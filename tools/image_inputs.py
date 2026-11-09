"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import argparse
import base64
import urllib.request
import urllib.error
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("linux/amd64", "linux/arm64")
CONTRACT = "native-multiarch-v3"
SCHEMA = 2
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")
CONFIG_TYPES = ("application/vnd.oci.image.config.v1+json", "application/vnd.docker.container.image.v1+json")
RECIPE = (
    "Dockerfile", ".dockerignore", "docker-entrypoint.sh", "nginx.conf", "patches/webhook-user-agent.patch",
    "tools/image_inputs.py", "tools/test_image_inputs.py", "tools/test_entrypoint.py",
    "tools/test_webhook_user_agent.py",
    "tools/multiarch_verify.py", "tools/test_multiarch_verify.py",
    "tools/multiarch_qualify.py", "tools/test_multiarch_qualify.py",
    "tools/webhook_sender/CMakeLists.txt", "tools/webhook_sender/webhook_sender_test.cpp",
    "tools/webhook_sender/receiver.py",
    "tools/multiarch_publish.py", "tools/test_multiarch_publish.py",
    ".github/workflows/image.yml",
)


def command(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def revision(repository):
    fields = command("git", "ls-remote", f"https://github.com/{repository}.git", "refs/heads/master").split()
    if len(fields) != 2 or fields[1] != "refs/heads/master" or not re.fullmatch(r"[0-9a-f]{40}", fields[0]):
        raise ValueError(f"Invalid revision from {repository}")
    return fields[0]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        destination = urllib.parse.urlparse(newurl)
        if destination.scheme != "https":
            raise ValueError("Registry redirect must use HTTPS")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if urllib.parse.urlparse(request.full_url).netloc != destination.netloc:
            redirected.remove_header("Authorization")
        return redirected


def registry_open(request, timeout):
    return urllib.request.build_opener(SafeRedirect()).open(request, timeout=timeout)


class Registry:
    """Read exact bytes. Only HTTP 404 means absence, never auth or timeout."""
    def __init__(self, host, repository, username=None, password=None):
        if not re.fullmatch(r"[a-z0-9.-]+", host) or not re.fullmatch(r"[a-z0-9._/-]+", repository):
            raise ValueError("Invalid registry repository")
        self.host, self.repository = host, repository
        self.username, self.password, self.bearer = username, password, None
        self.manifest_sizes = {}

    def get(self, kind, reference, missing=False):
        if kind not in ("manifests", "blobs") or not re.fullmatch(r"[A-Za-z0-9_.:-]+", reference):
            raise ValueError("Invalid registry reference")
        url = f"https://{self.host}/v2/{self.repository}/{kind}/{reference}"
        for attempt in range(2):
            headers = {"Accept": ", ".join(INDEX_TYPES + MANIFEST_TYPES)}
            if self.bearer:
                headers["Authorization"] = "Bearer " + self.bearer
            try:
                with registry_open(urllib.request.Request(url, headers=headers), timeout=60) as response:
                    raw = response.read()
                    announced = response.headers.get("Docker-Content-Digest")
                actual = sha256(raw)
                if (announced and announced != actual) or (reference.startswith("sha256:") and reference != actual):
                    raise ValueError("Registry content digest mismatch")
                return raw
            except urllib.error.HTTPError as error:
                if error.code == 404 and missing:
                    return None
                if error.code != 401 or attempt:
                    raise RuntimeError(f"Registry HTTP {error.code}; no publication allowed") from None
                challenge = error.headers.get("WWW-Authenticate", "")
                params = dict(re.findall(r'(\w+)="([^"]+)"', challenge))
                realm = urllib.parse.urlparse(params.get("realm", ""))
                allowed = {self.host}
                if self.host == "registry-1.docker.io":
                    allowed.add("auth.docker.io")
                if not challenge.lower().startswith("bearer ") or realm.scheme != "https" or realm.hostname not in allowed or realm.username or realm.port not in (None, 443):
                    raise ValueError("Untrusted registry auth challenge")
                query = urllib.parse.urlencode({"service": params.get("service", self.host), "scope": f"repository:{self.repository}:pull"})
                auth_headers = {}
                if self.password and realm.hostname == self.host:
                    encoded = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
                    auth_headers["Authorization"] = "Basic " + encoded
                request = urllib.request.Request(urllib.parse.urlunparse(realm._replace(query=query)), headers=auth_headers)
                try:
                    with registry_open(request, timeout=60) as response:
                        token = json.load(response)
                    self.bearer = token.get("token") or token.get("access_token")
                    if not isinstance(self.bearer, str) or not self.bearer:
                        raise ValueError("Invalid registry token response")
                except urllib.error.HTTPError as auth_error:
                    raise RuntimeError(f"Registry authentication HTTP {auth_error.code}") from None
        raise RuntimeError("Registry authentication failed")

    def manifest(self, reference, missing=False):
        raw = self.get("manifests", reference, missing=missing)
        if raw is None:
            return None
        actual = sha256(raw)
        self.manifest_sizes[actual] = len(raw)
        return actual, json.loads(raw)


def digest(image):
    value = json.loads(command("docker", "buildx", "imagetools", "inspect", image,
                               "--format", "{{json .Manifest}}"))["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"Invalid digest from {image}")
    return value


def platforms(values):
    if not isinstance(values, (list, tuple)) or len(values) != 2 or set(values) != set(PLATFORMS):
        raise ValueError("Expected exactly linux/amd64 and linux/arm64")
    return sorted(values)


def validate_base_index(raw):
    index = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if index.get("schemaVersion") != 2 or index.get("mediaType") not in (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ) or not isinstance(index.get("manifests"), list):
        raise ValueError("Base is not a valid image index")
    found = {}
    for item in index["manifests"]:
        platform = item.get("platform", {})
        name = platform.get("os", "") + "/" + platform.get("architecture", "")
        if name in PLATFORMS:
            variant = platform.get("variant")
            if (name == "linux/amd64" and variant not in (None, "")) or (
                name == "linux/arm64" and variant not in (None, "", "v8")
            ):
                raise ValueError("Unexpected base platform variant")
            if (item.get("mediaType") not in MANIFEST_TYPES
                    or type(item.get("size")) is not int or item["size"] <= 0):
                raise ValueError("Invalid base descriptor type/size")
            child = item.get("digest", "")
            if name in found or not re.fullmatch(r"sha256:[0-9a-f]{64}", child):
                raise ValueError("Duplicate or invalid base child")
            found[name] = child
    if set(found) != set(PLATFORMS) or len(set(found.values())) != len(PLATFORMS):
        raise ValueError("Base index lacks distinct required platforms")
    return dict(sorted(found.items()))


def resolve_base(reference, registry):
    index_digest, index = registry.manifest(reference)
    children = validate_base_index(index)
    sizes = {item["digest"]: item["size"] for item in index["manifests"] if item.get("digest") in children.values()}
    for platform, child in children.items():
        actual_child, manifest = registry.manifest(child)
        if actual_child != child or registry.manifest_sizes.get(child) != sizes[child]:
            raise ValueError("Base child digest mismatch")
        if manifest.get("schemaVersion") != 2 or manifest.get("mediaType") not in MANIFEST_TYPES:
            raise ValueError("Invalid base child manifest")
        descriptor = manifest.get("config", {})
        if descriptor.get("mediaType") not in CONFIG_TYPES or not DIGEST.fullmatch(descriptor.get("digest", "")):
            raise ValueError("Invalid base config descriptor")
        raw = registry.get("blobs", descriptor["digest"])
        if sha256(raw) != descriptor["digest"] or len(raw) != descriptor.get("size"):
            raise ValueError("Base config hash/size mismatch")
        config = json.loads(raw)
        if config.get("os") != "linux" or config.get("architecture") != platform.split("/")[1]:
            raise ValueError("Base child/config platform mismatch")
    return index_digest, children


def checked_base(image):
    reference = image + "@" + digest(image)
    validate_base_index(command("docker", "buildx", "imagetools", "inspect", reference, "--raw"))
    return reference


def build_key(inputs, files):
    # File names and length boundaries prevent ambiguous concatenations.
    inputs = dict(inputs)
    if "platforms" in inputs:
        inputs["platforms"] = platforms(inputs["platforms"])
    result = hashlib.sha256(canonical(inputs))
    for name, content in sorted(files.items()):
        result.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return result.hexdigest()[:32]


def snapshot_hash(inputs):
    return sha256(canonical(inputs))


def validate_snapshot(inputs, expected_hash=None, root=ROOT):
    if inputs.get("schema") != SCHEMA or inputs.get("verification_contract") != CONTRACT:
        raise ValueError("Snapshot schema/policy mismatch")
    platforms(inputs.get("platforms"))
    if not re.fullmatch(r"[0-9a-f]{40}", inputs.get("bot_api_revision", "")):
        raise ValueError("Invalid snapshot source")
    if not re.fullmatch(r"alpine:3\.22@sha256:[0-9a-f]{64}", inputs.get("alpine_image", "")):
        raise ValueError("Invalid snapshot base index")
    children = inputs.get("base_children", {})
    if set(children) != set(PLATFORMS) or len(set(children.values())) != 2 or any(not DIGEST.fullmatch(x) for x in children.values()):
        raise ValueError("Invalid snapshot base mapping")
    identity = {k: v for k, v in inputs.items() if k != "build_key"}
    key = build_key(identity, {name: (root / name).read_bytes() for name in RECIPE})
    if key != inputs.get("build_key") or (expected_hash and snapshot_hash(inputs) != expected_hash):
        raise ValueError("Snapshot hash/recipe mismatch")
    return inputs


def resolve():
    source = revision("tdlib/telegram-bot-api")
    registry = Registry("registry-1.docker.io", "library/alpine")
    index, children = resolve_base("3.22", registry)
    default = re.search(r"^ARG ALPINE_IMAGE=alpine:3\.22@(sha256:[0-9a-f]{64})$", (ROOT / "Dockerfile").read_text(), re.M)
    if not default:
        raise ValueError("Missing immutable Dockerfile base default")
    resolve_base(default[1], registry)
    inputs = {"schema": SCHEMA, "bot_api_revision": source,
              "alpine_image": "alpine:3.22@" + index, "base_children": children,
              "platforms": platforms(PLATFORMS), "verification_contract": CONTRACT}
    inputs["build_key"] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
    return inputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--input", help="Validate a saved snapshot without resolving upstream")
    parser.add_argument("--snapshot-hash")
    args = parser.parse_args()
    inputs = (validate_snapshot(json.loads(Path(args.input).read_text()), args.snapshot_hash)
              if args.input else resolve())
    if args.output:
        Path(args.output).write_bytes(canonical(inputs) + b"\n")
    print("snapshot_hash=" + snapshot_hash(inputs))
    for key in ("build_key", "bot_api_revision", "alpine_image", "verification_contract"):
        print(f"{key}={inputs[key]}")


if __name__ == "__main__":
    main()
