"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RECIPE = (
    "Dockerfile", ".dockerignore", "docker-entrypoint.sh", "patches/webhook-user-agent.patch",
    "tools/apk_policy.json", "tools/image_inputs.py", "tools/test_image_inputs.py", "tools/test_entrypoint.py",
    "tools/test_webhook_user_agent.py",
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


def validate_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != {"policy_version", "refresh", "generation"}
            or type(policy["policy_version"]) is not int or policy["policy_version"] != 1
            or policy["refresh"] != "utc-day" or type(policy["generation"]) is not int
            or policy["generation"] < 0):
        raise ValueError("Invalid APK refresh policy")
    return policy


def read_policy(path):
    with open(path, encoding="utf-8") as handle:
        return validate_policy(json.load(handle))


def check_generation(current, previous):
    validate_policy(current)
    if previous is not None and current["generation"] < validate_policy(previous)["generation"]:
        raise ValueError("APK refresh generation cannot decrease")


def resolve(clock=None, policy=None, platform="linux/amd64"):
    policy = read_policy(ROOT / "tools/apk_policy.json") if policy is None else validate_policy(policy)
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Clock must be timezone-aware")
    window = now.astimezone(timezone.utc).date().isoformat()
    inputs = {
        "snapshot_version": 1,
        "bot_api_revision": revision("tdlib/telegram-bot-api"),
        "alpine_image": "alpine:3.22@" + digest("alpine:3.22"),
        "platform": platform,
        **policy,
        "apk_refresh_window": window,
        "apk_refresh_id": f"v{policy['policy_version']}-{window}-g{policy['generation']}",
    }
    inputs["build_key"] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
    return inputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    args = parser.parse_args()
    inputs = resolve()
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(inputs, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for key, value in inputs.items():
        print(f"{key}={value}")
