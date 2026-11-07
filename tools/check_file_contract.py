"""Fail-closed synthetic file-contract gate. Runtime never touches live storage."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tools/fixtures/files'
MEDIA = '/var/lib/telegram-bot-api-files'
TOKENS = ('12345:SYNTHETIC_A', '12345:SYNTHETIC_B')


class NotRun(Exception):
    pass


def run(args, env, timeout=120, check=True):
    result = subprocess.run(args, env=env, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # Docker stderr can contain mounted paths or request details: never copy it to receipts.
        raise RuntimeError('fixture command failed; inspect the isolated CI step privately')
    return result


def environment(botapi, downloads, permissions='permissions-candidate:check'):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('COMPOSE_', 'API_', 'BOT', 'TELEGRAM_', 'DOWNLOADS_', 'PERMISSIONS_', 'FIXTURE_', 'TLS_'))}
    env.update(API_ID='12345', API_HASH='SYNTHETIC_ONLY', GATEWAY_BIND='127.0.0.1', BOTAPI_IMAGE=botapi,
               BOTAPI_TEST_IMAGE=botapi, DOWNLOADS_TEST_IMAGE=downloads, DOWNLOADS_IMAGE=downloads,
               PERMISSIONS_TEST_IMAGE=permissions,
               DOWNLOADS_CONFIG_FILE='/srv/private/downloads.config.json', BOT_TOKEN_FILE='/srv/private/token',
               BOT_A_HOST_ROOT='/srv/private/media/bot-a', BOT_A_ROOT=MEDIA + '/' + TOKENS[0],
               ROOT_DIR=str(ROOT), FIXTURE_DIR=str(FIXTURE), TLS_CONFIG=str(FIXTURE / 'unused.conf'),
               FIXTURE_REGISTRY_DIR='/tmp/fixture-registry', FIXTURE_TOKEN_DIR='/tmp/fixture-token')
    return env


def source_hashes():
    try:
        from .image_inputs import RECIPE, DOWNLOADS_RECIPE
    except ImportError:
        from image_inputs import RECIPE, DOWNLOADS_RECIPE
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sorted(set((*RECIPE, *DOWNLOADS_RECIPE)))}


def compose_prefix(project):
    if not re.fullmatch(r'filecontract[0-9a-f]{12}', project):
        raise ValueError('invalid fixture project')
    return ['docker', 'compose', '-p', project, '--project-directory', str(ROOT),
            '--env-file', str(FIXTURE / 'synthetic.env')]


def compose_model(prefix, files, env):
    command = prefix + sum((['-f', str(ROOT / name)] for name in files), [])
    return json.loads(run(command + ['config', '--format', 'json'], env).stdout)


STATE_CANARY_PATHS = (
    '/file', '/file/', '/file/bot12345:SYNTHETIC_A/webhooks_db.binlog',
    '/file/../webhooks_db.binlog', '/file/%2e%2e/webhooks_db.binlog',
    '/file/%252e%252e/webhooks_db.binlog', '/webhooks_db.binlog',
    '/var/lib/telegram-bot-api/webhooks_db.binlog', '//file//webhooks_db.binlog',
)


def validate_state_nginx(config):
    config = re.sub(r'#[^\n]*', '', config)
    if re.search(r'\b(alias|root|include)\s', config):
        raise ValueError('gateway filesystem or indirect configuration')
    locations = re.findall(r'\blocation\s+([^{}]+)\{', config)
    if [value.strip() for value in locations] != ['/']:
        raise ValueError('gateway alternative location')
    if re.findall(r'\bproxy_pass\s+([^;]+);', config) != ['http://botapi:8081']:
        raise ValueError('gateway upstream changed')


def validate_state_isolation(model):
    services = model['services']
    gateway, botapi = services['gateway'], services['botapi']
    if botapi.get('ports') or 'downloads' in services:
        raise ValueError('base backend publication or opt-in dependency')
    mounts = gateway.get('volumes', [])
    if (len(mounts) != 1 or mounts[0]['target'] != '/etc/nginx/conf.d/default.conf'
            or not mounts[0].get('read_only')):
        raise ValueError('default gateway storage')
    if len(gateway.get('ports', [])) != 1 or gateway['ports'][0].get('host_ip') != '127.0.0.1':
        raise ValueError('default gateway binding')


def validate_profiles(model, profile):
    services = model['services']
    gateway, botapi = services['gateway'], services['botapi']
    if botapi.get('ports') or botapi['environment'].get('TELEGRAM_FILES_DIR') != MEDIA:
        raise ValueError('split storage/backend publication contract')
    if {v['target'] for v in botapi['volumes']} != {'/var/lib/telegram-bot-api', MEDIA}:
        raise ValueError('split mounts')
    if len(gateway.get('volumes', [])) != 1 or gateway['volumes'][0]['target'] != '/etc/nginx/conf.d/default.conf':
        raise ValueError('default gateway storage')
    if gateway['ports'][0].get('host_ip') != '127.0.0.1':
        raise ValueError('default gateway binding')
    if profile == 'base':
        if 'downloads' in services:
            raise ValueError('default depends on opt-in')
        return
    name = 'reader' if profile == 'local' else 'downloads'
    consumer = services[name]
    if consumer.get('ports') or consumer.get('user') != '10001:101' or not consumer.get('read_only'):
        raise ValueError('consumer privileges')
    if (consumer.get('cap_drop') != ['ALL'] or 'no-new-privileges:true' not in consumer.get('security_opt', [])
            or not consumer.get('mem_limit') or not consumer.get('pids_limit') or not consumer.get('cpus')):
        raise ValueError('consumer resource limits')
    for mount in consumer['volumes']:
        if not mount.get('read_only') or mount.get('bind', {}).get('create_host_path') is not False:
            raise ValueError('consumer bind must fail closed')
        if mount['target'] not in (MEDIA + '/' + TOKENS[0], '/run/secrets/downloads.config.json', '/run/secrets/bot-token'):
            raise ValueError('consumer mount scope')
    if profile == 'remote':
        proxy = services['downloads-gateway']
        ports = proxy.get('ports', [])
        if len(ports) != 1 or ports[0].get('host_ip') != '127.0.0.1' or str(ports[0].get('published')) != '18082':
            raise ValueError('download proxy binding')
        if len(proxy['volumes']) != 1 or proxy['volumes'][0]['target'] != '/etc/nginx/conf.d/default.conf':
            raise ValueError('download proxy storage')


def validate_fixture(model):
    services = model['services']
    for name, service in services.items():
        if not all(service.get(k) for k in ('cpus', 'mem_limit', 'pids_limit')):
            raise ValueError('missing fixture resource bound')
        if bool(service.get('privileged')) != (name == 'mountcheck'):
            raise ValueError('privilege outside mount helper')
        if service.get('ports') and name not in ('downloads-gateway', 'downloads-tls'):
            raise ValueError('fixture backend published')
    for name in ('downloads', 'reader'):
        service = services[name]
        if service['user'] != '10001:101' or not service.get('read_only'):
            raise ValueError('fixture consumer identity')
        secret_target = '/run/secrets/' + ('downloads.config.json' if name == 'downloads' else 'bot-token')
        secrets = [v for v in service['volumes'] if v['target'] == secret_target]
        if (len(secrets) != 1 or secrets[0]['type'] != 'bind' or not secrets[0].get('read_only')
                or secrets[0].get('bind', {}).get('create_host_path') is not False):
            raise ValueError('fixture secret must be a file bind')
        mounts = [v for v in service['volumes'] if v['target'].startswith(MEDIA)]
        if len(mounts) != (2 if name == 'downloads' else 1):
            raise ValueError('fixture bot mount count')
        for mount in mounts:
            suffix = mount['target'][len(MEDIA) + 1:]
            if (suffix not in TOKENS or not mount.get('read_only')
                    or mount.get('volume', {}).get('subpath') != suffix):
                raise ValueError('fixture submount boundary')
    for name in ('downloads-gateway', 'downloads-tls'):
        if any(v['target'].startswith((MEDIA, '/private-state', '/run/secrets')) for v in services[name]['volumes']):
            raise ValueError('proxy storage boundary')


def check_models(project, env, state_only=False):
    prefix = compose_prefix(project)
    result = []
    if state_only:
        validate_state_nginx((ROOT / 'nginx.conf').read_text(encoding='utf-8'))
        models = []
        for files in (['docker-compose.yml'], ['docker-compose.yml', 'docker-compose.build.yml']):
            model = compose_model(prefix, files, env)
            validate_state_isolation(model)
            models.append(model)
            result.append('+'.join(files))
        return result, hashlib.sha256(json.dumps(models, sort_keys=True).encode()).hexdigest()
    for files, profile in [(['docker-compose.yml'], 'base'),
            (['docker-compose.yml', 'docker-compose.build.yml'], 'base'),
            (['docker-compose.yml', 'examples/files/compose.local.yml'], 'local'),
            (['docker-compose.yml', 'docker-compose.downloads.yml'], 'remote'),
            (['docker-compose.yml', 'docker-compose.build.yml', 'docker-compose.downloads.yml'], 'remote')]:
        validate_profiles(compose_model(prefix, files, env), profile)
        result.append('+'.join(files))
    fixture = compose_model(prefix, ['tools/fixtures/files/compose.yml'], env)
    validate_fixture(fixture)
    result.append('synthetic-fixture')
    return result, hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()


def source_contract(revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision or ''):
        raise ValueError('candidate upstream revision required')
    base = f'https://raw.githubusercontent.com/tdlib/telegram-bot-api/{revision}/telegram-bot-api/'
    hashes = {}
    checks = {
        'Client.cpp': ['bot_token_with_dc_ = bot_token_ + (is_test_dc_ ? ":T" : "")',
                       'files_dir_ = parameters_->files_directory_ + suff', "c = '~'",
                       'request->database_directory_ = dir_', 'request->files_directory_ = files_dir_'],
        'telegram-bot-api.cpp': ['"files-dir"', 'files_directory = working_directory',
                                'temporary_directory = files_directory + temporary_directory',
                                'log_file_path = files_directory + log_file_path'],
    }
    for name, needles in checks.items():
        with urlopen(base + name, timeout=30) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024 or any(needle not in data.decode('utf-8') for needle in needles):
            raise ValueError('upstream layout changed; review storage binding')
        hashes[name] = hashlib.sha256(data).hexdigest()
    return hashes


def validate_writer_sources(sources):
    """Known downloaded-media path only; drift requires review, never inference."""
    sources = {name: re.sub(r'/\*.*?\*/|//[^\n]*', '', value, flags=re.S)
               for name, value in sources.items()}
    loader = sources['FileLoaderUtils.cpp']
    if (not re.search(r'FileFd::open\(name,\s*FileFd::Read\s*\|\s*FileFd::Write\s*\|\s*FileFd::CreateNew,\s*0640\)', loader)
            or not re.search(r'mkdir\(path,\s*0750\)', loader)
            or not re.search(r'rename\(temp_path,\s*perm_path\)', loader)
            or re.search(r'\b(?:chmod|chown)\s*\(', loader)):
        raise ValueError('TDLib media create/move contract changed')
    if not re.search(r'::open\(filepath\.c_str\(\),\s*native_flags,\s*static_cast<mode_t>\(mode\)\)', sources['FileFd.cpp']):
        raise ValueError('TDLib open mode contract changed')
    if not re.search(r'::rename\(from\.c_str\(\),\s*to\.c_str\(\)\)', sources['path.cpp']):
        raise ValueError('TDLib rename contract changed')


def writer_contract(image, revision, env):
    metadata = json.loads(run(['docker', 'image', 'inspect', image], env).stdout)[0]
    if metadata['Config'].get('Labels', {}).get('io.tg-selfhost.bot-api-revision') != revision:
        raise ValueError('writer probe revision mismatch')
    def read(name):
        result = run(['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '256m',
                      '--pids-limit', '64', '--entrypoint', 'cat', image, '/usr/share/file-contract/' + name], env)
        return result.stdout
    td_revision = read('tdlib-revision').strip()
    if not re.fullmatch(r'[0-9a-f]{40}', td_revision):
        raise ValueError('invalid pinned TDLib revision')
    with urlopen(f'https://api.github.com/repos/tdlib/telegram-bot-api/git/trees/{revision}', timeout=30) as response:
        tree = json.load(response)
    if not any(item['path'] == 'td' and item['sha'] == td_revision and item['type'] == 'commit' for item in tree['tree']):
        raise ValueError('TDLib gitlink mismatch')
    sources = {name: read(name) for name in ('FileLoaderUtils.cpp', 'FileFd.cpp', 'path.cpp')}
    # Also compare archived probe source to the immutable upstream gitlink.
    for name, path in [('FileLoaderUtils.cpp', 'td/telegram/files/FileLoaderUtils.cpp'),
                       ('FileFd.cpp', 'tdutils/td/utils/port/FileFd.cpp'), ('path.cpp', 'tdutils/td/utils/port/path.cpp')]:
        with urlopen(f'https://raw.githubusercontent.com/tdlib/td/{td_revision}/{path}', timeout=30) as response:
            if response.read(8 * 1024 * 1024).decode('utf-8') != sources[name]:
                raise ValueError('writer probe source mismatch')
    validate_writer_sources(sources)
    return {'image_id': metadata['Id'], 'tdlib_revision': td_revision,
            'source_sha256': {name: hashlib.sha256(value.encode()).hexdigest() for name, value in sources.items()},
            'scope': 'downloaded media create/rename via pinned tdutils; no Telegram/session proof'}


def inspect(compose, service, env):
    cid = run(compose + ['ps', '-q', service], env).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{12,64}', cid):
        raise RuntimeError('fixture service unavailable')
    return json.loads(run(['docker', 'inspect', cid], env).stdout)[0]


def check_runtime_boundary(compose, env):
    result = {}
    for name in ('downloads', 'downloads-gateway', 'downloads-tls', 'botapi'):
        item = inspect(compose, name, env)
        if name in ('downloads', 'botapi') and item['HostConfig'].get('PortBindings'):
            raise ValueError('runtime backend published')
        if name == 'downloads':
            if item['Config']['User'] != '10001:101' or not item['HostConfig']['ReadonlyRootfs']:
                raise ValueError('runtime handler privileges')
            if any(m['RW'] for m in item['Mounts']):
                raise ValueError('runtime handler writable mount')
            if item['HostConfig'].get('Privileged') or item['HostConfig'].get('CapDrop') != ['ALL']:
                raise ValueError('runtime handler capabilities')
        if name in ('downloads-gateway', 'downloads-tls'):
            if any(m['Destination'].startswith((MEDIA, '/private-state', '/run/secrets')) for m in item['Mounts']):
                raise ValueError('runtime proxy storage')
            for bindings in item['NetworkSettings']['Ports'].values():
                if any(p['HostIp'] != '127.0.0.1' for p in bindings or []):
                    raise ValueError('runtime proxy exposure')
        metadata = json.loads(run(['docker', 'image', 'inspect', item['Image']], env).stdout)[0]
        result[name] = {'id': metadata['Id'], 'digests': metadata.get('RepoDigests', [])}
    return result


def exercise_state(project, env, report):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise NotRun('Linux required; verification deferred to CI/gates')
    compose = compose_prefix(project) + ['-f', str(FIXTURE / 'compose.yml')]
    try:
        run(compose + ['run', '--rm', '--no-deps', 'state-setup'], env)
        run(compose + ['up', '-d', 'state-mock', 'state-gateway'], env)
        gateway = inspect(compose, 'state-gateway', env)
        if (len(gateway['Mounts']) != 1 or gateway['Mounts'][0]['Destination'] != '/etc/nginx/conf.d/default.conf'
                or gateway['Mounts'][0]['RW']):
            raise ValueError('state gateway runtime mount mutation')
        result = run(compose + ['run', '--rm', '--no-deps', 'state-client'], env)
        lines = [line for line in result.stdout.splitlines() if line.startswith('{')]
        value = json.loads(lines[-1]) if lines else {}
        if value.get('state_isolation') != 'PASS' or value.get('cases') != len(STATE_CANARY_PATHS):
            raise ValueError('missing state canary evidence')
        return value
    finally:
        result = run(compose + ['down', '--volumes', '--remove-orphans'], env, check=False)
        report['cleanup'] = 'PASS' if result.returncode == 0 else 'FAIL'
        if result.returncode:
            raise RuntimeError('state fixture cleanup failed')


def exercise(project, env, report, botapi, downloads):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise NotRun('mandatory runtime fixture requires native Linux/amd64 CI')
    info = json.loads(run(['docker', 'info', '--format', '{{json .}}'], env).stdout)
    if info.get('OSType') != 'linux':
        raise NotRun('Linux Docker engine required')
    report['engine_version'] = info['ServerVersion']
    report['kernel'] = info['KernelVersion']
    report['compose_version'] = run(['docker', 'compose', 'version', '--short'], env).stdout.strip()
    report['images'] = {}
    for name, image in [('botapi', botapi), ('downloads', downloads)]:
        data = json.loads(run(['docker', 'image', 'inspect', image], env).stdout)[0]
        report['images'][name] = {'id': data['Id'], 'digests': data.get('RepoDigests', [])}
        if name == 'botapi':
            report['upstream_revision'] = data['Config'].get('Labels', {}).get('io.tg-selfhost.bot-api-revision', '')
    report['source_contract'] = source_contract(report['upstream_revision'])
    report['writer_contract'] = writer_contract(env['PERMISSIONS_TEST_IMAGE'], report['upstream_revision'], env)
    help_text = run(['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '256m',
                     '--pids-limit', '64', botapi, '--help'], env)
    if '--files-dir' not in help_text.stdout + help_text.stderr:
        raise ValueError('binary files-dir support missing')
    report['binary_cli'] = 'PASS'
    with tempfile.TemporaryDirectory(prefix='file-contract-') as directory:
        tmp = Path(directory)
        tmp.chmod(0o755)
        for name, filename in (('registry', 'downloads.config.json'), ('token', 'bot-token')):
            secret_dir = tmp / name
            secret_dir.mkdir()
            (secret_dir / filename).touch()
            env['FIXTURE_' + name.upper() + '_DIR'] = str(secret_dir)
        config = (ROOT / 'examples/files/nginx.downloads-tls.conf').read_text(encoding='utf-8')
        config = config.replace('127.0.0.1:18082', 'downloads-gateway:80').replace('downloads.example.com', 'downloads-tls')
        (tmp / 'tls.conf').write_text(config, encoding='utf-8')
        env['TLS_CONFIG'] = str(tmp / 'tls.conf')
        compose = compose_prefix(project) + ['-f', str(FIXTURE / 'compose.yml')]

        def once(service, *args):
            result = run(compose + ['run', '--rm', '--no-deps', service, *args], env, timeout=180)
            # Only structured synthetic summaries may enter the receipt.
            lines = [line for line in result.stdout.splitlines() if line.startswith('{')]
            if lines:
                return json.loads(lines[-1])
            if service in ('setup', 'writer', 'certs') or args == ('ready',):
                return {'status': 'PASS'}
            raise ValueError('missing structured mandatory fixture evidence')

        def resources():
            code = "import json,os; s=open('/proc/1/status').read(); print(json.dumps({'fds':len(os.listdir('/proc/1/fd')),'rss_kib':int(next(x.split()[1] for x in s.splitlines() if x.startswith('VmRSS:')))}))"
            return json.loads(run(compose + ['exec', '-T', 'downloads', 'python', '-c', code], env).stdout)

        try:
            once('setup')
            once('writer')
            report['writer_offline'] = once('permissions-writer')
            if report['writer_offline'].get('tdlib_create_move') != 'PASS':
                raise ValueError('missing offline TDLib create/move evidence')
            once('setup', 'decorate')
            once('certs')
            run(compose + ['up', '-d', 'entrypoint'], env)
            for _ in range(30):
                command = "test \"$(awk '/^Uid:/ {print $3}' /proc/1/status)\" = 101 && test \"$(stat -c %u:%g /var/lib/telegram-bot-api-files)\" = 101:101 && test \"$(stat -c %a /var/lib/telegram-bot-api-files)\" = 770 && test -f /var/lib/telegram-bot-api/synthetic.log && test ! -e /var/lib/telegram-bot-api-files/synthetic.log"
                ready = run(compose + ['exec', '-T', 'entrypoint', 'sh', '-ec', command], env, check=False)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('real entrypoint split-storage contract failed')
            report['real_entrypoint'] = 'PASS'
            run(compose + ['stop', 'entrypoint'], env)
            run(compose + ['up', '-d', 'botapi', 'downloads', 'downloads-gateway', 'downloads-tls'], env, timeout=180)
            # Readiness is not a test retry: wait for nginx TLS listener before running cases once.
            for _ in range(30):
                ready = run(compose + ['exec', '-T', 'downloads', 'python', '-c',
                            "import socket;s=socket.create_connection(('downloads-gateway',80),1);s.close()"], env, check=False)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('fixture readiness deadline')
            report['runtime_images'] = check_runtime_boundary(compose, env)
            once('client', 'ready')
            report['local'] = once('reader')
            report['tdlib_permissions'] = 'PASS'
            before = resources()
            report['remote'] = once('client')
            report['auth_before_io'] = once('probe', 'auth_counters')
            report['overload'] = once('probe')
            time.sleep(1)
            after = resources()
            if after['fds'] > before['fds'] + 4 or after['rss_kib'] > 128 * 1024:
                raise ValueError('stream resource/FD bound violated')
            report['resources'] = {'before': before, 'after': after, 'status': 'PASS'}
            report['mount_boundary'] = once('mountcheck')
            # Restart releases old pinned descriptors and loads the replaced registry.
            run(compose + ['stop', 'downloads'], env)
            report['rotation_setup'] = once('setup', 'rotate')
            run(compose + ['start', 'downloads'], env)
            once('client', 'ready')
            report['rotation'] = once('client', 'remote-rotated')
            run(compose + ['stop', 'downloads', 'botapi'], env)
            report['upgrade_rollback'] = once('setup', 'rollback')
            logs = run(compose + ['logs', '--no-color', 'downloads', 'downloads-gateway', 'downloads-tls'], env).stdout
            if any(value in logs for value in ('SYNTHETIC_A', 'SYNTHETIC_B', 'A' * 40, 'B' * 40, 'C' * 40, 'CANARY', MEDIA)):
                raise ValueError('sensitive fixture data in service logs')
            report['log_privacy'] = 'PASS'
        finally:
            # Only this project, no global prune or production paths.
            result = run(compose + ['down', '--volumes', '--remove-orphans'], env, check=False)
            report['cleanup'] = 'PASS' if result.returncode == 0 else 'FAIL'
            if result.returncode:
                raise RuntimeError('fixture cleanup failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--botapi-image', default='botapi-candidate:check')
    parser.add_argument('--downloads-image', default='downloads-candidate:check')
    parser.add_argument('--permissions-image', default='permissions-candidate:check')
    parser.add_argument('--models-only', action='store_true')
    parser.add_argument('--state-isolation-only', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    report = {'status': 'NOTRUN', 'models': 'NOTRUN', 'runtime': 'NOTRUN', 'cleanup': 'NOTRUN',
              'publish': 'NOTRUN', 'production': 'NOTRUN', 'tdlib_permissions': 'UNKNOWN',
              'mode': 'state-isolation-only' if args.state_isolation_only else 'models-only' if args.models_only else 'full'}
    code = 1
    try:
        if not shutil.which('docker'):
            raise NotRun('Docker CLI required')
        env = environment(args.botapi_image, args.downloads_image, args.permissions_image)
        report['source_sha256'] = source_hashes()
        report['commit'] = run(['git', '-c', f'safe.directory={ROOT.as_posix()}', 'rev-parse', 'HEAD'], env).stdout.strip()
        report['tracked_worktree_dirty'] = run(['git', '-c', f'safe.directory={ROOT.as_posix()}',
                                                'diff', '--quiet'], env, check=False).returncode != 0
        project = 'filecontract' + uuid.uuid4().hex[:12]
        report['model_cases'], report['topology_sha256'] = check_models(project, env, args.state_isolation_only)
        report['models'] = 'PASS'
        if args.state_isolation_only:
            report['canary_paths'] = list(STATE_CANARY_PATHS)
            if args.models_only:
                report['runtime_reason'] = 'models-only requested'
            elif platform.system() != 'Linux':
                report['runtime_reason'] = 'Linux required; verification deferred to CI/gates'
            else:
                report['state_isolation'] = exercise_state(project, env, report)
                report['runtime'] = 'PASS'
        elif not args.models_only:
            report['state_before'] = exercise_state(project, env, report)
            exercise(project, env, report, args.botapi_image, args.downloads_image)
            report['state_after'] = exercise_state(project, env, report)
            report['runtime'] = 'PASS'
            if report['tdlib_permissions'] != 'PASS':
                raise NotRun('TDLib create/move evidence missing; verification deferred to CI/gates')
        report['status'] = 'PASS'
        code = 0
    except NotRun as exc:
        report.update(status='NOTRUN', reason=str(exc))
        code = 2
    except Exception as exc:
        report.update(status='FAIL', error=type(exc).__name__)
    output = json.dumps(report, indent=2, sort_keys=True)
    print(output)
    if args.report:
        args.report.write_text(output + '\n', encoding='utf-8')
    return code


if __name__ == '__main__':
    sys.exit(main())
