"""Fail-closed qualification of one amd64 bundle; never rebuild while publishing."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import urlopen

from check_release import image_evidence, registry_lookup
from image_inputs import ROOT, recipe_files, nginx_version, validate_resolved, checkout_revision
from release_contract import GATES, validate_checks, validate_receipt


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_inputs(path):
    inputs = json.loads(Path(path).read_text(encoding='utf8'))
    if inputs.get('wrapper_revision') != checkout_revision():
        raise ValueError('Capture the actual committed wrapper before qualification')
    return validate_resolved(inputs)


def inspect(ref):
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', ref], timeout=60))[0]
    if info.get('Os') != 'linux' or info.get('Architecture') != 'amd64':
        raise ValueError('Native linux/amd64 bundle required; ARM64 requires #22')
    return info


def component(ref, key=None):
    info = inspect(ref)
    if key is not None and (info['Config'].get('Labels') or {}).get('io.tg-selfhost.build-key') != key:
        raise ValueError('Component build key mismatch')
    return {'config_id': info['Id'], 'rootfs_sha256': sha(json.dumps(info['RootFS'], sort_keys=True).encode())}


def gateway_evidence(inputs):
    ref = inputs['nginx_image']
    subprocess.run(['docker', 'pull', ref], check=True, timeout=180)
    info = inspect(ref)
    if not any(d.endswith('@' + ref.rsplit('@', 1)[1]) for d in info.get('RepoDigests', [])):
        raise ValueError('Gateway digest mismatch')
    child = ref.split('@')[0] + '@' + inputs['nginx_platform_digest']
    index = json.loads(subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', ref, '--raw'], timeout=120))
    children = [m['digest'] for m in index.get('manifests', [])
                if m.get('platform', {}).get('os') == 'linux' and m.get('platform', {}).get('architecture') == 'amd64']
    if children != [inputs['nginx_platform_digest']]:
        raise ValueError('Gateway child does not belong to selected index')
    manifest = json.loads(subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', child, '--raw'], timeout=120))
    if manifest.get('config', {}).get('digest') != info['Id'] or nginx_version(ref) != inputs['nginx_version']:
        raise ValueError('Gateway child/config/version mismatch')
    subprocess.run(['docker', 'run', '--rm', '--network', 'none',
        '--mount', f'type=bind,src={ROOT / "nginx.conf"},dst=/etc/nginx/conf.d/default.conf,readonly',
        '--mount', f'type=bind,src={ROOT / "nginx-main.conf"},dst=/etc/nginx/nginx.conf,readonly',
        '--entrypoint', 'nginx', ref, '-t'], check=True, timeout=30)
    return {'image': ref, 'config_id': info['Id'], 'platform_digest': inputs['nginx_platform_digest'], 'version': inputs['nginx_version']}


def base_evidence(inputs):
    with urlopen('https://alpinelinux.org/releases.json', timeout=30) as response:
        branches = json.load(response)['release_branches']
    today = datetime.now(timezone.utc).date().isoformat()
    if not any(b['rel_branch'] == 'v3.22' and b['eol_date'] >= today for b in branches):
        raise ValueError('Locked Alpine branch is unsupported')
    records = {}
    for name in ('alpine_image', 'observer_base', 'python_image'):
        ref = inputs[name]
        subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', ref], check=True, timeout=180)
        info = inspect(ref)
        if not any(d.endswith('@' + ref.rsplit('@', 1)[1]) for d in info.get('RepoDigests', [])):
            raise ValueError('Base registry identity mismatch')
        index = json.loads(subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', ref, '--raw'], timeout=120))
        children = [m['digest'] for m in index.get('manifests', [])
                    if m.get('platform', {}).get('os') == 'linux' and m.get('platform', {}).get('architecture') == 'amd64']
        if len(children) != 1:
            raise ValueError('Base index must have one amd64 child')
        manifest = json.loads(subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', ref.split('@')[0] + '@' + children[0], '--raw'], timeout=120))
        if manifest.get('config', {}).get('digest') != info['Id']:
            raise ValueError('Base child/config mismatch')
        records[name] = {'image': ref, 'platform_digest': children[0], 'config_id': info['Id']}
    return records


def qualify(image, inputs, directory, observer, downloads, sender):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Qualification requires a native Linux amd64 runner')
    directory.mkdir(parents=True, exist_ok=True)
    actual = image_evidence(image, inputs, require_registry=False)
    sender_actual = image_evidence(sender, inputs, require_registry=False)
    for key in ('binary_sha256', 'inventories_sha256', 'wrapper_revision'):
        if actual[key] != sender_actual[key]:
            raise ValueError('Sender target differs from production build chain')
    components = {'botapi': component(image, inputs['build_key']),
                  'observer': component(observer, inputs['build_key']),
                  'downloads': component(downloads, inputs['downloads_key']),
                  'sender': component(sender, inputs['build_key'])}
    image, observer, downloads, sender = (components['botapi']['config_id'], components['observer']['config_id'],
                                         components['downloads']['config_id'], sender_actual['config_id'])
    gateway = gateway_evidence(inputs)
    for ref, expected_base in ((observer, inputs['observer_base']), (downloads, inputs['python_image'])):
        if (inspect(ref)['Config'].get('Labels') or {}).get('io.tg-selfhost.base') != expected_base:
            raise ValueError('Component base label differs from saved inputs')
    python_version = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', downloads, '--version'], timeout=30).decode().strip()
    if not re.fullmatch(r'Python 3\.12\.[0-9]+', python_version):
        raise ValueError('Downloads interpreter differs from saved Python series')
    checks = {}

    def gate(name, commands):
        path = directory / (name + '.log')
        with path.open('wb') as output:
            for command in commands:
                subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                               check=True, timeout=1800)
                output.write(json.dumps({'command': command[1:], 'exit_code': 0}).encode() + b'\n')
        if name == 'unit' and b'skipped=' in path.read_bytes():
            raise ValueError('Required POSIX tests did not execute')
        checks[name] = {'status': 'PASS', 'evidence_sha256': sha(path.read_bytes())}

    py = sys.executable
    gate('unit', [[py, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_issue12_*.py'],
                  [py, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_image_inputs.py'],
                  [py, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_entrypoint.py'],
                  [py, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_botapi_healthcheck.py']])
    static = {'image': actual, 'components': components, 'gateway': gateway, 'bases': base_evidence(inputs),
              'downloads_python': python_version}
    static_path = directory / 'static.json'
    static_path.write_text(json.dumps(static, sort_keys=True), encoding='utf8')
    checks['static'] = {'status': 'PASS', 'evidence_sha256': sha(static_path.read_bytes())}
    gate('image', [[py, 'tools/check_observability.py', '--botapi-image', image, '--observer-image', observer,
                    '--nginx-image', inputs['nginx_image']],
                   [py, 'tools/check_file_contract.py', '--botapi-image', image, '--downloads-image', downloads,
                    '--report', str(directory / 'files.json')],
                   [py, 'tools/check_gateway_uploads.py', '--profile', 'quick', '--revision', inputs['bot_api_revision'],
                    '--nginx-image', inputs['nginx_image'], '--report', str(directory / 'uploads.json')]])
    gate('runtime_ua', [[py, 'tools/webhook_probe.py', '--image', sender, '--output', str(directory / 'sender.json')]])
    gate('restore', [[py, 'tools/smoke_image.py', image, '--gateway-image', inputs['nginx_image'],
                       '--output', str(directory / 'runtime.json')]])
    resolved = directory / 'resolved.json'
    resolved.write_text(json.dumps(inputs), encoding='utf8')
    gate('apk_policy', [[py, 'tools/check_apk_refresh.py', '--inputs', str(resolved), '--output', str(directory / 'apk.json')]])
    # Observer inventory must correspond to the actual interpreter image, not server version labels.
    inventory = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', observer,
        '/usr/share/tg-selfhost-botapi/observer/installed'], timeout=30)
    installed = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', observer,
        '/lib/apk/db/installed'], timeout=30)
    refresh = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', observer,
        '/usr/share/tg-selfhost-botapi/observer/refresh-id'], timeout=30).decode().strip()
    if inventory != installed or refresh != inputs['apk_refresh_id']:
        raise ValueError('Observer dependency evidence mismatch')
    candidate = {'schema': 1, 'build_key': inputs['build_key'], 'qualification_key': inputs['qualification_key'],
        'image': actual, 'gateway': gateway, 'components': components, 'checks': checks,
        'artifacts_sha256': {name: sha((directory / name).read_bytes()) for name in
            ('static.json', 'sender.json', 'runtime.json', 'apk.json', 'files.json', 'uploads.json')},
        'recipe_sha256': {p: sha(raw) for p, raw in recipe_files().items()}}
    validate_evidence(candidate, directory)
    (directory / 'candidate.json').write_text(json.dumps(candidate, sort_keys=True) + '\n', encoding='utf8')
    return candidate


def validate_evidence(candidate, directory):
    if directory is None:
        raise ValueError('Publication requires executed gate evidence')
    validate_checks(candidate.get('checks'), approved=True)
    if set(candidate.get('artifacts_sha256', {})) != {'static.json', 'sender.json', 'runtime.json', 'apk.json', 'files.json', 'uploads.json'}:
        raise ValueError('Missing qualification result artifact hashes')
    for name, digest in candidate['artifacts_sha256'].items():
        if name not in ('static.json', 'sender.json', 'runtime.json', 'apk.json', 'files.json', 'uploads.json'):
            raise ValueError('Unexpected evidence file')
        if sha((directory / name).read_bytes()) != digest:
            raise ValueError('Qualification result artifact changed')
    for gate in GATES:
        path = directory / ('static.json' if gate == 'static' else gate + '.log')
        raw = path.read_bytes()
        if not raw or sha(raw) != candidate['checks'][gate]['evidence_sha256']:
            raise ValueError('Executed gate evidence differs: ' + gate)
    sender = json.loads((directory / 'sender.json').read_text())
    runtime = json.loads((directory / 'runtime.json').read_text())
    from smoke_image import validate_restore_evidence
    validate_restore_evidence(runtime)
    if (sender.get('production_sender') != 'PASS' or sender.get('queue_acknowledged') is not True
            or any(sender.get(k) != 'PASS' for k in ('receiver_negative_control', 'ack_error_control', 'ack_timeout_control'))
            or any(runtime.get(k) != 'PASS' for k in ('runtime_smoke', 'restore_rehearsal', 'readiness_abort'))
            or json.loads((directory / 'apk.json').read_text()).get('warm_cache') != 'PASS'):
        raise ValueError('Required sender/runtime/restore/APK results missing')


def publish(image, repository, inputs, candidate, directory, observer, downloads, sender='sender-candidate:check'):
    if not re.fullmatch(r'ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+', repository):
        raise ValueError('Invalid publication repository')
    validate_evidence(candidate, directory)
    if (candidate['qualification_key'] != inputs['qualification_key']
            or candidate['recipe_sha256'] != {p: sha(raw) for p, raw in recipe_files().items()}
            or candidate['image'] != image_evidence(image, inputs, require_registry=False)
            or candidate['gateway'] != gateway_evidence(inputs)):
        raise ValueError('Qualified candidate changed before publication')
    bundle = {}
    for name, ref, key, repo in (('botapi', image, inputs['build_key'], repository),
            ('observer', observer, inputs['build_key'], repository + '-observer'),
            ('downloads', downloads, inputs['downloads_key'], repository + '-downloads'),
            ('sender', sender, inputs['build_key'], repository + '-sender')):
        local = component(ref, key)
        if local != candidate['components'][name]:
            raise ValueError('Component changed before publication: ' + name)
        tag = repo + ':build-' + key
        digest = registry_lookup(tag)
        if digest is None:
            subprocess.run(['docker', 'tag', local['config_id'], tag], check=True)
            subprocess.run(['docker', 'push', tag], check=True, timeout=600)
            digest = registry_lookup(tag)
        if digest is None:
            raise ValueError('Published artifact unavailable')
        immutable = repo + '@' + digest
        subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', immutable], check=True, timeout=180)
        if component(immutable, key) != local:
            raise ValueError('Published config/rootfs differs from qualified artifact')
        bundle[name] = {'image': immutable, **local}
    remote = image_evidence(bundle['botapi']['image'], inputs)
    if any(remote.get(k) != v for k, v in candidate['image'].items()):
        raise ValueError('Published binary/metadata differs from qualified artifact')
    receipt = {'schema': 1, 'qualification_version': 1, 'build_key': inputs['build_key'],
        'qualification_key': inputs['qualification_key'], 'components': bundle,
        'platform': inputs['platform'], 'server_revision': inputs['bot_api_revision'],
        'server_version': inputs['bot_api_version'], 'tdlib_revision': inputs['submodules']['td'],
        'patch_sha256': sha((ROOT / 'patches/webhook-user-agent.patch').read_bytes()),
        'recipe_sha256': candidate['recipe_sha256'], 'checks': candidate['checks'],
        'gateway': candidate['gateway'], 'provenance': 'ci', **remote}
    validate_receipt(receipt, inputs, approved=True)
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('qualify', 'publish'))
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--image', default='botapi-candidate:check')
    p.add_argument('--observer', default='observer-candidate:check')
    p.add_argument('--downloads', default='downloads-candidate:check')
    p.add_argument('--sender', default='sender-candidate:check')
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--repository')
    args = p.parse_args()
    inputs = load_inputs(args.inputs)
    if args.action == 'qualify':
        qualify(args.image, inputs, args.directory, args.observer, args.downloads, args.sender)
    else:
        receipt = publish(args.image, args.repository, inputs,
            json.loads((args.directory / 'candidate.json').read_text()), args.directory, args.observer, args.downloads, args.sender)
        (args.directory / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True) + '\n', encoding='utf8')


if __name__ == '__main__':
    main()
