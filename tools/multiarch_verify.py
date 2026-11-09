"""Offline primitives for checking multi-platform image metadata and ELF files.

These checks alone do not qualify an image for publication.
"""
import hashlib
import re
import struct
import json
import subprocess
import tempfile
from pathlib import Path
import platform
import time
import uuid
import argparse
import os
import copy
import shutil
from image_inputs import (CONTRACT, PLATFORMS, DIGEST, MANIFEST_TYPES, CONFIG_TYPES,
                          sha256, canonical, snapshot_hash, validate_snapshot)


MACHINES = {"amd64": 62, "arm64": 183}


def verify_elf(data, architecture):
    """Validate a little-endian ELF64 binary and return its SHA-256 digest."""
    if architecture not in MACHINES:
        raise ValueError("unsupported architecture")
    if (len(data) < 64 or data[:4] != b"\x7fELF" or data[4:7] != b"\x02\x01\x01"
            or struct.unpack_from("<I", data, 20)[0] != 1
            or struct.unpack_from("<H", data, 52)[0] != 64):
        raise ValueError("expected a little-endian ELF64 binary")
    if struct.unpack_from("<H", data, 18)[0] != MACHINES[architecture]:
        raise ValueError("ELF architecture mismatch")
    if b"WebhookDelivery/1.0\0" not in data:
        raise ValueError("missing webhook User-Agent")
    return hashlib.sha256(data).hexdigest()


def verify_release_index(index, expected=None):
    """Release policy v2 permits exactly two runnable children, no attestations."""
    if (not isinstance(index, dict) or index.get("schemaVersion") != 2
            or index.get("mediaType") not in (
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json")
            or not isinstance(index.get("manifests"), list)):
        raise ValueError("invalid image index")
    children = {}
    for descriptor in index["manifests"]:
        if not isinstance(descriptor, dict):
            raise ValueError("invalid descriptor")
        digest = descriptor.get("digest")
        platform = descriptor.get("platform")
        if (not isinstance(digest, str) or not DIGEST.fullmatch(digest) or not isinstance(platform, dict)
                or descriptor.get("mediaType") not in MANIFEST_TYPES
                or type(descriptor.get("size")) is not int or descriptor["size"] <= 0):
            raise ValueError("invalid descriptor digest or platform")
        os_name, arch = platform.get("os"), platform.get("architecture")
        if os_name != "linux" or arch not in MACHINES or arch in children:
            raise ValueError("unexpected or duplicate runnable platform")
        variant = platform.get("variant", "")
        if variant not in (("", "v8") if arch == "arm64" else ("",)):
            raise ValueError("unexpected platform variant")
        children[arch] = digest
    if set(children) != set(MACHINES):
        raise ValueError("incomplete image index")
    if len(set(children.values())) != len(children):
        raise ValueError("duplicate child digest")
    if expected is not None and children != expected:
        raise ValueError("child digest mismatch")
    return children


def verify_config(config, architecture, inputs):
    if config.get("Os") != "linux" or config.get("Architecture") != architecture:
        raise ValueError("image config platform mismatch")
    if config.get("Variant", "") not in (("", "v8") if architecture == "arm64" else ("",)):
        raise ValueError("image config variant mismatch")
    labels = config.get("Config", {}).get("Labels") or {}
    expected = {
        "org.opencontainers.image.source": "https://github.com/ichinya/tg-selfhost-botapi",
        "io.tg-selfhost.bot-api-revision": inputs["bot_api_revision"],
        "io.tg-selfhost.base-reference": inputs["alpine_image"],
        "io.tg-selfhost.build-key": inputs["build_key"],
        "io.tg-selfhost.verification-contract": inputs["verification_contract"],
        "io.tg-selfhost.platform-set": ",".join(sorted(inputs["platforms"])),
    }
    if any(labels.get(key) != value for key, value in expected.items()):
        raise ValueError("image labels mismatch")


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120).stdout.strip()


def native_host(architecture):
    aliases = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    host = aliases.get(platform.machine().lower())
    daemon = json.loads(command("docker", "info", "--format", "{{json .}}"))
    cpu = aliases.get(daemon.get("Architecture", "").lower())
    if platform.system() != "Linux" or host != architecture or cpu != architecture or daemon.get("OSType") != "linux":
        raise ValueError("Native Linux host/daemon architecture required; no QEMU fallback")
    return {"host": host, "daemon": cpu, "os": "linux"}


def verify_version(output, expected=None):
    # Official telegram-bot-api.cpp prints LOG(PLAIN) << "Bot API " << version_.
    match = re.fullmatch(r"Bot API (\d+\.\d+(?:\.\d+)?)", output.strip())
    if not match or (expected is not None and match[1] != expected):
        raise ValueError("Unexpected Bot API version output")
    return match[1]


def validate_source_identity(text, inputs):
    lines = text.splitlines()
    patch = sha256((Path(__file__).resolve().parents[1] / "patches/webhook-user-agent.patch").read_bytes()).split(":")[1]
    if (len(lines) < 3 or lines[0] != inputs["bot_api_revision"]
            or lines[1] != patch + "  /tmp/webhook-user-agent.patch"
            or any(not re.fullmatch(r" [0-9a-f]{40} [^\r\n]+", line) for line in lines[2:])):
        raise ValueError("Source/patch/submodule compilation identity mismatch")
    return {"revision": lines[0], "patch_sha256": "sha256:" + patch, "submodules": lines[2:]}


def verify_stored_image(image, architecture, inputs):
    inspected = json.loads(command("docker", "image", "inspect", image))
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise ValueError("invalid docker inspection")
    config = inspected[0]
    verify_config(config, architecture, inputs)
    image_id = config.get("Id", "")
    if not DIGEST.fullmatch(image_id):
        raise ValueError("invalid image ID")
    container = "issue22-extract-" + uuid.uuid4().hex
    try:
        identifier = command("docker", "create", "--name", container, image_id)
        if not re.fullmatch(r"[0-9a-f]{12,64}", identifier):
            raise ValueError("Invalid temporary container ID")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "telegram-bot-api"
            command("docker", "cp", container + ":/usr/local/bin/telegram-bot-api", str(binary))
            binary_hash = verify_elf(binary.read_bytes(), architecture)
            identity = Path(directory) / "source-identity.txt"
            command("docker", "cp", container + ":/usr/share/botapi/source-identity.txt", str(identity))
            source = validate_source_identity(identity.read_text(), inputs)
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=60)
    rootfs = config.get("RootFS", {}).get("Layers", [])
    if not rootfs or any(not DIGEST.fullmatch(x) for x in rootfs):
        raise ValueError("Missing local rootfs identity")
    return {"image_id": image_id, "elf_sha256": binary_hash, "rootfs": rootfs, "source": source}


def verify_local(image, architecture, inputs):
    native = native_host(architecture)
    stored = verify_stored_image(image, architecture, inputs)
    image_id, binary_hash = stored["image_id"], stored["elf_sha256"]
    names = ["issue22-version-" + uuid.uuid4().hex, "issue22-syntax-" + uuid.uuid4().hex]
    try:
        result = subprocess.run(["docker", "run", "--rm", "--name", names[0], "--network", "none",
                                 "--entrypoint", "/docker-entrypoint.sh", image_id, "--version"],
                                check=True, capture_output=True, text=True, timeout=120)
        version = verify_version(result.stdout + result.stderr, inputs.get("expected_version"))
        command("docker", "run", "--rm", "--name", names[1], "--network", "none", "--entrypoint", "sh", image_id, "-n", "/docker-entrypoint.sh")
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
    return {"image_id": image_id, "elf_sha256": binary_hash, "version": version,
            "native": native, "ua": "WebhookDelivery/1.0", "rootfs": stored["rootfs"], "source": stored["source"]}


def verify_remote(registry, child, architecture, inputs, config_id=None):
    digest, manifest = registry.manifest(child)
    if digest != child or manifest.get("schemaVersion") != 2 or manifest.get("mediaType") not in MANIFEST_TYPES:
        raise ValueError("Invalid remote child identity/type")
    descriptor = manifest.get("config", {})
    config_digest = descriptor.get("digest", "")
    if descriptor.get("mediaType") not in CONFIG_TYPES or not DIGEST.fullmatch(config_digest):
        raise ValueError("Invalid registry config descriptor")
    if config_id and config_id != config_digest:
        raise ValueError("Registry config differs from tested local image ID")
    raw = registry.get("blobs", config_digest)
    if sha256(raw) != config_digest or descriptor.get("size") != len(raw):
        raise ValueError("Registry config hash/size mismatch")
    config = json.loads(raw)
    variant = config.get("variant", "")
    if variant not in (("", "v8") if architecture == "arm64" else ("",)):
        raise ValueError("Remote config variant mismatch")
    rootfs = config.get("rootfs", {})
    if (rootfs.get("type") != "layers" or not isinstance(rootfs.get("diff_ids"), list)
            or not rootfs["diff_ids"] or any(not DIGEST.fullmatch(x) for x in rootfs["diff_ids"])):
        raise ValueError("Invalid remote rootfs")
    verify_config({"Os": config.get("os"), "Architecture": config.get("architecture"),
                   "Config": {"Labels": config.get("config", {}).get("Labels")}}, architecture, inputs)
    size = registry.manifest_sizes.get(child)
    if type(size) is not int or size <= 0:
        raise ValueError("Missing raw child manifest size")
    return {"manifest_digest": child, "config_digest": config_digest, "manifest_size": size}



CHECKS = {key: "PASS" for key in ("config", "elf", "version", "ua", "native", "entrypoint_syntax", "runtime_contents")}
EVENTS = ("push", "schedule", "workflow_dispatch")


def context_from_env():
    return {"repository": os.environ["GITHUB_REPOSITORY"], "workflow": ".github/workflows/image.yml",
            "event": os.environ["GITHUB_EVENT_NAME"], "branch": os.environ["GITHUB_REF_NAME"],
            "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "sha": os.environ["GITHUB_SHA"]}


def validate_context(context):
    if (context.get("workflow") != ".github/workflows/image.yml"
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", context.get("repository", ""))
            or not re.fullmatch(r"[0-9a-f]{40}", context.get("sha", ""))
            or any(not re.fullmatch(r"[1-9][0-9]*", str(context.get(key, ""))) for key in ("run_id", "run_attempt"))
            or not context.get("branch") or context.get("event") not in EVENTS + ("pull_request",)):
        raise ValueError("Invalid workflow context")


def validate_receipt(receipt, inputs, context=None, published=False):
    if (receipt.get("schema") != 2 or receipt.get("contract") != CONTRACT
            or receipt.get("build_key") != inputs["build_key"]
            or receipt.get("snapshot_hash") != snapshot_hash(inputs) or receipt.get("inputs") != inputs
            or receipt.get("platform") not in PLATFORMS or receipt.get("checks") != CHECKS):
        raise ValueError("Incomplete or foreign receipt")
    validate_context(receipt.get("context", {}))
    if context is not None and receipt["context"] != context:
        raise ValueError("Receipt belongs to another run/attempt")
    local = receipt.get("local", {})
    arch = receipt["platform"].split("/")[1]
    if (not DIGEST.fullmatch(local.get("image_id", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", local.get("elf_sha256", ""))
            or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", local.get("version", "")) or local.get("ua") != "WebhookDelivery/1.0"
            or local.get("native") != {"host": arch, "daemon": arch, "os": "linux"}
            or receipt.get("smoke", {}).get("status") != "PASS"
            or not DIGEST.fullmatch(receipt.get("archive_sha256", ""))):
        raise ValueError("Missing native/archive evidence")
    source = local.get("source", {})
    patch_digest = sha256((Path(__file__).resolve().parents[1] / "patches/webhook-user-agent.patch").read_bytes())
    if (source.get("revision") != inputs["bot_api_revision"] or source.get("patch_sha256") != patch_digest
            or not source.get("submodules")
            or any(not re.fullmatch(r" [0-9a-f]{40} [^\r\n]+", line) for line in source["submodules"])):
        raise ValueError("Missing source/patch/submodule identity")
    sender = receipt.get("sender", {})
    if (sender.get("status") != "PASS" or sender.get("negative") != "PASS"
            or sender.get("queue_acknowledged") is not True
            or not DIGEST.fullmatch(sender.get("image_id", ""))
            or sender.get("elf_sha256") != local["elf_sha256"]
            or not DIGEST.fullmatch(sender.get("archive_sha256", ""))):
        raise ValueError("Missing production sender/negative-control evidence")
    if published or receipt.get("mode") == "reuse":
        if not DIGEST.fullmatch(sender.get("manifest_digest", "")):
            raise ValueError("Missing retained sender image binding")
    if (not isinstance(local.get("rootfs"), list) or not local["rootfs"]
            or any(not DIGEST.fullmatch(x) for x in local["rootfs"])):
        raise ValueError("Missing tested rootfs")
    compile_proof = receipt.get("compile", {})
    if (compile_proof.get("status") != "PASS" or compile_proof.get("patch") != "PASS"
            or compile_proof.get("cmake") != "PASS" or compile_proof.get("cold") is not True
            or compile_proof.get("config_id") != local["image_id"]
            or compile_proof.get("snapshot_hash") != snapshot_hash(inputs)
            or not isinstance(compile_proof.get("build_record"), dict)
            or not compile_proof["build_record"].get("buildx.build.ref")):
        raise ValueError("Missing original cold compilation proof")
    validate_context(compile_proof.get("context", {}))
    if (compile_proof["context"]["repository"] != receipt["context"]["repository"]
            or (receipt["context"]["event"] in EVENTS and
                (compile_proof["context"]["branch"] != receipt["context"]["branch"]
                 or compile_proof["context"]["event"] not in EVENTS))):
        raise ValueError("Foreign original compilation")
    if receipt.get("mode") == "build" and compile_proof["context"] != receipt["context"]:
        raise ValueError("Fresh build needs current compilation proof")
    if receipt.get("mode") not in ("build", "reuse"):
        raise ValueError("Unknown receipt mode")
    registry = receipt.get("registry")
    if published or receipt["mode"] == "reuse":
        if (not isinstance(registry, dict) or not DIGEST.fullmatch(registry.get("manifest_digest", ""))
                or registry.get("config_digest") != local["image_id"]
                or type(registry.get("manifest_size")) is not int or registry["manifest_size"] <= 0
                or compile_proof.get("manifest_digest") != registry["manifest_digest"]):
            raise ValueError("Missing immutable compilation/registry binding")
    return receipt


def validate_pair(receipts, inputs, context=None, published=False):
    if len(receipts) != 2:
        raise ValueError("Exactly two receipts required")
    mapped = {}
    for receipt in receipts:
        validate_receipt(receipt, inputs, context, published)
        arch = receipt["platform"].split("/")[1]
        if arch in mapped:
            raise ValueError("Duplicate platform receipt")
        mapped[arch] = receipt
    if set(mapped) != {"amd64", "arm64"}:
        raise ValueError("Missing required platform receipt")
    if mapped["amd64"]["local"]["image_id"] == mapped["arm64"]["local"]["image_id"]:
        raise ValueError("Distinct native images required")
    if mapped["amd64"]["local"]["version"] != mapped["arm64"]["local"]["version"]:
        raise ValueError("Platform versions differ")
    return mapped


def validate_qualification(value, inputs, repository, branch, run=None):
    context = value.get("context", {})
    if (value.get("schema") != 2 or value.get("status") != "QUALIFIED"
            or value.get("snapshot_hash") != snapshot_hash(inputs) or value.get("inputs") != inputs
            or value.get("contract") != CONTRACT or value.get("build_key") != inputs["build_key"]
            or context.get("repository") != repository or context.get("branch") != branch
            or context.get("event") not in EVENTS or not DIGEST.fullmatch(value.get("index_digest", ""))):
        raise ValueError("Untrusted qualification")
    pair = validate_pair(list(value.get("children", {}).values()), inputs, context, published=True)
    if set(value["children"]) != set(pair):
        raise ValueError("Qualification platform mapping mismatch")
    for arch, receipt in pair.items():
        if receipt["platform"] != "linux/" + arch or receipt != value["children"][arch]:
            raise ValueError("Qualification receipt key mismatch")
    if run is not None:
        if (run.get("conclusion") != "success" or run.get("status") != "completed"
                or run.get("repository", {}).get("full_name") != repository
                or run.get("head_branch") != branch or run.get("event") != context["event"]
                or run.get("path") != ".github/workflows/image.yml"
                or str(run.get("id")) != context["run_id"] or str(run.get("run_attempt")) != context["run_attempt"]
                or run.get("head_sha") != context["sha"]):
            raise ValueError("Qualification not from a successful trusted default-branch workflow")
    return pair
