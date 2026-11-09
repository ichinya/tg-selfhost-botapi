"""Qualification receipts and trusted Actions history; no registry writes."""
import argparse
import signal
import time
import uuid
import shutil
import copy
import hashlib
import http.client
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

from image_inputs import CONTRACT, DIGEST, PLATFORMS, canonical, snapshot_hash, validate_snapshot

from multiarch_verify import (EVENTS, context_from_env, validate_context, validate_receipt,
                              validate_pair, validate_qualification, command, native_host,
                              verify_local)

def gh(*args, binary=False):
    result = subprocess.check_output(["gh", "api", *args], timeout=120)
    return result if binary else json.loads(result)


def find_qualification(inputs, repository, branch, index_digest):
    """Only artifacts of successful default-branch image workflows are eligible."""
    pages = gh("--paginate", "--slurp", f"repos/{repository}/actions/artifacts?per_page=100")
    for page in pages:
        for artifact in page["artifacts"]:
            if artifact.get("expired") or not artifact.get("name", "").startswith("qualification-" + inputs["build_key"] + "-"):
                continue
            created = datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))
            if created < datetime.now(timezone.utc) - timedelta(days=90):
                continue
            run_id = artifact["workflow_run"]["id"]
            run = gh(f"repos/{repository}/actions/runs/{run_id}")
            if run.get("conclusion") != "success" or run.get("head_branch") != branch or run.get("event") not in EVENTS:
                continue
            archive = gh(f"repos/{repository}/actions/artifacts/{artifact['id']}/zip", binary=True)
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                names = [name for name in bundle.namelist() if name == "qualification.json"]
                if len(names) != 1 or bundle.getinfo(names[0]).file_size > 2_000_000:
                    raise ValueError("Invalid qualification artifact contents")
                value = json.loads(bundle.read(names[0]))
            validate_qualification(value, inputs, repository, branch, run)
            # A reused receipt must retain successful *original* default-branch compilation.
            for receipt in value["children"].values():
                original = receipt["compile"]["context"]
                origin = gh(f"repos/{repository}/actions/runs/{original['run_id']}")
                if (origin.get("status") != "completed" or origin.get("conclusion") != "success"
                        or origin.get("repository", {}).get("full_name") != repository
                        or origin.get("head_branch") != branch or origin.get("event") != original["event"]
                        or origin.get("path") != original["workflow"] or origin.get("head_sha") != original["sha"]
                        or str(origin.get("run_attempt")) != original["run_attempt"]):
                    raise ValueError("Original compilation lacks successful default-branch Actions origin")
            if value["index_digest"] != index_digest:
                raise ValueError("Qualification index differs from immutable build tag")
            return value
    raise ValueError("Existing build has no retained trusted qualification; cannot rebuild or promote this K")



def exact_no_bot(status, body):
    try:
        return status == 404 and json.loads(body) == {"ok": False, "error_code": 404, "description": "Not Found"}
    except (ValueError, TypeError):
        return False


def smoke(image, architecture):
    """Run normal entrypoint, direct HTTP and shipped gateway with isolated resources."""
    suffix = uuid.uuid4().hex
    network, bot, gateway = ("issue22-" + n + "-" + suffix for n in ("net", "bot", "gateway"))
    command("docker", "pull", "--platform", "linux/" + architecture, "nginx:alpine")
    nginx = json.loads(command("docker", "image", "inspect", "nginx:alpine"))[0]
    if nginx.get("Os") != "linux" or nginx.get("Architecture") != architecture:
        raise ValueError("Gateway architecture mismatch")
    try:
        command("docker", "network", "create", "--internal", network)
        command("docker", "run", "-d", "--name", bot, "--network", network, "--network-alias", "botapi",
                "--publish", "127.0.0.1::8081", "--memory", "1g",
                "--tmpfs", "/var/lib/telegram-bot-api", "--tmpfs", "/tmp/telegram-bot-api",
                "-e", "TELEGRAM_API_ID=12345", "-e", "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef", image)
        config = str(Path(__file__).resolve().parents[1] / "nginx.conf")
        command("docker", "run", "-d", "--name", gateway, "--network", network,
                "--publish", "127.0.0.1::80", "--memory", "128m", "--mount",
                f"type=bind,source={config},target=/etc/nginx/conf.d/default.conf,readonly", nginx["Id"])
        command("docker", "exec", gateway, "nginx", "-t")
        for name, port in ((bot, "8081/tcp"), (gateway, "80/tcp")):
            address = command("docker", "port", name, port).strip()
            host, number = address.rsplit(":", 1)
            if host != "127.0.0.1":
                raise ValueError("Smoke port must be loopback")
            for attempt in range(30):
                connection = http.client.HTTPConnection(host, int(number), timeout=2)
                try:
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    if exact_no_bot(response.status, response.read(65536)):
                        break
                except (OSError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
                time.sleep(1)
            else:
                raise ValueError("Exact no-bot HTTP response absent")
        command("docker", "exec", "--user", "telegram-bot-api", bot, "sh", "-ec",
                'test "$(stat -c %u "$TELEGRAM_WORK_DIR")" = 101; '
                'test "$(stat -c %u "$TELEGRAM_TEMP_DIR")" = 101; '
                'test -w "$TELEGRAM_WORK_DIR"; test -w "$TELEGRAM_TEMP_DIR"')
        return {"status": "PASS", "signature": "404/Not Found", "gateway_config_id": nginx["Id"], "network": "internal"}
    finally:
        for name in (gateway, bot):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=60)


def sender_probe(image, architecture, inputs, runtime):
    checked = verify_local(image, architecture, inputs)
    if checked["elf_sha256"] != runtime["elf_sha256"] or checked["version"] != runtime["version"]:
        raise ValueError("Sender and runtime did not use the same production binary")
    names = ["issue22-sender-" + uuid.uuid4().hex for _ in range(2)]
    try:
        result = json.loads(command("docker", "run", "--rm", "--name", names[0], "--network", "none",
                                    "--entrypoint", "python3", checked["image_id"], "/opt/webhook_sender/receiver.py"))
        if result != {"status": "PASS", "post": True, "user_agent": "WebhookDelivery/1.0", "queue_acknowledged": True}:
            raise ValueError("Production sender did not prove exact HTTP header and queue ACK")
        negative = subprocess.run(["docker", "run", "--rm", "--name", names[1], "--network", "none",
                                   "--entrypoint", "python3", checked["image_id"], "/opt/webhook_sender/receiver.py",
                                   "--expected", "DeliberatelyWrong/1.0"], capture_output=True, timeout=30)
        if negative.returncode != 1:
            raise ValueError("Wrong-UA negative control did not fail as expected")
        return {"status": "PASS", "negative": "PASS", "image_id": checked["image_id"],
                "elf_sha256": checked["elf_sha256"], "queue_acknowledged": True}
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def make_report(image, architecture, inputs, context):
    checked = verify_local(image, architecture, inputs)
    return {"schema": 2, "contract": inputs["verification_contract"], "build_key": inputs["build_key"],
            "snapshot_hash": snapshot_hash(inputs), "platform": "linux/" + architecture, "inputs": inputs,
            "run_url": f"https://github.com/{context['repository']}/actions/runs/{context['run_id']}/attempts/{context['run_attempt']}",
            "context": context, "local": checked, "registry": None,
            "checks": {key: "PASS" for key in ("config", "elf", "version", "ua", "native", "entrypoint_syntax")}}


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return "sha256:" + result.hexdigest()


def prepare_native(inputs, architecture, plan, directory):
    native_host(architecture)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "start.json").write_bytes(canonical({"time": time.time(), "disk": shutil.disk_usage(directory)._asdict()}))
    mode = plan.get("mode")
    if mode not in ("build", "reuse"):
        raise ValueError("Unknown preparation mode")
    if mode == "reuse":
        from multiarch_verify import validate_qualification
        value = plan["qualification"]
        validate_qualification(value, inputs, os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"])
        receipt = value["children"][architecture]
        ref = "ghcr.io/" + os.environ["GITHUB_REPOSITORY"].lower() + "@" + receipt["registry"]["manifest_digest"]
        command("docker", "pull", "--platform", "linux/" + architecture, ref)
        command("docker", "tag", ref, "botapi-candidate:check")
        sender = receipt["sender"]
        sender_ref = "ghcr.io/" + os.environ["GITHUB_REPOSITORY"].lower() + "@" + sender["manifest_digest"]
        command("docker", "pull", "--platform", "linux/" + architecture, sender_ref)
        command("docker", "tag", sender_ref, "botapi-sender:check")
    return mode


def runtime_contents(image):
    name = "issue22-contents-" + uuid.uuid4().hex
    try:
        output = command("docker", "run", "--rm", "--name", name, "--network", "none", "--entrypoint", "sh", image, "-ec",
                         "test -s /usr/share/licenses/telegram-bot-api/LICENSE_1_0.txt; "
                         "test ! -e /usr/local/libexec/webhook-sender; "
                         "test ! -e /opt/webhook_sender/receiver.py; ldd /usr/local/bin/telegram-bot-api")
        if "not found" in output.lower() or "error loading" in output.lower():
            raise ValueError("Runtime libraries unavailable")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def finish_native(inputs, architecture, plan, directory, build_result, metadata):
    from multiarch_verify import context_from_env, validate_receipt
    context = context_from_env()
    report = make_report("botapi-candidate:check", architecture, inputs, context)
    report["mode"] = plan["mode"]
    runtime_contents(report["local"]["image_id"])
    report["checks"]["runtime_contents"] = "PASS"
    report["sender"] = sender_probe("botapi-sender:check", architecture, inputs, report["local"])
    sender_archive = directory / "sender.tar"
    command("docker", "save", "--output", str(sender_archive), report["sender"]["image_id"])
    report["sender"]["archive_sha256"] = file_hash(sender_archive)
    report["smoke"] = smoke(report["local"]["image_id"], architecture)
    archive = directory / "image.tar"
    command("docker", "save", "--output", str(archive), report["local"]["image_id"])
    report["archive_sha256"] = file_hash(archive)
    if plan["mode"] == "build":
        record = json.loads(metadata)
        if build_result != "success" or not record or not record.get("buildx.build.ref"):
            raise ValueError("No successful cold Buildx build record")
        report["compile"] = {"status": "PASS", "patch": "PASS", "cmake": "PASS", "cold": True,
                             "config_id": report["local"]["image_id"], "snapshot_hash": snapshot_hash(inputs),
                             "context": context, "build_record": record}
    else:
        original = plan["qualification"]["children"][architecture]
        report["compile"] = copy.deepcopy(original["compile"])
        report["registry"] = copy.deepcopy(original["registry"])
        report["sender"]["manifest_digest"] = original["sender"]["manifest_digest"]
        if report["local"] != original["local"]:
            raise ValueError("Reused immutable binary/config evidence changed")
    start = json.loads((directory / "start.json").read_text())
    report["resources"] = {"elapsed_seconds": time.time() - start["time"], "archive_bytes": archive.stat().st_size,
                           "disk_before": start["disk"], "disk_after": shutil.disk_usage(directory)._asdict(),
                           "docker_usage": command("docker", "system", "df")}
    validate_receipt(report, inputs, context)
    (directory / "receipt.json").write_bytes(canonical(report) + b"\n")


if __name__ == "__main__":
    def terminated(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, terminated)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify", "plan"))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--snapshot-hash", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--arch", choices=("amd64", "arm64"))
    parser.add_argument("--directory", default="artifacts")
    args = parser.parse_args()
    inputs = validate_snapshot(json.loads(Path(args.snapshot).read_text()), args.snapshot_hash)
    if args.action == "plan":
        from image_inputs import Registry
        from multiarch_verify import verify_release_index, verify_remote
        repository, branch = os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"]
        registry = Registry("ghcr.io", repository.lower(), os.environ.get("GITHUB_ACTOR"), os.environ.get("GH_TOKEN"))
        existing = registry.manifest("build-" + inputs["build_key"], missing=True)
        plan = {"mode": "build", "qualification": None}
        if existing is not None:
            index_digest, index = existing
            children = verify_release_index(index)
            value = find_qualification(inputs, repository, branch, index_digest)
            for arch, child in children.items():
                receipt = value["children"][arch]
                if receipt["registry"]["manifest_digest"] != child:
                    raise ValueError("Qualification child mapping mismatch")
                verify_remote(registry, child, arch, inputs, receipt["local"]["image_id"])
            plan = {"mode": "reuse", "qualification": value}
        Path(args.plan).write_bytes(canonical(plan) + b"\n")
        print("mode=" + plan["mode"])
        raise SystemExit(0)
    plan = json.loads(Path(args.plan).read_text())
    directory = Path(args.directory)
    if args.action == "prepare":
        print("mode=" + prepare_native(inputs, args.arch, plan, directory))
    else:
        finish_native(inputs, args.arch, plan, directory, os.environ.get("BUILD_RESULT"), os.environ.get("BUILD_METADATA", "{}"))
