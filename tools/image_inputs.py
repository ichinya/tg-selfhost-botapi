"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RECIPE = (
    "Dockerfile", ".dockerignore", "docker-entrypoint.sh", "patches/webhook-user-agent.patch",
    "tools/apk_policy.json", "tools/image_inputs.py", "tools/test_image_inputs.py", "tools/test_entrypoint.py",
    "tools/test_webhook_user_agent.py",
    ".github/workflows/image.yml",
    "tools/capture_apk_metadata.sh",
    "tools/test_apk_docker_contract.py",
    "tools/capture_link_metadata.py",
    "tools/image_metadata.py",
    "tools/image_receipt.py",
    "tools/test_image_metadata.py",
    "tools/apk_candidate.py",
    "tools/test_apk_candidate.py",
    "tools/check_apk_refresh.py",
    "tools/test_apk_refresh.py",
    "tools/apk_refresh_fixture/fixture.c",
    "tools/apk_refresh_fixture/consumer.c",
    "tools/apk_refresh_fixture/APKBUILD.in",
    "tools/apk_refresh_fixture/package.sh",
    "tools/apk_refresh_fixture/SHA256SUMS",
    "tools/apk_refresh_fixture/LICENSE",
    "tools/apk_refresh_fixture/README.md",
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


def atomic_write(path, content):
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    parser.add_argument("--build-env-out")
    args = parser.parse_args()
    if args.json_out and args.build_env_out and Path(args.json_out).resolve() == Path(args.build_env_out).resolve():
        parser.error("JSON and build env must use different paths")
    inputs = resolve()
    if args.json_out:
        atomic_write(args.json_out, json.dumps(inputs, sort_keys=True, indent=2) + "\n")
    if args.build_env_out:
        public = {
            "BOT_API_REVISION": inputs["bot_api_revision"],
            "ALPINE_IMAGE": inputs["alpine_image"],
            "BUILD_FINGERPRINT": inputs["build_key"],
            "APK_REFRESH_ID": inputs["apk_refresh_id"],
            "APK_POLICY_VERSION": inputs["policy_version"],
            "APK_REFRESH_WINDOW": inputs["apk_refresh_window"],
            "APK_REFRESH_GENERATION": inputs["generation"],
            "BUILD_PLATFORM": inputs["platform"],
        }
        atomic_write(args.build_env_out, "".join(f"{key}={value}\n" for key, value in public.items()))
    for key, value in inputs.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
