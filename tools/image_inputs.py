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
    "patches/botapi-secrets-redaction.patch",
    "tools/fixtures/issue17_security/botapi_log_driver.cpp",
    "tools/fixtures/issue17_security/cases.json",
    "tools/issue17_security_gate.py", "tools/issue17_security_checks.py",
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
    'tools/botapi_healthcheck.sh', 'tools/check_stats_source.py',
    'tools/observability/Dockerfile', 'tools/observability/status.schema.json',
    'docker-compose.yml', 'docker-compose.build.yml', 'nginx.conf',
    "docker-compose.files.yml",
)
DOWNLOADS_RECIPE = (
    'Dockerfile.downloads', '.dockerignore', 'tools/file_access.py', 'tools/file_contract.py',
    'tools/download_server.py', 'tools/test_file_access.py', 'tools/test_download_server.py',
    'tools/check_file_contract.py', 'tools/test_check_file_contract.py',
    'docker-compose.files.yml', 'docker-compose.downloads.yml', 'nginx.conf',
    'examples/files/local_reader.py', 'examples/files/remote_client.py',
    'examples/files/compose.local.yml', 'examples/files/nginx.downloads.conf',
    'tools/fixtures/files/compose.full.yml', 'tools/fixtures/files/Dockerfile.full',
    'tools/fixtures/files/runtime.py', 'tools/fixtures/files/nginx.downloads.conf',
    'tools/fixtures/files/compose.yml', 'tools/fixtures/files/Dockerfile',
    'tools/fixtures/files/mock_botapi.py', 'tools/fixtures/files/synthetic.env',
    'tools/image_inputs.py', 'tools/test_image_inputs.py', '.github/workflows/files.yml',
    '.github/workflows/image.yml',
    'docker-compose.yml', 'docker-compose.build.yml', '.env.example',
    'tools/check_docs.py', 'tools/test_check_docs.py', '_config.yml',
    '.github/workflows/docs.yml',
)
RECIPE = tuple(dict.fromkeys((*RECIPE, *DOWNLOADS_RECIPE,
    'tools/doctor_runtime.py', 'tools/doctor_checks.py', 'tools/test_doctor_config.py',
    'tools/test_doctor_storage.py', 'tools/test_doctor_exposure.py', 'tools/test_doctor_migration.py',
    'tools/test_doctor_runtime.py', 'tools/check_docs.py', 'tools/test_check_docs.py',
    '_config.yml', 'docs/en/configuration.md', 'docs/ru/configuration.md',
    'docs/en/getting-started.md', 'docs/ru/getting-started.md',
    'docs/en/maintenance.md', 'docs/ru/maintenance.md',
    'docs/en/migration.md', 'docs/ru/migration.md', 'examples/files/README.md',
    'README.md', 'CONTRIBUTING.md', 'docs/en/README.md', 'docs/ru/README.md',
)))


def recipe_files():
    names = set(RECIPE)
    names.update(str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'tools/observability').glob('*.py'))
    return {name: (ROOT / name).read_bytes() for name in sorted(names)}


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
        "python_image": "python:3.12-slim@" + digest("python:3.12-slim"),
    }
    inputs['observer_base'] = 'python:3.13.5-alpine3.22@' + digest('python:3.13.5-alpine3.22')
    inputs['downloads_key'] = build_key({'python_image': inputs['python_image']},
                                       {name: (ROOT / name).read_bytes() for name in DOWNLOADS_RECIPE})
    inputs["build_key"] = build_key(inputs, recipe_files())
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
