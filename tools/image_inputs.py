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
)
DOWNLOADS_RECIPE = (
    "Dockerfile.downloads", "docker-compose.downloads.yml",
    "tools/file_access.py", "tools/file_contract.py", "tools/download_server.py",
    "tools/check_file_contract.py", "tools/test_check_file_contract.py",
    "tools/fixtures/files/compose.yml", "tools/fixtures/files/mock_botapi.py",
    "tools/fixtures/files/synthetic.env", "tools/fixtures/files/README.md",
    "tools/fixtures/files/tdlib_permissions.cpp",
    "examples/files/compose.local.yml", "examples/files/local_reader.py",
    "examples/files/downloads.config.example.json", "examples/files/nginx.downloads.conf",
    "examples/files/nginx.downloads-tls.conf", "examples/files/README.md",
)
# Both keys include the qualification contract so reuse is always requalified
# against the exact current sources, not just an image with a familiar tag.
QUALIFICATION_RECIPE = (
    '.github/workflows/file-contract.yml', '.github/workflows/docs.yml',
    'docker-compose.yml', 'docker-compose.build.yml', 'nginx.conf',
    '.env.example', '_config.yml', 'tools/check_docs.py',
    'tools/test_file_access.py', 'tools/test_file_contract.py',
    'tools/test_download_server.py', 'tools/test_file_site_privacy.py',
    'README.md', 'CONTRIBUTING.md',
    'tg_selfhost_botapi_migrator.html', 'migrate_off_to_self.sh',
    'tools/issue10_test_support.py', 'tools/issue10_bash.cjs',
    'tools/issue10_timeout.cjs', 'tools/issue10_ui_harness.cjs',
    'tools/test_issue10_bash.cjs', 'index.md', 'docs/README.md',
    '_layouts/default.html', 'assets/css/docs.css', 'assets/favicon.svg',
)
QUALIFICATION_RECIPE += tuple(str(path.relative_to(ROOT)).replace('\\', '/')
                              for pattern in ('docs/en/*.md', 'docs/ru/*.md', 'tools/test_issue10_*.py')
                              for path in sorted(ROOT.glob(pattern)))
RECIPE = tuple(sorted(set(RECIPE + DOWNLOADS_RECIPE + QUALIFICATION_RECIPE)))
DOWNLOADS_RECIPE = tuple(sorted(set(RECIPE + DOWNLOADS_RECIPE)))


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


def downloads_key(inputs, files):
    return build_key({"recipe": "downloads", **inputs}, files)


def python_image(image="python:3.12-alpine"):
    if "@" in image or not re.fullmatch(r"python:[A-Za-z0-9._-]+", image):
        raise ValueError("expected an official Python image tag")
    return image + "@" + digest(image)


def resolve():
    inputs = {
        "bot_api_revision": revision("tdlib/telegram-bot-api"),
        "alpine_image": "alpine:3.22@" + digest("alpine:3.22"),
        "python_image": python_image(),
    }
    inputs["build_key"] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
    inputs["downloads_key"] = downloads_key(inputs, {name: (ROOT / name).read_bytes() for name in DOWNLOADS_RECIPE})
    return inputs


if __name__ == "__main__":
    for key, value in resolve().items():
        print(f"{key}={value}")
