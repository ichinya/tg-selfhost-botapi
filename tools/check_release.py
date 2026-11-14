"""Verify immutable image content and receipts; never authorize live gates."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from image_inputs import recipe_files, RECIPE, ROOT, build_key, resolve, validate_lock
from release_contract import GATES, QUALIFICATION_VERSION, validate_receipt, validate_selected


def validate_compose_config(config, inputs, *, local=False, selected=None):
    """Check the effective merged model after process/.env interpolation, without exposing it."""
    from image_inputs import build_environment
    services = config.get('services', {}) if isinstance(config, dict) else {}
    if not all(isinstance(services.get(name), dict) for name in ('botapi', 'gateway')):
        raise ValueError('Effective Compose services are incomplete')
    api, gateway = services['botapi'], services['gateway']
    if local:
        expected_api, expected_gateway = 'tg-selfhost-botapi:local', inputs['nginx_image']
        expected_args = {k: v for k, v in build_environment(inputs).items() if k not in ('OBSERVER_BASE', 'PYTHON_IMAGE')}
        if api.get('build', {}).get('args') != expected_args:
            raise ValueError('Effective Compose build arguments differ from saved inputs')
    else:
        if not selected:
            raise ValueError('Registry deployment requires a qualified selected release')
        expected_api, expected_gateway = selected['botapi_image'], selected['nginx_image']
        if 'build' in api:
            raise ValueError('Registry deployment must use its qualified artifact')
    if api.get('image') != expected_api or gateway.get('image') != expected_gateway:
        raise ValueError('Effective Compose image references differ from the release')
    for image in ([expected_gateway] if local else [expected_api, expected_gateway]):
        if not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}', image):
            raise ValueError('Registry image references must be immutable')
    if not local:
        for name in ('observer', 'downloads'):
            if name in services:
                expected = selected.get(name + '_image')
                service = services[name]
                if (not isinstance(expected, str)
                        or not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}', expected)
                        or not isinstance(service, dict) or service.get('image') != expected):
                    raise ValueError('Effective Compose image references differ from the release')
    environment = api.get('environment', {})
    if not isinstance(environment, dict):
        raise ValueError('Effective Compose credentials mapping is missing')
    if str(environment.get('TELEGRAM_HTTP_PORT', '8081')) != '8081':
        raise ValueError('Effective Compose TELEGRAM_HTTP_PORT must be 8081')
    for name in ('TELEGRAM_API_ID', 'TELEGRAM_API_HASH'):
        if bool(environment.get(name)) == bool(environment.get(name + '_FILE')):
            raise ValueError('Effective Compose requires exactly one credential source: ' + name)
    if api.get('platform', 'linux/amd64') != inputs['platform']:
        raise ValueError('Effective Compose platform differs from saved inputs')
    return True


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_gateway(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('Gateway smoke accepts only a credential-free root URL')

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(url, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        if response.code != 404 or response.headers.get_content_type() != 'application/json':
            raise ValueError('Gateway root HTTP contract failed')
        body = response.read(16385)
    if len(body) > 16384:
        raise ValueError('Oversized gateway response')
    value = json.loads(body)
    if (not isinstance(value, dict) or value.get('ok') is not False
            or type(value.get('error_code')) not in (int, float) or value['error_code'] != 404):
        raise ValueError('Gateway root JSON contract failed')


def registry_lookup(ref):
    result = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', ref,
                             '--format', '{{json .Manifest}}'], capture_output=True, text=True, timeout=120)
    if result.returncode:
        error = result.stderr.lower()
        if ('manifest unknown' in error or 'manifest_unknown' in error) and not any(
                word in error for word in ('denied', 'unauthorized', 'forbidden', 'timeout',
                                           'deadline', 'connection', '429', 'rate limit', 'eof')):
            return None
        raise ValueError('Registry lookup failed; candidate/release must not be overwritten')
    digest = json.loads(result.stdout).get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Registry returned an invalid digest')
    return digest


def command(*args):
    if args[:2] == ('docker', 'run'):
        args = args[:2] + ('--cpus', '1', '--memory', '256m') + args[2:]
    return subprocess.check_output(args, timeout=120)


def image_evidence(ref, inputs, require_registry=True):
    if require_registry and not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', ref):
        raise ValueError('Image verification requires a registry digest')
    info = json.loads(command('docker', 'image', 'inspect', ref))[0]
    if (info.get('Os') != 'linux' or info.get('Architecture') != 'amd64'
            or (require_registry and not any(value.endswith('@' + ref.rsplit('@', 1)[1]) for value in info.get('RepoDigests', [])))):
        raise ValueError('Image platform/digest differs from requested artifact')
    labels = info['Config'].get('Labels') or {}
    if info['Config'].get('Entrypoint') != ['/docker-entrypoint.sh']:
        raise ValueError('Image entrypoint differs from runtime contract')
    for name, expected in {'org.opencontainers.image.revision': inputs['bot_api_revision'],
                           'io.tg-selfhost.bot-api-revision': inputs['bot_api_revision'],
                           'org.opencontainers.image.version': inputs['bot_api_version'],
                           'io.tg-selfhost.tdlib-revision': inputs['submodules']['td'],
                           'io.tg-selfhost.base': inputs['alpine_image'],
                           'io.tg-selfhost.platform': inputs['platform'],
                           'io.tg-selfhost.verification-contract': '1',
                           'io.tg-selfhost.build-key': inputs['build_key']}.items():
        if labels.get(name) != expected:
            raise ValueError('Image labels differ from saved inputs: ' + name)
    wrapper = labels.get('io.tg-selfhost.wrapper-revision', '')
    if not re.fullmatch(r'[0-9a-f]{40}', wrapper):
        raise ValueError('Image must record its actual wrapper revision')
    if wrapper != inputs['wrapper_revision']:
        raise ValueError('Image wrapper revision differs from saved inputs')
    registry_identity = {}
    if require_registry:
        index = json.loads(command('docker', 'buildx', 'imagetools', 'inspect', ref, '--raw'))
        child = ref.rsplit('@', 1)[1]
        if 'manifests' in index:
            if any(item.get('platform', {}).get('os') == 'linux'
                   and item.get('platform', {}).get('architecture') != 'amd64' for item in index['manifests']):
                raise ValueError('Unqualified platform in registry index; multiarch requires #22')
            children = [item['digest'] for item in index['manifests']
                        if item.get('platform', {}).get('os') == 'linux'
                        and item.get('platform', {}).get('architecture') == 'amd64']
            if len(children) != 1:
                raise ValueError('Registry index must have exactly one amd64 child')
            child = children[0]
            index = json.loads(command('docker', 'buildx', 'imagetools', 'inspect',
                                       ref.split('@')[0] + '@' + child, '--raw'))
        if index.get('config', {}).get('digest') != info['Id']:
            raise ValueError('Registry child/config differs from inspected image')
        registry_identity = {'index_digest': ref.rsplit('@', 1)[1], 'platform_digest': child}
    version = command('docker', 'run', '--rm', '--network', 'none', ref, '--version').decode()
    if inputs['bot_api_version'] not in version.split():
        raise ValueError('Binary version differs from source version')

    def read(path):
        return command('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', ref, path)

    binary = read('/usr/local/bin/telegram-bot-api')
    if binary[:5] != b'\x7fELF\x02' or binary[5:6] != b'\x01' or binary[18:20] != b'\x3e\x00':
        raise ValueError('Binary is not an amd64 little-endian ELF64')
    if b'WebhookDelivery/1.0' not in binary:
        raise ValueError('Missing patched webhook marker (static gate only)')
    entrypoint = read('/docker-entrypoint.sh')
    probe = read('/usr/local/bin/botapi-healthcheck')
    if sha(entrypoint) != sha((ROOT / 'docker-entrypoint.sh').read_bytes()) or sha(probe) != sha((ROOT / 'tools/botapi_healthcheck.sh').read_bytes()):
        raise ValueError('Image recipe files differ from current recipe')
    command('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'sh', ref,
            '-ec', 'sh -n /docker-entrypoint.sh; sh -n /usr/local/bin/botapi-healthcheck')
    inventory = {}
    for name in ('build-packages.txt', 'build-repositories.txt', 'build-apk.txt', 'compiler.txt', 'runtime-apk.txt', 'runtime-packages.txt',
                 'runtime-repositories.txt', 'linkage.txt', 'files.sha256', 'patch.sha256', 'source.txt',
                 'link-commands.txt', 'static-archives.sha256', 'binary.sha256', 'adapter.sha256', 'production-objects.sha256'):
        stage = 'build' if name.startswith('build-') or name in ('compiler.txt', 'patch.sha256', 'source.txt', 'link-commands.txt', 'static-archives.sha256', 'binary.sha256', 'adapter.sha256', 'production-objects.sha256') else 'runtime'
        data = read('/usr/share/tg-selfhost-botapi/' + stage + '/' + name)
        if not data.strip() or (name == 'linkage.txt' and b'not found' in data):
            raise ValueError('Missing or invalid image inventory/linkage')
        inventory[name] = sha(data)
        if name.endswith('-apk.txt') and data.decode().splitlines()[-1] != inputs['apk_refresh_id']:
            raise ValueError('Actual dependency refresh differs from saved inputs')
        if name.endswith('-repositories.txt'):
            repositories = [line.strip() for line in data.decode().splitlines()
                            if line.strip() and not line.lstrip().startswith('#')]
            if not repositories or any(not re.fullmatch(r'https?://[^\s]+/v3\.22/(main|community)', line)
                                       for line in repositories):
                raise ValueError('Dependency repositories leave the selected stable branch')
        if name == 'runtime-packages.txt':
            installed = command('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'sh',
                                ref, '-ec', 'apk info -vv | sort')
            if installed != data:
                raise ValueError('Actual runtime packages differ from installed inventory')
        if name == 'patch.sha256' and data.decode().split()[0] != sha((ROOT / 'patches/webhook-user-agent.patch').read_bytes()):
            raise ValueError('Image patch evidence differs from recipe')
        if name == 'source.txt':
            lines = data.decode().splitlines()
            if (not lines or lines[0] != inputs['bot_api_revision']
                    or lines[-1] != inputs['bot_api_version']):
                raise ValueError('Actual source evidence differs from saved inputs')
            actual = {}
            for line in lines[1:-1]:
                match = re.fullmatch(r' ([0-9a-f]{40}) ([^ ]+)(?: .*)?', line)
                if not match:
                    raise ValueError('Invalid actual recursive gitlinks')
                actual[match[2].removeprefix('telegram-bot-api/')] = match[1]
            if actual != inputs['submodules']:
                raise ValueError('Actual gitlinks differ from saved inputs')
        if name == 'binary.sha256' and data.decode().split()[0] != sha(binary):
            raise ValueError('Build binary hash differs from runtime')
        if name == 'adapter.sha256':
            expected = {p: sha((ROOT / p).read_bytes()) for p in (
                'tools/webhook_sender/CMakeLists.txt', 'tools/webhook_sender/webhook_sender_test.cpp')}
            actual_hashes = {}
            for line in data.decode().splitlines():
                checksum, path = line.split()
                actual_hashes['tools/' + path] = checksum
            if actual_hashes != expected:
                raise ValueError('Adapter source evidence differs from recipe')
    from release_metadata import parse_installed, validate_packages
    for stage in ('build', 'runtime'):
        base_database = read('/usr/share/tg-selfhost-botapi/' + stage + '/base-installed')
        if not base_database.strip():
            raise ValueError('Missing base package inventory')
        inventory[stage + '/base-installed'] = sha(base_database)
        database = read('/usr/share/tg-selfhost-botapi/' + stage + '/installed')
        validate_packages(parse_installed(database.decode()), set(inputs['apk_policy']['packages'][stage]), 'x86_64')
        inventory[stage + '/installed'] = sha(database)
        if stage == 'runtime' and database != read('/lib/apk/db/installed'):
            raise ValueError('Actual runtime installed database differs from evidence')
    command('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'sh', ref,
            '-ec', 'sha256sum -c /usr/share/tg-selfhost-botapi/runtime/files.sha256 >/dev/null')
    return {'config_id': info['Id'], 'binary_sha256': sha(binary), 'entrypoint_sha256': sha(entrypoint),
            'inventories_sha256': inventory, 'wrapper_revision': wrapper, **registry_identity}


def verify_reuse(ref, inputs, receipt_bytes):
    receipt = validate_receipt(json.loads(receipt_bytes), inputs, approved=True)
    if not ref.endswith('@' + receipt['index_digest']):
        raise ValueError('Receipt refers to a different registry digest')
    actual = image_evidence(ref, inputs)
    for name, value in actual.items():
        if receipt[name] != value:
            raise ValueError('Reused image content differs from receipt: ' + name)
    recipe = {p: sha(raw) for p, raw in recipe_files().items()}
    if receipt['recipe_sha256'] != recipe:
        raise ValueError('Receipt qualification recipe differs')
    from qualify_release import gateway_evidence
    if gateway_evidence(inputs) != receipt['gateway']:
        raise ValueError('Reused gateway differs from qualified receipt')
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lookup', help='Resolve a candidate build tag; errors fail closed')
    parser.add_argument('--image', help='Pulled image by registry digest')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--gateway', help='Token-free smoke of a gateway root URL')
    parser.add_argument('--inputs', type=Path, help='Resolved saved CI inputs; no re-resolution')
    parser.add_argument('--local-candidate', action='store_true', help='Local static verification only; no registry/approval claim')
    parser.add_argument('--compose-config', type=Path, help='Effective Compose JSON, or - for private stdin')
    args = parser.parse_args()
    if args.gateway:
        check_gateway(args.gateway)
        print('Gateway root PASS; authorization/delivery NOTRUN')
        return
    if args.lookup:
        print(registry_lookup(args.lookup) or 'NOT_FOUND')
        return
    if args.inputs:
        inputs = json.loads(args.inputs.read_text(encoding='utf-8'))
        validate_lock({'schema': 1, 'inputs': inputs, 'selected_release': None})
        identity = {k: v for k, v in inputs.items() if k not in ('build_key', 'submodules_arg', 'downloads_key', 'qualification_key', 'nginx_image', 'nginx_version', 'nginx_platform_digest')}
        if inputs.get('build_key') != build_key(identity, recipe_files()):
            raise ValueError('Saved CI inputs/recipe key mismatch')
    else:
        inputs = resolve()
    if args.compose_config:
        selected = None
        if not args.local_candidate:
            if not args.selection or not args.receipt:
                raise ValueError('Registry Compose verification requires selection and receipt')
            selected = validate_selected(json.loads(args.selection.read_text(encoding='utf8')), inputs, args.receipt.read_bytes())
        raw = sys.stdin.read(1024 * 1024 + 1) if str(args.compose_config) == '-' else args.compose_config.read_text(encoding='utf8')
        if len(raw) > 1024 * 1024:
            raise ValueError('Effective Compose model exceeds verification limit')
        validate_compose_config(json.loads(raw), inputs, local=args.local_candidate, selected=selected)
        print('Effective Compose inputs match; secret values were not reported')
    elif args.selection:
        validate_selected(json.loads(args.selection.read_text(encoding='utf-8')), inputs,
                          args.receipt.read_bytes() if args.receipt else None)
        print('Selection validated; structural validation does not authenticate evidence')
    elif args.image and args.receipt:
        verify_reuse(args.image, inputs, args.receipt.read_bytes())
        print('Image and receipt match; manual live gates remain as recorded')
    elif args.image:
        image_evidence(args.image, inputs, require_registry=not args.local_candidate)
        print('Image content verified; runtime-UA and restore NOTRUN')
    else:
        parser.error('Provide --lookup, --image or --selection')


if __name__ == '__main__':
    main()
