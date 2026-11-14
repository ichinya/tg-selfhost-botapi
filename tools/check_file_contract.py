"""Check the default gateway using an isolated synthetic Compose project."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import hashlib
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tools/fixtures/files'


class NotRun(Exception):
    pass


def command(args, env, timeout=120, include_stderr=False):
    try:
        result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=timeout, check=True)
        return result.stdout + (result.stderr if include_stderr else '')
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise NotRun('Docker unavailable or timed out') from exc


def prefix(project):
    if not re.fullmatch(r'filecontract[0-9a-f]{12}', project):
        raise ValueError('invalid project')
    return ['docker', 'compose', '-p', project, '--env-file', str(FIXTURE / 'synthetic.env'),
            '-f', str(FIXTURE / 'compose.yml')]


def validate(model, nginx):
    validate_base(model)
    nginx = re.sub(r'#[^\n]*', '', nginx)
    if re.search(r'\b(?:alias|root|include)\s', nginx):
        raise ValueError('gateway filesystem configuration')
    for location in (r'=\s*/file', r'/file/'):
        if not re.search(r'location\s+' + location + r'\s*\{\s*return\s+404\s*;', nginx):
            raise ValueError('missing file denial')


def validate_base(model):
    services = model['services']
    mounts = services['gateway'].get('volumes', [])
    allowed = {
        '/etc/nginx/nginx.conf': ROOT / 'nginx-main.conf',
        '/etc/nginx/conf.d/default.conf': ROOT / 'nginx.conf',
        '/etc/nginx/conf.d/observability.conf': ROOT / 'nginx.observability.conf',
    }
    found = set()
    for mount in mounts:
        target = mount.get('target')
        if target in found:
            raise ValueError('duplicate gateway mount')
        found.add(target)
        if target == '/var/cache/nginx/client_temp':
            if (mount.get('type') != 'volume' or mount.get('read_only')
                    or mount.get('source') != 'gateway_client_temp'):
                raise ValueError('unexpected spool mount')
        elif (target not in allowed or mount.get('type') != 'bind' or not mount.get('read_only')
              or Path(mount.get('source', '')).resolve() != allowed[target].resolve()):
            raise ValueError('unexpected gateway mount')
    if not {'/etc/nginx/nginx.conf', '/etc/nginx/conf.d/default.conf', '/var/cache/nginx/client_temp'} <= found or services['botapi'].get('ports'):
        raise ValueError('base gateway or backend exposure')


def validate_gateway_runtime(container):
    allowed = {
        '/etc/nginx/nginx.conf': ROOT / 'nginx-main.conf',
        '/etc/nginx/conf.d/default.conf': ROOT / 'nginx.conf',
        '/etc/nginx/conf.d/observability.conf': ROOT / 'nginx.observability.conf',
    }
    found = set()
    for mount in container.get('Mounts', []):
        target = mount.get('Destination')
        if target in found:
            raise ValueError('duplicate gateway mount')
        found.add(target)
        if target == '/var/cache/nginx/client_temp':
            if mount.get('Type') != 'volume' or mount.get('RW') is not True:
                raise ValueError('unexpected spool mount')
        elif (target not in allowed or mount.get('RW') is not False
              or Path(mount.get('Source', '')).resolve() != allowed[target].resolve()):
            raise ValueError('runtime gateway storage exposure')
    if not {'/etc/nginx/nginx.conf', '/etc/nginx/conf.d/default.conf', '/var/cache/nginx/client_temp'} <= found:
        raise ValueError('missing runtime gateway mount')


PROBE = r'''
import http.client, json, time
paths = ['/file', '/file/', '/file/bot12345:SYNTHETIC_TOKEN/a',
         '/file/%2e%2e/binlog', '/file/%252e%252e/binlog',
         '/file%2f..%2fbinlog', '/file/../binlog', '/private-state/binlog',
         '/private-temp/cache', '/private-secret/token']
for attempt in range(30):
    try:
        c = http.client.HTTPConnection('gateway', 80, timeout=2)
        c.request('GET', '/bot12345:SYNTHETIC_TOKEN/getMe')
        r = c.getresponse(); body = r.read(); c.close()
        if r.status == 200 and body == b'SYNTHETIC_API_OK': break
    except OSError: pass
    time.sleep(1)
else: raise RuntimeError('gateway unavailable')
for path in paths:
    for headers in ({}, {'X-Telegram-Bot-Token': '12345:SYNTHETIC_TOKEN'}):
        c = http.client.HTTPConnection('gateway', 80, timeout=3)
        c.request('GET', path, headers=headers)
        r = c.getresponse(); body = r.read(); c.close()
        if r.status != 404 or b'SYNTHETIC_' in body: raise RuntimeError('isolation failure')
c = http.client.HTTPConnection('botapi', 8081, timeout=3)
c.request('GET', '/stats')
r = c.getresponse(); audit = json.loads(r.read()); c.close()
if r.status != 200 or audit['file_requests'] != 0: raise RuntimeError('file request reached upstream')
print('PASS')
'''


def pin_nginx(env):
    from image_inputs import resolve
    reference = env.get('FILE_NGINX_IMAGE') or resolve()['nginx_image']
    if not re.fullmatch(r'nginx(?::[a-zA-Z0-9_.-]+)?@sha256:[0-9a-f]{64}', reference):
        raise ValueError('invalid fixture image')
    command(['docker', 'pull', reference], env, timeout=180)
    metadata = json.loads(command(['docker', 'image', 'inspect', reference], env))[0]
    for digest in metadata.get('RepoDigests') or []:
        if re.fullmatch(r'(?:docker.io/library/)?nginx@sha256:[0-9a-f]{64}', digest):
            if digest.split('@', 1)[1] == reference.split('@', 1)[1]:
                return 'nginx@' + digest.split('@', 1)[1]
    raise ValueError('fixture digest unavailable')


def check(report=None):
    if not shutil.which('docker'):
        raise NotRun('Docker CLI unavailable')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('COMPOSE_', 'BOTAPI_', 'GATEWAY_', 'API_'))}
    env['FIXTURE_NGINX'] = str(ROOT / 'nginx.conf')
    env['FIXTURE_NGINX_MAIN'] = str(ROOT / 'nginx-main.conf')
    env['API_ID'] = '12345'
    env['API_HASH'] = 'SYNTHETIC_ONLY'
    try:
        command(['docker', 'info'], env, timeout=15)
    except subprocess.CalledProcessError as exc:
        raise NotRun('Docker daemon unavailable') from exc
    env['FILE_NGINX_IMAGE'] = pin_nginx(env)
    if report is not None:
        report.setdefault('fixture_images', {})['nginx'] = env['FILE_NGINX_IMAGE']
    project = 'filecontract' + uuid.uuid4().hex[:12]
    compose = prefix(project)
    started = False
    try:
        base = ['docker', 'compose', '-p', project, '--env-file', str(FIXTURE / 'synthetic.env'),
                '-f', str(ROOT / 'docker-compose.yml')]
        validate_base(json.loads(command(base + ['config', '--format', 'json'], env)))
        model = json.loads(command(compose + ['config', '--format', 'json'], env))
        validate(model, (ROOT / 'nginx.conf').read_text(encoding='utf-8'))
        started = True
        command(compose + ['up', '-d', '--build'], env, timeout=300)
        gateway = command(compose + ['ps', '-q', 'gateway'], env).strip()
        validate_gateway_runtime(json.loads(command(['docker', 'inspect', gateway], env))[0])
        command(compose + ['exec', '-T', 'botapi', 'python', '-c', PROBE], env, timeout=60)
    finally:
        if started:
            command(compose + ['down', '--volumes', '--remove-orphans'], env, timeout=90)


def validate_full(model):
    services = model['services']
    root = '/var/lib/telegram-bot-api-files/12345:SYNTHETIC_A'
    for name, service in services.items():
        if service.get('container_name') or service.get('ports') or service.get('network_mode') == 'host':
            raise ValueError('fixture must not publish or select production containers')
        if bool(service.get('privileged')) != (name == 'mountcheck'):
            raise ValueError('unexpected fixture privilege')
    for name in ('reader', 'downloads'):
        service = services[name]
        if str(service.get('user')) != '101:101' or not service.get('read_only'):
            raise ValueError('consumer identity or writable rootfs')
        mounts = service['volumes']
        if any(not m.get('read_only') for m in mounts):
            raise ValueError('writable consumer storage')
        media = [m for m in mounts if m['target'].startswith('/var/lib')]
        if (len(media) != 1 or media[0]['target'] != root or media[0]['source'] != 'media'
                or media[0].get('volume', {}).get('subpath') != '12345:SYNTHETIC_A'):
            raise ValueError('consumer subtree mismatch')
        if any(m['target'] != root and not m['target'].startswith('/run/secrets/') for m in mounts):
            raise ValueError('unexpected private consumer mount')
    for name in ('gateway', 'tls'):
        if any(m['source'] in ('media', 'state', 'secret') for m in services[name].get('volumes', [])):
            raise ValueError('frontend storage exposure')


def validate_split(model):
    services = model['services']
    api = services['botapi']
    media = '/var/lib/telegram-bot-api-files'
    if api.get('environment', {}).get('TELEGRAM_FILES_DIR') != media or api.get('ports'):
        raise ValueError('split settings')
    volumes = api['volumes']
    media_mount = next(m for m in volumes if m['target'] == media)
    state_mount = next(m for m in volumes if m['target'] == '/var/lib/telegram-bot-api')
    # Container path differences do not establish independent host backings.
    first, second = Path(media_mount['source']).resolve(), Path(state_mount['source']).resolve()
    if first == second or first in second.parents or second in first.parents:
        raise ValueError('split backing overlap')
    validate_base(model)


def source_hashes():
    from image_inputs import RECIPE, DOWNLOADS_RECIPE
    fixtures = ('tools/fixtures/files/runtime.py', 'tools/fixtures/files/compose.full.yml',
                'tools/fixtures/files/Dockerfile.full', 'tools/fixtures/files/nginx.downloads.conf')
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(set(RECIPE + DOWNLOADS_RECIPE + fixtures))}


def exercise(botapi_image, downloads_image, report):
    if not botapi_image or not downloads_image:
        raise NotRun('exact Bot API and downloads images are required')
    project = 'filecontract' + uuid.uuid4().hex[:12]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('COMPOSE_', 'BOTAPI_', 'DOWNLOAD', 'FIXTURE_', 'FILE_', 'API_', 'GATEWAY_'))}
    env.update(BOTAPI_TEST_IMAGE=botapi_image, DOWNLOADS_TEST_IMAGE=downloads_image,
               FILE_FIXTURE_IMAGE=project + '-fixture', FIXTURE_NGINX=str(ROOT / 'nginx.conf'),
               FIXTURE_NGINX_MAIN=str(ROOT / 'nginx-main.conf'),
               FIXTURE_TLS_CONFIG=str(FIXTURE / 'nginx.downloads.conf'))
    env['FILE_NGINX_IMAGE'] = report['fixture_images']['nginx']
    compose = ['docker', 'compose', '-p', project, '--env-file', str(FIXTURE / 'synthetic.env'),
               '-f', str(FIXTURE / 'compose.full.yml')]
    validate_full(json.loads(command(compose + ['config', '--format', 'json'], env)))
    base = ['docker', 'compose', '-p', project, '--env-file', str(FIXTURE / 'synthetic.env'),
            '-f', str(ROOT / 'docker-compose.yml'), '-f', str(ROOT / 'docker-compose.files.yml')]
    validate_split(json.loads(command(base + ['config', '--format', 'json'], env)))
    report['source_sha256'] = source_hashes()
    report['images'] = {}
    for name, image in (('botapi', botapi_image), ('downloads', downloads_image)):
        metadata = json.loads(command(['docker', 'image', 'inspect', image], env))[0]
        report['images'][name] = metadata['Id']
        if name == 'botapi':
            revision = metadata.get('Config', {}).get('Labels', {}).get('io.tg-selfhost.bot-api-revision', '')
            if not re.fullmatch(r'[0-9a-f]{40}', revision): raise ValueError('candidate upstream provenance absent')
            report['upstream_revision'] = revision
    packaged = ['tools/file_access.py', 'tools/file_contract.py', 'tools/download_server.py',
                'examples/files/local_reader.py']
    hash_program = ('import hashlib,json; print(json.dumps({p:hashlib.sha256(open("/app/"+p,"rb").read()).hexdigest() '
                    'for p in ' + repr(packaged) + '}))')
    observed = json.loads(command(['docker', 'run', '--rm', '--network', 'none', '--entrypoint',
                                  'python', downloads_image, '-c', hash_program], env))
    if observed != {p: report['source_sha256'][p] for p in packaged}:
        raise ValueError('downloads image does not contain this candidate')
    entrypoint_hash = command(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'sh',
                              botapi_image, '-c', 'sha256sum /docker-entrypoint.sh'], env).split()[0]
    if entrypoint_hash != report['source_sha256']['docker-entrypoint.sh']:
        raise ValueError('Bot API entrypoint does not contain this candidate')
    report['packaged_sources'] = 'PASS'
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        context = Path(directory)
        files = ['tools/file_access.py', 'tools/file_contract.py', 'tools/download_server.py',
                 'tools/test_file_access.py', 'tools/test_download_server.py',
                 'examples/files/local_reader.py', 'examples/files/remote_client.py']
        for name in files:
            target = context / 'app' / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        (context / 'runtime.py').write_bytes((FIXTURE / 'runtime.py').read_bytes())
        (context / 'Dockerfile').write_bytes((FIXTURE / 'Dockerfile.full').read_bytes())
        try:
            command(['docker', 'build', '-t', env['FILE_FIXTURE_IMAGE'], str(context)], env, timeout=300)
            def once(service, *args):
                output = command(compose + ['run', '--rm', '--no-deps', service, *args], env, timeout=120)
                lines = [line for line in output.splitlines() if line.startswith('{')]
                if not lines or json.loads(lines[-1]).get('status') != 'PASS':
                    raise ValueError('missing fixture evidence')
            once('setup')
            command(compose + ['up', '-d', 'botapi', 'gateway', 'downloads', 'tls'], env)
            once('reader')
            report['local'] = 'PASS'
            once('kernel')
            report['kernel_security'] = 'PASS'
            once('client')
            report['remote_tls'] = 'PASS'
            once('mountcheck')
            report['nested_bind'] = 'PASS'
            rss = command(compose + ['exec', '-T', 'downloads', 'python', '-c',
                "import os; s=open('/proc/1/status').read(); n=int(next(l.split()[1] for l in s.splitlines() if l.startswith('VmRSS:'))); assert n<131072; assert len(os.listdir('/proc/1/fd'))<32"], env)
            report['resources'] = 'PASS'
            report['synthetic'] = 'PASS'
            help_text = command(compose + ['run', '--rm', '--no-deps', 'actual', '--help'], env, include_stderr=True)
            if '--files-dir' not in help_text: raise ValueError('candidate lacks files-dir')
            command(compose + ['up', '-d', 'actual'], env)
            probe = ('test "$(awk \'/^Uid:/ {print $3}\' /proc/1/status)" = 101 && '
                     'test "$(awk \'/^Gid:/ {print $3}\' /proc/1/status)" = 101 && '
                     'test "$(stat -c %u:%g /var/lib/telegram-bot-api-files)" = 101:101 && '
                     'test "$(stat -c %a /var/lib/telegram-bot-api-files)" = 770 && '
                     'tr \'\\0\' \'\\n\' </proc/1/cmdline | grep -qx -- --files-dir=/var/lib/telegram-bot-api-files')
            for attempt in range(30):
                try:
                    command(compose + ['exec', '-T', 'actual', 'sh', '-ec', probe], env, timeout=5)
                    break
                except subprocess.CalledProcessError:
                    time.sleep(0.25)
            else: raise ValueError('actual startup not verified')
            for service, role in (('actual', 'botapi'), ('downloads', 'downloads')):
                identifier = command(compose + ['ps', '-q', service], env).strip()
                metadata = json.loads(command(['docker', 'inspect', identifier], env))[0]
                if metadata['Image'] != report['images'][role]: raise ValueError('candidate identity mismatch')
                if service == 'downloads':
                    allowed = {'/var/lib/telegram-bot-api-files/12345:SYNTHETIC_A', '/run/secrets/bot-token', '/run/secrets/auth'}
                    if {m['Destination'] for m in metadata['Mounts']} != allowed or any(m['RW'] for m in metadata['Mounts']):
                        raise ValueError('runtime consumer mount scope')
            report['actual_startup'] = 'PASS'
            logs = command(compose + ['logs', '--no-color', 'downloads', 'tls'], env)
            if any(value in logs for value in ('SYNTHETIC_A', 'PRIVATE_CANARY', 'A' * 40, '/var/lib/telegram-bot-api-files')):
                raise ValueError('fixture log privacy')
            report['log_privacy'] = 'PASS'
        finally:
            command(compose + ['down', '--volumes', '--remove-orphans'], env, timeout=90)
            # Remove only the unique helper image built by this invocation.
            command(['docker', 'image', 'rm', env['FILE_FIXTURE_IMAGE']], env, timeout=30)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-isolation-only', action='store_true')
    parser.add_argument('--botapi-image')
    parser.add_argument('--downloads-image')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    report = {'status': 'NOTRUN', 'synthetic': 'NOTRUN', 'actual_startup': 'NOTRUN',
              'production': 'NOTRUN', 'mode': 'state-only' if args.state_isolation_only else 'full'}
    code = 0
    try:
        check(report)
        report['state_isolation'] = 'PASS'
        if not args.state_isolation_only:
            exercise(args.botapi_image, args.downloads_image, report)
            report['synthetic'] = 'PASS'
            check(report)
        report['status'] = 'PASS'
    except NotRun as exc:
        report['reason'] = str(exc); code = 2
    except (ValueError, KeyError, StopIteration, OSError, subprocess.CalledProcessError) as exc:
        report['status'] = 'FAIL'; report['error'] = type(exc).__name__; code = 1
    output = json.dumps(report, sort_keys=True, indent=2)
    print(output)
    if args.report: args.report.write_text(output + '\n', encoding='utf-8')
    return code


if __name__ == '__main__':
    sys.exit(main())
