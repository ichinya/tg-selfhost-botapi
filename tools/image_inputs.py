"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RECIPE = (
    "Dockerfile", ".dockerignore", "docker-entrypoint.sh", "patches/webhook-user-agent.patch",
    "tools/image_inputs.py", "tools/test_image_inputs.py", "tools/test_entrypoint.py",
    "tools/test_webhook_user_agent.py",
    "docker-compose.yml", "docker-compose.build.yml", "docker-compose.nonroot.yml",
    "tools/check_runtime_permissions.py",
    "tools/fixtures/issue21/entrypoint-probe.sh",
    "tools/fixtures/issue21/docker-compose.reader.yml",
    "tools/fixtures/issue21/reader-probe.sh",
    "tools/fixtures/issue21/test_runtime_permissions.py",
    ".github/workflows/image.yml",
)


def command(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def revision(repository):
    value = command("git", "ls-remote", f"https://github.com/{repository}.git", "refs/heads/master").split()[0]
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"Invalid revision from {repository}")
    return value


def digest(image):
    value = json.loads(command("docker", "buildx", "imagetools", "inspect", image,
                               "--format", "{{json .Manifest}}"))["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"Invalid digest from {image}")
    return value


def build_key(inputs, files):
    # File names and length boundaries prevent ambiguous concatenations.
    result = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode())
    for name, content in sorted(files.items()):
        result.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return result.hexdigest()[:32]


def resolve():
    inputs = {
        "bot_api_revision": revision("tdlib/telegram-bot-api"),
        "alpine_image": "alpine:3.22@" + digest("alpine:3.22"),
    }
    inputs["build_key"] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
    return inputs


if __name__ == "__main__":
    for key, value in resolve().items():
        print(f"{key}={value}")
