"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
from datetime import datetime, timezone
import os
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RECIPE = (
    "docker-compose.downloads.build.yml", "image-inputs.lock.json", "tools/apk_policy.json", "nginx-main.conf", "docker-compose.secrets.yml", "Dockerfile", ".dockerignore", "docker-entrypoint.sh", "patches/webhook-user-agent.patch",
    "tools/image_inputs.py", "tools/test_image_inputs.py", "tools/test_entrypoint.py",
    "tools/test_webhook_user_agent.py",
    "docker-compose.yml", "docker-compose.build.yml", "docker-compose.nonroot.yml", "docker-compose.files.yml",
    "tools/check_nonroot.py", "tools/check_nonroot_compose.py",
    "tools/test_check_nonroot.py", "tools/test_nonroot_compose.py",
    "tools/fixtures/nonroot/compose.yml", "tools/fixtures/nonroot/media-probe.sh",
    "tools/fixtures/nonroot/source-semantics.sh",
    "tools/migration_probe.py", "tools/migration_contract.py",
    "tools/check_migration_volumes.py", "tools/fixtures/migration/fake-bot-api.sh",
    "tools/fixtures/migration/docker-compose.volumes.yml",
    "patches/botapi-secrets-redaction.patch",
    "tools/fixtures/issue17_security/botapi_log_driver.cpp",
    "tools/fixtures/issue17_security/cases.json",
    "tools/issue17_security_gate.py", "tools/issue17_security_checks.py",
    ".github/workflows/image.yml",
    'tools/botapi_healthcheck.sh', 'tools/check_stats_source.py',
    'tools/observability/Dockerfile', 'tools/observability/status.schema.json',
    'docker-compose.yml', 'docker-compose.build.yml', 'nginx.conf',
    'docker-compose.observability.yml', 'docker-compose.observability.build.yml', 'nginx.observability.conf',
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
    names.update('tools/webhook_sender/'+name for name in ('CMakeLists.txt','receiver.py','webhook_sender_test.cpp'))
    names.update(('tools/multiarch_publish.py',))
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


def resolve(clock=None, policy=None, platform='linux/amd64'):
    # Reviewed source/base snapshot: discovery does not silently promote master.
    policy=validate_policy(policy or json.loads((ROOT/'tools/apk_policy.json').read_text(encoding='utf-8')))
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    if now.tzinfo is None or platform not in ('linux/amd64','linux/arm64'):
        raise ValueError('aware UTC clock and explicit platform required')
    saved=json.loads((ROOT/'image-inputs.lock.json').read_text(encoding='utf-8'))
    expected={'bot_api_revision','submodules','bot_api_version','alpine_image','python_image','observer_base'}
    if (set(saved)!={'schema','inputs','selected_release'} or type(saved['schema']) is not int or saved['schema']!=1
            or not isinstance(saved['inputs'],dict) or set(saved['inputs'])!=expected or saved['selected_release'] is not None):
        raise ValueError('reviewed candidate snapshot required')
    inputs={k:saved['inputs'][k] for k in ('bot_api_revision','submodules','bot_api_version','alpine_image','python_image','observer_base')}
    if not isinstance(inputs['submodules'],dict) or set(inputs['submodules']) != {'td'} or not re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?',inputs['bot_api_version']):
        raise ValueError('reviewed source version/submodule map required')
    if not re.fullmatch('[0-9a-f]{40}',inputs['bot_api_revision']) or not re.fullmatch('[0-9a-f]{40}',inputs['submodules']['td']):
        raise ValueError('pinned source/submodule required')
    for name in ('alpine_image','python_image','observer_base'):
        if not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}',inputs[name]):
            raise ValueError('immutable base required')
    wrapper=os.environ.get('GITHUB_SHA') or command('git','rev-parse','HEAD')
    if not re.fullmatch('[0-9a-f]{40}',wrapper):
        raise ValueError('committed wrapper identity required')
    window=now.astimezone(timezone.utc).date().isoformat()
    inputs.update(platform=platform,wrapper_revision=wrapper,apk_policy_version=policy['policy_version'],
                  apk_refresh_window=window,apk_refresh_generation=policy['generation'],
                  apk_refresh_id=f"v{policy['policy_version']}-{window}-g{policy['generation']}")
    inputs['downloads_key']=build_key({'python_image':inputs['python_image']},
                                    {name:(ROOT/name).read_bytes() for name in DOWNLOADS_RECIPE})
    files=recipe_files()
    inputs['recipe_sha256']=hashlib.sha256(b''.join(name.encode()+b'\0'+hashlib.sha256(raw).digest() for name,raw in sorted(files.items()))).hexdigest()
    inputs['build_key']=build_key(inputs,files)
    return inputs


def build_environment(inputs):
    return {'BOT_API_REVISION':inputs['bot_api_revision'],'ALPINE_IMAGE':inputs['alpine_image'],
            'PYTHON_IMAGE':inputs['python_image'],'OBSERVER_BASE':inputs['observer_base'],
            'BUILD_FINGERPRINT':inputs['build_key'],'DOWNLOADS_FINGERPRINT':inputs['downloads_key'],
            'APK_REFRESH_ID':inputs['apk_refresh_id'],'WRAPPER_REVISION':inputs['wrapper_revision'],
            'BOT_API_VERSION':inputs['bot_api_version']}

if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--build-env',type=Path)
    args=parser.parse_args()
    if args.build_env and Path(command('git','rev-parse','--show-toplevel')).resolve()!=ROOT:
        raise ValueError('build projection requires its own committed checkout')
    inputs=resolve(platform=os.environ.get('BUILD_PLATFORM','linux/amd64'))
    if args.build_env:
        args.build_env.write_text(''.join(f'{name}={value}\n' for name,value in build_environment(inputs).items()),encoding='utf-8',newline='\n')
    for key,value in inputs.items():
        print(f"{key}={json.dumps(value,sort_keys=True,separators=(',',':')) if isinstance(value,dict) else value}")
