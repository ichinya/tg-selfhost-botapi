"""Isolated no-bot runtime, stopped-state backup and readiness-abort restore."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import posixpath
from datetime import datetime, timezone
from check_release import check_gateway
from image_inputs import ROOT


def archive_manifest(raw):
    """Private content/owner/mode comparison; only the aggregate hash is public."""
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts or member.name in result:
                raise ValueError('Unsafe or duplicate archive entry')
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError('Special files are not permitted in a cold backup')
            if member.issym() or member.islnk():
                base = posixpath.dirname(member.name) if member.issym() else ''
                target = posixpath.normpath(posixpath.join(base, member.linkname))
                if member.linkname.startswith('/') or target == '..' or target.startswith('../'):
                    raise ValueError('Archive link escapes the storage root')
            contents = archive.extractfile(member).read() if member.isfile() else b''
            result[member.name] = (member.type.decode('ascii'), member.uid, member.gid, member.mode,
                                   member.size, member.linkname, hashlib.sha256(contents).hexdigest())
    return result


def run(*args, timeout=180):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def validate_shutdown(events, state):
    """A zero exit alone cannot establish the cold-backup precondition."""
    signals = [str(e.get('Actor', {}).get('Attributes', {}).get('signal'))
               for e in events if e.get('Action') == 'kill']
    exited = [e for e in events if e.get('Action') == 'die'
              and str(e.get('Actor', {}).get('Attributes', {}).get('exitCode')) == '0']
    if (state.get('Running') or state.get('OOMKilled') or state.get('ExitCode') != 0
            or any(e.get('Action') == 'oom' for e in events)
            or signals not in (['15'], ['SIGTERM']) or len(exited) != 1):
        raise ValueError('Unclean or unobserved shutdown; backup aborted')


def runtime(image, gateway):
    if '@sha256:' not in gateway:
        raise ValueError('Gateway requires an immutable candidate')
    with tempfile.TemporaryDirectory(prefix='botapi-rehearsal-') as tmp:
        root = Path(tmp)
        state, restored = root / 'state', root / 'restored'
        state.mkdir(); restored.mkdir()
        config = {'networks': {'default': {'internal': True}}, 'services': {
            'botapi': {'image': image, 'cpus': 1, 'mem_limit': '512m',
                'environment': {'TELEGRAM_API_ID': '12345', 'TELEGRAM_API_HASH': '0123456789abcdef0123456789abcdef', 'TELEGRAM_LOCAL': 'true'},
                'volumes': [f'{state}:/var/lib/telegram-bot-api'], 'stop_grace_period': '2m',
                'healthcheck': {'test': ['CMD', '/usr/local/bin/botapi-healthcheck'], 'interval': '2s', 'timeout': '3s', 'retries': 10}},
            'gateway': {'image': gateway, 'cpus': 0.5, 'mem_limit': '128m',
                'ports': ['127.0.0.1::80'], 'volumes': [f'{ROOT / "nginx.conf"}:/etc/nginx/conf.d/default.conf:ro', f'{ROOT / "nginx-main.conf"}:/etc/nginx/nginx.conf:ro'],
                'depends_on': {'botapi': {'condition': 'service_healthy'}}}}}
        path = root / 'compose.json'
        compose = ('docker', 'compose', '-p', 'smoke' + root.name.replace('_', '').replace('-', ''), '-f', str(path))
        def save():
            path.write_text(json.dumps(config), encoding='utf8')
        def gateway_check():
            port = run(*compose, 'port', 'gateway', '80').rsplit(':', 1)[1]
            check_gateway(f'http://127.0.0.1:{port}/')
        def stop_clean():
            container = run(*compose, 'ps', '-q', 'botapi')
            run(*compose, 'stop', 'gateway')
            since = datetime.now(timezone.utc).isoformat()
            start = time.monotonic()
            run(*compose, 'stop', 'botapi', timeout=130)
            actual = json.loads(run('docker', 'inspect', container))[0]['State']
            until = datetime.now(timezone.utc).isoformat()
            raw = run('docker', 'events', '--since', since, '--until', until,
                      '--filter', 'container=' + container, '--format', '{{json .}}')
            validate_shutdown([json.loads(line) for line in raw.splitlines()], actual)
            return round(time.monotonic() - start, 3)
        save()
        try:
            run(*compose, 'up', '-d', '--wait', '--wait-timeout', '180')
            gateway_check()
            run(*compose, 'exec', '-T', '--user', '101:101', 'botapi', 'sh', '-ec', 'printf release-fixture > /var/lib/telegram-bot-api/release-rehearsal')
            run(*compose, 'restart', 'botapi')
            run(*compose, 'up', '-d', '--wait', '--wait-timeout', '180', 'botapi')
            run(*compose, 'up', '-d', '--force-recreate', '--no-deps', 'gateway')
            gateway_check()
            elapsed = stop_clean()
            archive = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '128m', '-v', f'{state}:/state:ro', '--entrypoint', 'tar', image, '-cpf', '-', '-C', '/state', '.'], timeout=60)
            with tarfile.open(fileobj=io.BytesIO(archive)) as saved:
                marker = next(m for m in saved.getmembers() if m.name == './release-rehearsal')
                if (marker.uid, marker.gid) != (101, 101):
                    raise ValueError('Archive lost numeric ownership')
            archive_path = root / 'stopped-state.tar'
            archive_path.write_bytes(archive)
            checksum = hashlib.sha256(archive).hexdigest()
            original_tree = archive_manifest(archive)
            if hashlib.sha256(archive_path.read_bytes()).hexdigest() != checksum:
                raise ValueError('Archive checksum mismatch')
            config['services']['botapi']['healthcheck'] = {'test': ['CMD', '/bin/false'], 'interval': '1s', 'timeout': '1s', 'retries': 1, 'start_period': '0s'}
            run(*compose, 'down')
            save()
            failure = subprocess.run([*compose, 'up', '-d', '--force-recreate', '--wait', '--wait-timeout', '15'], capture_output=True, timeout=30)
            if failure.returncode == 0:
                raise ValueError('Readiness failure was accepted')
            if run(*compose, 'ps', '--status', 'running', '-q', 'gateway'):
                raise ValueError('Gateway started before backend readiness')
            run(*compose, 'stop', 'botapi', timeout=130)
            run(*compose, 'down')
            subprocess.run(['docker', 'run', '-i', '--rm', '--network', 'none', '--cpus', '1', '--memory', '128m', '-v', f'{restored}:/state', '--entrypoint', 'tar', image, '-xpf', '-', '-C', '/state'], input=archive, check=True, timeout=60)
            restored_archive = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '-v', f'{restored}:/state:ro', '--entrypoint', 'tar', image, '-cpf', '-', '-C', '/state', '.'], timeout=60)
            if archive_manifest(restored_archive) != original_tree:
                raise ValueError('Full restored tree/content/ownership differs from snapshot')
            config['services']['botapi']['healthcheck'] = {'test': ['CMD', '/usr/local/bin/botapi-healthcheck'], 'interval': '2s', 'timeout': '3s', 'retries': 10}
            config['services']['botapi']['volumes'] = [f'{restored}:/var/lib/telegram-bot-api']
            save()
            run(*compose, 'up', '-d', '--wait', '--wait-timeout', '180')
            gateway_check()
            if run(*compose, 'exec', '-T', '--user', '101:101', 'botapi', 'cat', '/var/lib/telegram-bot-api/release-rehearsal') != 'release-fixture':
                raise ValueError('Restored fixture differs')
            stop_clean()
            return {'runtime_smoke': 'PASS', 'restore_rehearsal': 'PASS', 'readiness_abort': 'PASS', 'archive_sha256': checksum,
                    'full_tree_sha256': hashlib.sha256(json.dumps(original_tree, sort_keys=True).encode()).hexdigest(),
                    'shutdown_seconds': elapsed, 'live_delivery': 'NOTRUN', 'production_state': 'UNKNOWN'}
        finally:
            run(*compose, 'down', '--volumes', '--remove-orphans')
            # Only this freshly created rehearsal root is mounted; release ownership
            # back to the runner so its private TemporaryDirectory can be removed.
            for directory in (state, restored):
                if directory.resolve().parent != root.resolve():
                    raise ValueError('Unexpected rehearsal cleanup target')
                run('docker', 'run', '--rm', '--network', 'none', '--cpus', '0.5', '--memory', '128m',
                    '-v', f'{directory}:/state', '--entrypoint', 'chown', image,
                    '-R', f'{os.getuid()}:{os.getgid()}', '/state')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    parser.add_argument('--gateway-image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(runtime(args.image, args.gateway_image), sort_keys=True) + '\n', encoding='utf8')
