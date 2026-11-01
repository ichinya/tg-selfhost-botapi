"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RECIPE = (
    "Dockerfile", ".dockerignore", "patches/webhook-user-agent.patch",
    "tools/image_inputs.py", "tools/test_image_inputs.py", ".github/workflows/image.yml",
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
        "aiogram_revision": revision("aiogram/telegram-bot-api"),
        "aiogram_image_digest": digest("aiogram/telegram-bot-api:latest"),
        "alpine_image": "alpine:3.22@" + digest("alpine:3.22"),
    }
    inputs["build_key"] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
    return inputs


if __name__ == "__main__":
    for key, value in resolve().items():
        print(f"{key}={value}")
