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
    ".github/workflows/image.yml",
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
        "python_image": "python:3.12-slim@" + digest("python:3.12-slim"),
    }
    inputs['downloads_key'] = build_key({'python_image': inputs['python_image']},
                                       {name: (ROOT / name).read_bytes() for name in DOWNLOADS_RECIPE})
    inputs["build_key"] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
    return inputs


if __name__ == "__main__":
    for key, value in resolve().items():
        print(f"{key}={value}")
