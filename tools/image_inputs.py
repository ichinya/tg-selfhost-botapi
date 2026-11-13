"""Resolve immutable build inputs and fingerprint the image recipe (stdlib only)."""
import hashlib
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import platform
import shutil
from datetime import date, datetime, timezone
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
# Extended by each owned qualification component as it is introduced.
RECIPE = (
    'Dockerfile', '.dockerignore', 'docker-entrypoint.sh', 'tools/botapi_healthcheck.sh',
    'patches/webhook-user-agent.patch', 'patches/botapi-secrets-redaction.patch',
    'tools/fixtures/issue17_security/botapi_log_driver.cpp',
    'tools/image_inputs.py', 'tools/release_metadata.py', 'tools/apk_policy.json',
    'tools/observability/Dockerfile', 'Dockerfile.downloads',
    'tools/file_access.py', 'tools/file_contract.py', 'tools/download_server.py',
    'examples/files/local_reader.py',
)
DOWNLOADS_RECIPE = ('Dockerfile.downloads', 'tools/file_access.py', 'tools/file_contract.py',
                    'tools/download_server.py', 'examples/files/local_reader.py')
QUALIFICATION_RECIPE = ('tools/check_release.py', 'tools/qualify_release.py',
    'tools/smoke_image.py', 'tools/webhook_probe.py', 'tools/check_apk_refresh.py',
    'tools/release_contract.py', 'tools/release.schema.json',
    'nginx.conf', 'nginx-main.conf', 'docker-compose.yml', 'docker-compose.downloads.yml',
    '.github/workflows/image.yml')



def extract_source_version(source):
    matches = re.findall(r'project\s*\(\s*TelegramBotApi\s+VERSION\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s', source, re.I)
    if len(matches) != 1:
        raise ValueError('Cannot resolve one official source version')
    return matches[0]


def nginx_version(ref):
    result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--cpus', '0.5',
        '--memory', '128m', '--entrypoint', 'nginx', ref, '-v'], capture_output=True, text=True, check=True, timeout=30)
    match = re.fullmatch(r'nginx version: nginx/([0-9]+\.[0-9]+\.[0-9]+)\s*', result.stderr)
    if not match:
        raise ValueError('Cannot verify actual nginx version')
    return match[1]


def command(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def revision(repository):
    value = command("git", "ls-remote", f"https://github.com/{repository}.git", "refs/heads/master").split()[0]
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"Invalid revision from {repository}")
    return value


def checkout_revision():
    """Capture the public wrapper commit during discovery, never during replay."""
    value = command('git', '-c', f'safe.directory={ROOT.as_posix()}', '-C', str(ROOT), 'rev-parse', 'HEAD')
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Invalid wrapper checkout revision')
    return value


def submodules(rev):
    with tempfile.TemporaryDirectory() as tmp:
        command('git', 'clone', '--quiet', '--no-checkout', 'https://github.com/tdlib/telegram-bot-api.git', tmp)
        command('git', '-C', tmp, 'checkout', '--quiet', '--detach', rev)
        if command('git', '-C', tmp, 'rev-parse', 'HEAD') != rev:
            raise ValueError('Source checkout differs from requested revision')
        command('git', '-C', tmp, 'submodule', 'update', '--init', '--recursive')
        status = command('git', '-C', tmp, 'submodule', 'status', '--recursive')
        modules = {}
        for line in status.splitlines():
            match = re.fullmatch(r' ?([0-9a-f]{40}) ([^ ]+)(?: .*)?', line)
            if not match:
                raise ValueError('Invalid or uninitialized recursive submodule')
            modules[match.group(2).removeprefix('telegram-bot-api/')] = match.group(1)
        if 'td' not in modules:
            raise ValueError('Missing td gitlink')
        return modules


def check_host():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise ValueError('Local builds require a linux/amd64 host')
    if not shutil.which('docker'):
        raise ValueError('Docker CLI is required')
    command('docker', 'compose', 'version')
    resolve('locked')


def digest(image):
    value = json.loads(command("docker", "buildx", "imagetools", "inspect", image,
                               "--format", "{{json .Manifest}}"))["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"Invalid digest from {image}")
    return value


def recipe_files():
    names = set(RECIPE)
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools/observability').glob('*.py'))
    names.update(('tools/observability/status.schema.json',))
    if (ROOT / 'tools/webhook_sender').exists():
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools/webhook_sender').glob('*') if p.is_file())
    return {name: (ROOT / name).read_bytes() for name in sorted(names)}


def recipe_digests(files):
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


def qualification_files():
    names = set(QUALIFICATION_RECIPE)
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools').glob('test_issue12_*.py'))
    names.update(('tools/test_image_inputs.py', 'tools/test_entrypoint.py', 'tools/test_botapi_healthcheck.py',
                  'tools/check_nonroot.py', 'tools/check_migration_volumes.py',
                  'tools/issue17_security_gate.py', 'tools/issue17_security_checks.py',
                  'tools/check_observability.py', 'tools/check_file_contract.py', 'tools/check_gateway_uploads.py'))
    return {name: (ROOT / name).read_bytes() for name in sorted(names) if (ROOT / name).exists()}


def require_committed_recipe():
    try:
        subprocess.run(['git', '-c', f'safe.directory={ROOT.as_posix()}', '-C', str(ROOT), 'ls-files', '--error-unmatch', '--', *RECIPE],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        subprocess.run(['git', '-c', f'safe.directory={ROOT.as_posix()}', '-C', str(ROOT), 'diff', '--quiet', 'HEAD', '--', *RECIPE],
                       check=True, timeout=120)
    except subprocess.CalledProcessError as exc:
        raise ValueError('Commit recipe changes before capturing a new candidate') from exc


def build_key(inputs, files):
    # File names and length boundaries prevent ambiguous concatenations.
    result = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode())
    for name, content in sorted(files.items()):
        result.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return result.hexdigest()[:32]


def read_policy():
    value = json.loads((ROOT / 'tools/apk_policy.json').read_text(encoding='utf8'))
    return validate_policy(value)


def validate_policy(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'policy_version', 'stable_branch',
            'refresh_window', 'generation', 'packages'} or type(value['schema']) is not int or value['schema'] != 1
            or type(value['policy_version']) is not int or value['policy_version'] != 3
            or value['stable_branch'] != '3.22' or value['refresh_window'] != 'utc-day'
            or type(value['generation']) is not int or value['generation'] < 0
            or value['packages'] != {'build': ['alpine-sdk', 'linux-headers', 'git', 'zlib-dev', 'openssl-dev', 'gperf', 'cmake', 'python3'],
                                     'runtime': ['openssl', 'libstdc++', 'su-exec', 'curl', 'jq']}):
        raise ValueError('Invalid apk policy')
    return value


def refresh_id(version, window, generation):
    if type(version) is not int or version < 1 or type(generation) is not int or generation < 0:
        raise ValueError('Invalid apk refresh identity')
    if not isinstance(window, str) or date.fromisoformat(window).isoformat() != window:
        raise ValueError('Invalid UTC refresh day')
    return f'apk-v{version}-{window}-g{generation}'


def validate_lock(lock):
    """Reject malformed lock data before it can be used as a build input."""
    if not isinstance(lock, dict) or type(lock.get("schema")) is not int or lock.get("schema") != 1:
        raise ValueError("Unsupported release lock schema")
    inputs = lock.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Missing locked inputs")
    public = {"bot_api_revision", "wrapper_revision", "alpine_image", "platform", "bot_api_version",
              "apk_policy_version", "apk_refresh_window", "apk_refresh_generation", "apk_refresh_id", "submodules", "observer_base", "python_image"}
    derived = {"apk_policy", "build_key", "submodules_arg", "nginx_image", "nginx_version", "nginx_platform_digest", "downloads_key", "qualification_key"}
    if not public <= set(inputs) or set(inputs) - public - derived:
        raise ValueError("Unexpected build input fields")
    if not isinstance(inputs.get("bot_api_revision"), str) or not re.fullmatch(r"[0-9a-f]{40}", inputs["bot_api_revision"]):
        raise ValueError("Invalid locked server revision")
    if not isinstance(inputs.get('wrapper_revision'), str) or not re.fullmatch(r'[0-9a-f]{40}', inputs['wrapper_revision']):
        raise ValueError('Invalid locked wrapper revision')
    if not isinstance(inputs.get("alpine_image"), str) or not re.fullmatch(r"alpine:3\.22@sha256:[0-9a-f]{64}", inputs["alpine_image"]):
        raise ValueError("Invalid locked Alpine image")
    if inputs.get("platform") != "linux/amd64":
        raise ValueError("Locked builds support only linux/amd64")
    for key, pattern in (("bot_api_version", r"[0-9]+\.[0-9]+(?:\.[0-9]+)?"),):
        if not isinstance(inputs.get(key), str) or not re.fullmatch(pattern, inputs[key]):
            raise ValueError(f"Invalid {key}")
    if inputs['apk_refresh_id'] != refresh_id(inputs['apk_policy_version'], inputs['apk_refresh_window'], inputs['apk_refresh_generation']):
        raise ValueError('Noncanonical apk refresh identity')
    modules = inputs.get('submodules')
    if not isinstance(modules, dict) or 'td' not in modules or any(
            not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', k)
            or '..' in k.split('/') or not isinstance(v, str)
            or not re.fullmatch(r'[0-9a-f]{40}', v) for k, v in modules.items()):
        raise ValueError('Invalid locked submodules')
    for name in ('observer_base', 'python_image'):
        if not isinstance(inputs.get(name), str) or not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', inputs[name]):
            raise ValueError('Invalid locked base: ' + name)
    if "selected_release" not in lock:
        raise ValueError("Missing selected release")
    if lock["selected_release"] is not None:
        raise ValueError("Selection belongs in image-release.lock.json")
    return inputs.copy()


def resolve(mode="locked", inputs_file=None, observed_at=None):
    if mode == "locked":
        lock = json.loads(Path(inputs_file or ROOT / "image-inputs.lock.json").read_text(encoding="utf-8"))
        from release_contract import validate_inputs
        inputs = validate_inputs(lock)
        files = recipe_files()
        inputs['nginx_image'] = lock['discovery']['nginx_candidate_image']
        inputs['nginx_platform_digest'] = lock['discovery']['nginx_amd64_digest']
        inputs['nginx_version'] = lock['discovery']['nginx_version']
    elif mode == "discovery":
        require_committed_recipe()
        files = recipe_files()
        observed_at = observed_at or datetime.now(timezone.utc)
        policy = read_policy()
        inputs = {
            "bot_api_revision": json.loads((ROOT / "image-inputs.lock.json").read_text())["inputs"]["bot_api_revision"],
            "alpine_image": "alpine:3.22@" + digest("alpine:3.22"),
            "platform": "linux/amd64",
        }
        inputs['observer_base'] = inputs['alpine_image']
        inputs['python_image'] = 'python:3.12-slim@' + digest('python:3.12-slim')
        inputs['submodules'] = submodules(inputs['bot_api_revision'])
        url = f"https://raw.githubusercontent.com/tdlib/telegram-bot-api/{inputs['bot_api_revision']}/CMakeLists.txt"
        with urlopen(url, timeout=30) as response:
            source = response.read(1024 * 1024).decode("utf-8")
        inputs.update(bot_api_version=extract_source_version(source),
                      wrapper_revision=checkout_revision(),
                      apk_policy_version=policy['policy_version'],
                      apk_refresh_window=observed_at.date().isoformat(),
                      apk_refresh_generation=policy['generation'])
        inputs['apk_refresh_id'] = refresh_id(inputs['apk_policy_version'], inputs['apk_refresh_window'], inputs['apk_refresh_generation'])
        with urlopen('https://alpinelinux.org/releases.json', timeout=30) as response:
            branches = json.load(response)['release_branches']
        if not any(b['rel_branch'] == 'v' + policy['stable_branch'] and b['eol_date'] >= observed_at.date().isoformat() for b in branches):
            raise ValueError('Configured Alpine branch is no longer supported')
        nginx_index, nginx_child = registry_candidate('nginx:alpine')
        inputs['nginx_image'] = 'nginx:alpine@' + nginx_index
        inputs['nginx_platform_digest'] = nginx_child
        subprocess.run(['docker', 'pull', inputs['nginx_image']], check=True, timeout=180)
        inputs['nginx_version'] = nginx_version(inputs['nginx_image'])
    else:
        raise ValueError("Unknown resolution mode")
    inputs['apk_policy'] = read_policy()
    if (inputs['apk_refresh_generation'] != inputs['apk_policy']['generation']
            or inputs['apk_policy_version'] != inputs['apk_policy']['policy_version']):
        raise ValueError('Saved generation differs from policy; save a new discovery candidate')
    # Runtime refs, observation dates, and qualification outputs never enter this key.
    identity = {k: v for k, v in inputs.items() if k not in ('nginx_image', 'nginx_version', 'nginx_platform_digest')}
    inputs["build_key"] = build_key(identity, files)
    inputs['downloads_key'] = build_key({'python_image': inputs['python_image']},
                                       {p: (ROOT / p).read_bytes() for p in DOWNLOADS_RECIPE})
    inputs['qualification_key'] = build_key({'build_key': inputs['build_key'], 'nginx_image': inputs['nginx_image']},
        qualification_files())
    inputs['submodules_arg'] = ','.join(f'{path}={sha}' for path, sha in sorted(inputs['submodules'].items()))
    return inputs


def build_environment(inputs):
    """The sole public build projection, shared by Compose and CI."""
    return {'BOT_API_REVISION': inputs['bot_api_revision'],
            'BOT_API_VERSION': inputs['bot_api_version'], 'ALPINE_IMAGE': inputs['alpine_image'],
            'APK_REFRESH_ID': inputs['apk_refresh_id'],
            'SUBMODULES': inputs['submodules_arg'], 'BUILD_FINGERPRINT': inputs['build_key'],
            'TDLIB_REVISION': inputs['submodules']['td'],
            'WRAPPER_REVISION': inputs['wrapper_revision'], 'BUILD_JOBS': '1',
            'OBSERVER_BASE': inputs['observer_base'], 'PYTHON_IMAGE': inputs['python_image']}


def validate_resolved(inputs):
    """Validate an already resolved run snapshot without discovery or networking."""
    validate_lock({'schema': 1, 'inputs': inputs, 'selected_release': None})
    if inputs.get('apk_policy') != read_policy():
        raise ValueError('Resolved dependency policy differs from repository policy')
    derived = {'build_key', 'submodules_arg', 'downloads_key', 'qualification_key',
               'nginx_image', 'nginx_version', 'nginx_platform_digest'}
    expected = build_key({k: v for k, v in inputs.items() if k not in derived}, recipe_files())
    if inputs.get('build_key') != expected:
        raise ValueError('Resolved inputs differ from build recipe')
    if inputs.get('submodules_arg') != ','.join(f'{p}={s}' for p, s in sorted(inputs['submodules'].items())):
        raise ValueError('Resolved gitlink projection differs')
    if inputs.get('qualification_key') != build_key({'build_key': expected, 'nginx_image': inputs['nginx_image']}, qualification_files()):
        raise ValueError('Resolved qualification recipe differs')
    downloads = build_key({'python_image': inputs['python_image']}, {p: (ROOT / p).read_bytes() for p in DOWNLOADS_RECIPE})
    if inputs.get('downloads_key') != downloads:
        raise ValueError('Resolved downloads recipe differs')
    return inputs


def public_environment(inputs):
    """Local Compose projection, including required base-file interpolation inputs."""
    return {**build_environment(inputs), 'BOTAPI_IMAGE': 'tg-selfhost-botapi:local',
            'GATEWAY_IMAGE': inputs['nginx_image'], 'OBSERVER_IMAGE': 'tg-selfhost-botapi-observer:local',
            'DOWNLOADS_IMAGE': 'tg-selfhost-botapi-downloads:local', 'DOWNLOADS_FINGERPRINT': inputs['downloads_key']}


def check_build_environment(path, inputs):
    lines = Path(path).read_text(encoding='utf8').splitlines()
    actual = {}
    for line in lines:
        if '=' not in line:
            raise ValueError('Malformed public build projection')
        name, value = line.split('=', 1)
        if name in actual:
            raise ValueError('Duplicate public build projection field')
        actual[name] = value
    if actual != public_environment(inputs):
        raise ValueError('Public build projection differs from saved inputs')


def registry_candidate(tag):
    """Resolve both index and the one supported child; errors never mean absence."""
    index_digest = digest(tag)
    document = json.loads(command('docker', 'buildx', 'imagetools', 'inspect',
                                  tag + '@' + index_digest, '--raw'))
    if document.get('mediaType') not in ('application/vnd.oci.image.index.v1+json',
                                        'application/vnd.docker.distribution.manifest.list.v2+json'):
        raise ValueError('Expected a platform index')
    children = [m['digest'] for m in document.get('manifests', [])
                if m.get('platform', {}).get('os') == 'linux'
                and m.get('platform', {}).get('architecture') == 'amd64']
    if len(children) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', children[0]):
        raise ValueError('Registry candidate must expose one linux/amd64 manifest')
    return index_digest, children[0]


def save_discovery(path):
    """Write a new candidate envelope, never deployment selection or defaults."""
    observed_at = datetime.now(timezone.utc)
    candidate = resolve('discovery', observed_at=observed_at)
    alpine_tag = candidate['alpine_image'].split('@')[0]
    alpine_index, alpine_child = registry_candidate(alpine_tag)
    if not candidate['alpine_image'].endswith('@' + alpine_index):
        raise ValueError('Base changed during discovery; retry explicitly')
    nginx_tag, nginx_index = candidate['nginx_image'].split('@')
    nginx_child = candidate['nginx_platform_digest']
    record = {'schema': 1, 'inputs': {k: v for k, v in candidate.items()
              if k not in ('build_key', 'submodules_arg', 'apk_policy', 'nginx_image', 'nginx_version', 'nginx_platform_digest', 'downloads_key', 'qualification_key')},
              'selected_release': None, 'apk_policy': candidate['apk_policy'],
              'recipe_sha256': recipe_digests(recipe_files()),
              'discovery': {'source_repository': 'https://github.com/tdlib/telegram-bot-api',
              'observed_date': observed_at.date().isoformat(),
              'alpine_index_digest': alpine_index, 'alpine_amd64_digest': alpine_child,
              'nginx_candidate_image': nginx_tag + '@' + nginx_index,
              'nginx_version': candidate['nginx_version'], 'nginx_amd64_digest': nginx_child,
              'qualification': 'NOTRUN'}}
    from release_contract import validate_inputs
    validate_inputs(record)
    Path(path).write_text(json.dumps(record, indent=2) + '\n', encoding='utf8', newline='\n')
    return record


def save_wrapper_candidate(source, destination):
    """Explicit new recipe candidate; retain saved upstream/base/refresh inputs."""
    from release_contract import validate_inputs
    record = json.loads(Path(source).read_text(encoding='utf8'))
    validate_inputs(record)
    require_committed_recipe()
    record['inputs']['wrapper_revision'] = checkout_revision()
    record['recipe_sha256'] = recipe_digests(recipe_files())
    Path(destination).write_text(json.dumps(record, indent=2) + '\n', encoding='utf8', newline='\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("locked", "discovery"), default="locked")
    parser.add_argument('--check-host', action='store_true')
    parser.add_argument('--extract-version', type=Path)
    parser.add_argument('--json-file')
    parser.add_argument('--build-env', help='Write public saved build arguments as an env file')
    parser.add_argument('--save-discovery', type=Path, help='Save a new unqualified candidate envelope')
    parser.add_argument('--inputs-file', type=Path, help='Replay this saved candidate instead of the repository default')
    parser.add_argument('--check-build-env', type=Path, help='Reject a stale or changed public projection')
    parser.add_argument('--capture-wrapper', type=Path, help='Explicitly save a new candidate for the committed wrapper HEAD')
    args = parser.parse_args()
    if args.extract_version:
        print(extract_source_version(args.extract_version.read_text(encoding='utf8')))
        raise SystemExit(0)
    if args.check_host:
        check_host()
    if args.save_discovery:
        save_discovery(args.save_discovery)
        raise SystemExit(0)
    if args.capture_wrapper:
        save_wrapper_candidate(args.inputs_file or ROOT / 'image-inputs.lock.json', args.capture_wrapper)
        raise SystemExit(0)
    inputs = resolve(args.mode, args.inputs_file)
    if args.check_build_env:
        check_build_environment(args.check_build_env, inputs)
    if args.json_file:
        Path(args.json_file).write_text(json.dumps(inputs, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    if args.build_env:
        values = public_environment(inputs)
        Path(args.build_env).touch(mode=0o600, exist_ok=True)
        Path(args.build_env).chmod(0o600)
        Path(args.build_env).write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8', newline='\n')
    for key, value in inputs.items():
        print(f"{key}={json.dumps(value, sort_keys=True, separators=(',', ':')) if isinstance(value, dict) else value}")
