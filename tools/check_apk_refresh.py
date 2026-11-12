"""Explicit signed A/A/control/B integration gate. Never invoked by unittest discovery."""
import argparse
from contextlib import contextmanager
import os
import shlex
import functools
import hashlib
import ipaddress
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

from image_inputs import ROOT, recipe_files, build_key
from image_metadata import parse_installed


FIXTURE = ROOT / 'tools/apk_refresh_fixture'


def verify_fixture():
    manifest = {}
    for line in (FIXTURE / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name not in ('fixture.c', 'consumer.c', 'LICENSE', 'APKBUILD.in', 'package.sh'):
            raise ValueError('Unexpected fixture source')
        if hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Fixture source hash mismatch')
        manifest[name] = digest
    if len(manifest) != 5:
        raise ValueError('Incomplete fixture source manifest')
    return manifest


def transform(recipe, url):
    """Only isolated context: install v1 before keyed RUN; never add it inside that RUN."""
    if recipe.count(' && apk upgrade --no-cache') != 2 or recipe.count('sh /tmp/capture_apk_metadata.sh') != 2:
        raise ValueError('Production installation structure changed')
    result = recipe
    for stage in ('build-deps', 'runtime-deps'):
        marker = ' AS ' + stage + '\nARG APK_REFRESH_ID'
        if result.count(marker) != 1:
            raise ValueError('Missing exact production deps stage')
        before = (' AS ' + stage + '\n'
                  'COPY fixture-key.pub /etc/apk/keys/issue23.rsa.pub\n'
                  f'RUN printf \'%s\\n\' \'{url}\' >> /etc/apk/repositories && apk add --no-cache issue23-fixture\n'
                  'ARG APK_REFRESH_ID')
        result = result.replace(marker, before)
    build_consumer = '''
COPY fixture-consumer.c /tmp/issue23.c
RUN cc /tmp/issue23.c -lissue23 -o /tmp/issue23-dynamic \\
 && cc -static /tmp/issue23.c /usr/lib/libissue23.a -Wl,-Map=/tmp/issue23.map -o /tmp/issue23-static \\
 && /tmp/issue23-dynamic > /usr/share/tg-selfhost-botapi/build/fixture-dynamic \\
 && /tmp/issue23-static > /usr/share/tg-selfhost-botapi/build/fixture-static \\
 && readelf -d /tmp/issue23-dynamic > /usr/share/tg-selfhost-botapi/build/fixture-needed \\
 && cp /tmp/issue23.map /usr/share/tg-selfhost-botapi/build/fixture-link-map \\
 && sha256sum /usr/lib/libissue23.a /usr/lib/libissue23.so.1 /tmp/issue23-static > /usr/share/tg-selfhost-botapi/build/fixture-hashes
'''
    runtime_consumer = '''
COPY --from=build-deps /tmp/issue23-dynamic /tmp/issue23-dynamic
RUN /tmp/issue23-dynamic > /usr/share/tg-selfhost-botapi/runtime/fixture-dynamic \\
 && sha256sum /usr/lib/libissue23.so.1 > /usr/share/tg-selfhost-botapi/runtime/fixture-hashes
'''
    result = result.replace('\nFROM build-deps AS source', build_consumer + '\nFROM build-deps AS source')
    result = result.replace('\nFROM runtime-deps AS runtime', runtime_consumer + '\nFROM runtime-deps AS runtime')
    return result



def remove_refresh_consumption(recipe, stage, frozen):
    marker = ' AS ' + stage + '\n'
    start = recipe.index(marker) + len(marker)
    end = recipe.find('\nFROM ', start)
    if end < 0:
        end = len(recipe)
    section = recipe[start:end]
    if 'ARG APK_REFRESH_ID\n' not in section or '$APK_REFRESH_ID' not in section:
        raise ValueError('Cannot construct refresh negative control')
    section = section.replace('ARG APK_REFRESH_ID\n', '')
    section = section.replace('${APK_REFRESH_ID:?Run tools/image_inputs.py --build-env-out .env.build first}', frozen)
    section = section.replace('$APK_REFRESH_ID', frozen)
    return recipe[:start] + section + recipe[end:]


def installation_cached(log, stage):
    identifiers = re.findall(r'^#(\d+) \[' + re.escape(stage) + r' \d+/\d+\] RUN .*capture_apk_metadata\.sh', log, re.M)
    if len(set(identifiers)) != 1:
        raise ValueError('Installation RUN cannot be identified in BuildKit plain log: ' + stage)
    number = identifiers[0]
    if re.search(r'^#' + number + r' CACHED\s*$', log, re.M):
        return True
    if re.search(r'^#' + number + r' DONE(?: |$)', log, re.M):
        return False
    raise ValueError('Installation RUN completion UNKNOWN')


def command(args, log=None, timeout=900):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if log:
        Path(log).write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Integration command failed: {shlex.join(args)}; exit code: {result.returncode}; log: {log or "not saved"}')
    return result.stdout


@contextmanager
def temporary_workspace(prefix):
    workspace = tempfile.TemporaryDirectory(prefix=prefix)
    primary = None
    try:
        yield workspace.name
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            workspace.cleanup()
        except Exception as error:
            if primary is None:
                raise
            primary.add_note(f'Temporary workspace cleanup failed: {type(error).__name__}: {error}')


def builder_gateway(namespace):
    networks = json.loads(command(['docker', 'inspect', '--format',
                                   '{{json .NetworkSettings.Networks}}',
                                   'buildx_buildkit_' + namespace + '0']))
    gateways = {settings.get('Gateway') for settings in networks.values() if settings.get('Gateway')}
    if len(gateways) != 1:
        raise ValueError('Builder network gateway is ambiguous or missing')
    gateway = gateways.pop()
    if ipaddress.ip_address(gateway).version != 4:
        raise ValueError('Builder network gateway is not IPv4')
    return gateway


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def extract(image, directory):
    container = command(['docker', 'create', image]).strip()
    if not re.fullmatch('[0-9a-f]{12,64}', container):
        raise ValueError('Invalid owned container')
    try:
        command(['docker', 'cp', container + ':/usr/share/tg-selfhost-botapi/.', str(directory)])
    finally:
        command(['docker', 'rm', '-f', container])


def integration(inputs, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = verify_fixture()
    if inputs['platform'] != 'linux/amd64':
        raise ValueError('Fixture gate currently supports linux/amd64 only')
    recipe = (ROOT / 'Dockerfile').read_text()
    files = recipe_files()
    identity = {k: v for k, v in inputs.items() if k != 'build_key'}
    if build_key(identity, files) != inputs['build_key']:
        raise ValueError('Snapshot does not match exact candidate recipe')
    namespace = 'issue23-' + uuid.uuid4().hex[:12]
    images, records = [], []
    builder_created = False
    with temporary_workspace(namespace) as folder:
        temp = Path(folder)
        packaging, context, served = temp / 'packaging', temp / 'context', temp / 'served'
        packaging.mkdir(); context.mkdir(); served.mkdir()
        shutil.copytree(FIXTURE, packaging / 'source')
        server = ThreadingHTTPServer(('0.0.0.0', 0), functools.partial(QuietHandler, directory=str(served)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            command(['docker', 'run', '--rm', '--cpus', '2', '--memory', '3g',
                     '-e', 'HOST_UID=' + str(os.getuid() if hasattr(os, 'getuid') else 0),
                     '-e', 'HOST_GID=' + str(os.getgid() if hasattr(os, 'getgid') else 0),
                     '-v', str(packaging) + ':/work',
                     inputs['alpine_image'], 'sh', '/work/source/package.sh'], output.parent / 'fixture-packaging.log')
            shutil.copytree(packaging / 'repo-v1', served / 'current')
            for name in ('tools/capture_apk_metadata.sh', 'tools/capture_link_metadata.py'):
                destination = context / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, destination)
            shutil.copy2(packaging / 'issue23.rsa.pub', context / 'fixture-key.pub')
            shutil.copy2(FIXTURE / 'consumer.c', context / 'fixture-consumer.c')
            # Source/entrypoint stages are not built, but keep exact recipe context files available.
            for name in ('docker-entrypoint.sh', 'patches/webhook-user-agent.patch'):
                destination = context / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, destination)
            url = 'http://host.docker.internal:' + str(server.server_port) + '/current'
            transformed = transform(recipe, url)
            (context / 'Dockerfile').write_text(transformed, encoding='utf-8', newline='\n')
            context_hash = hashlib.sha256(transformed.encode()).hexdigest()
            context_files = {str(p.relative_to(context)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in context.rglob('*') if p.is_file()}
            config = temp / 'buildkitd.toml'
            config.write_text('[worker.oci]\n  max-parallelism = 2\n')
            builder_created = True
            command(['docker', 'buildx', 'create', '--name', namespace, '--driver', 'docker-container',
                     '--driver-opt', 'memory=3g', '--driver-opt', 'cpu-period=100000', '--driver-opt', 'cpu-quota=200000',
                     '--buildkitd-config', str(config), '--bootstrap'], output.parent / 'fixture-builder.log')
            host_mapping = 'host.docker.internal:' + builder_gateway(namespace)
            previous_cache = {}
            next_identity = {**identity, 'generation': identity['generation'] + 1}
            next_identity['apk_refresh_id'] = f"v{identity['policy_version']}-{identity['apk_refresh_window']}-g{next_identity['generation']}"
            if build_key(next_identity, files) == inputs['build_key']:
                raise ValueError('Refresh did not change build key')
            for phase, refresh, expected, cached in [('A', inputs['apk_refresh_id'], '1', False),
                                                     ('A-repeat', inputs['apk_refresh_id'], '1', True),
                                                     ('control', inputs['apk_refresh_id'], '1', True),
                                                     ('B', next_identity['apk_refresh_id'], '2', False)]:
                if phase == 'control':
                    shutil.copytree(packaging / 'repo-v2', served / 'current', dirs_exist_ok=True)
                actual_context = {str(p.relative_to(context)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in context.rglob('*') if p.is_file()}
                if actual_context != context_files:
                    raise ValueError('Fixture recipe changed between phases')
                for target, stage in [('build-deps', 'build'), ('runtime-deps', 'runtime')]:
                    tag = namespace + ':' + phase.lower() + '-' + target
                    images.append(tag)
                    cache = temp / (phase + '-' + target + '-cache')
                    args = ['docker', 'buildx', 'build', '--builder', namespace, '--progress', 'plain', '--load',
                            '--platform', inputs['platform'], '--add-host', host_mapping,
                            '--target', target, '--tag', tag, '--cache-to', 'type=local,dest=' + str(cache) + ',mode=max',
                            '--build-arg', 'ALPINE_IMAGE=' + inputs['alpine_image'],
                            '--build-arg', 'BOT_API_REVISION=' + inputs['bot_api_revision'], '--build-arg', 'APK_REFRESH_ID=' + refresh]
                    if target in previous_cache:
                        args += ['--cache-from', 'type=local,src=' + str(previous_cache[target])]
                    args.append(str(context))
                    log_path = output.parent / (phase + '-' + target + '.log')
                    log = command(args, log_path, timeout=1200)
                    previous_cache[target] = cache
                    if installation_cached(log, target) != cached:
                        raise ValueError('Unexpected installation cache state: ' + phase + '/' + target)
                    evidence = output.parent / (phase + '-' + target)
                    evidence.mkdir()
                    extract(tag, evidence)
                    inventory = parse_installed((evidence / stage / 'installed').read_text())
                    if (evidence / stage / 'refresh-id').read_text().strip() != refresh:
                        raise ValueError('Inventory is from a different refresh')
                    fixture = next(p for p in inventory if p['name'] == 'issue23-fixture')
                    if fixture['version'] != expected + '-r0':
                        raise ValueError('Fixture upgrade did not reach production installation layer')
                    if (evidence / stage / 'fixture-dynamic').read_text().strip() != expected:
                        raise ValueError('Dynamic consumer uses old library')
                    if stage == 'build' and (evidence / stage / 'fixture-static').read_text().strip() != expected:
                        raise ValueError('Static consumer was not recompiled')
                    if stage == 'build':
                        if ('libissue23.so.1' not in (evidence / stage / 'fixture-needed').read_text()
                                or 'libissue23.a' not in (evidence / stage / 'fixture-link-map').read_text()):
                            raise ValueError('Fixture linkage effect is not established')
                    records.append({'phase': phase, 'target': target, 'refresh_id': refresh, 'version': fixture['version'],
                                    'cached': cached, 'hashes': (evidence / stage / 'fixture-hashes').read_text()})
            negative_controls = []
            for target in ('build-deps', 'runtime-deps'):
                original = next(r for r in records if r['phase'] == 'A' and r['target'] == target)
                updated = next(r for r in records if r['phase'] == 'B' and r['target'] == target)
                old_hashes = dict(line.split(None, 1)[::-1] for line in original['hashes'].splitlines())
                new_hashes = dict(line.split(None, 1)[::-1] for line in updated['hashes'].splitlines())
                if old_hashes.keys() != new_hashes.keys() or any(old_hashes[k] == new_hashes[k] for k in old_hashes):
                    raise ValueError('Refresh did not change all linked fixture inputs/consumers')
            for stage in ('build-deps', 'runtime-deps'):
                broken = remove_refresh_consumption(transformed, stage, inputs['apk_refresh_id'])
                # A separate, fixed context per negative variant: never mutate the A/B context.
                broken_context = temp / ('negative-' + stage)
                shutil.copytree(context, broken_context)
                (broken_context / 'Dockerfile').write_text(broken, encoding='utf-8', newline='\n')
                tag = namespace + ':negative-' + stage
                images.append(tag)
                versions = []
                for phase, refresh in [('A', inputs['apk_refresh_id']), ('B', next_identity['apk_refresh_id'])]:
                    # A sees v1; B sees v2 at the same URL. Without refresh it must stay v1.
                    shutil.copytree(packaging / ('repo-v1' if phase == 'A' else 'repo-v2'), served / 'current', dirs_exist_ok=True)
                    log = command(['docker', 'buildx', 'build', '--builder', namespace, '--progress', 'plain', '--load',
                        '--platform', inputs['platform'], '--add-host', host_mapping,
                        '--target', stage, '--tag', tag, '--build-arg', 'ALPINE_IMAGE=' + inputs['alpine_image'],
                        '--build-arg', 'APK_REFRESH_ID=' + refresh, str(broken_context)],
                        output.parent / ('negative-' + stage + '-' + phase + '.log'), timeout=1200)
                    if phase == 'B' and not installation_cached(log, stage):
                        raise ValueError('Negative control unexpectedly consumed refresh')
                    directory = output.parent / ('negative-' + stage + '-' + phase)
                    directory.mkdir()
                    extract(tag, directory)
                    kind = 'build' if stage == 'build-deps' else 'runtime'
                    inventory = parse_installed((directory / kind / 'installed').read_text())
                    version = next(p['version'] for p in inventory if p['name'] == 'issue23-fixture')
                    versions.append(version)
                    if (directory / kind / 'fixture-dynamic').read_text().strip() != '1':
                        raise ValueError('Negative control did not retain the old dynamic input')
                    if kind == 'build' and (directory / kind / 'fixture-static').read_text().strip() != '1':
                        raise ValueError('Negative control did not retain the old static input')
                if versions != ['1-r0', '1-r0']:
                    raise ValueError('Negative control did not expose stale installation evidence')
                negative_controls.append({'stage': stage, 'versions': versions, 'detected': True, 'status': 'EXPECTED_REJECTION'})
            result = {'schema': 1, 'status': 'PASS', 'build_key': inputs['build_key'], 'inputs': inputs,
                      'next_build_key': build_key(next_identity, files), 'recipe_sha256': hashlib.sha256(recipe.encode()).hexdigest(),
                      'fixture_recipe_sha256': context_hash, 'context_sha256': context_files, 'fixture_sources': manifest, 'records': records,
                      'repository_url': url, 'negative_controls': negative_controls}
            output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        finally:
            primary = sys.exception()
            cleanup_errors = []
            for cleanup in (
                lambda: (server.shutdown(), server.server_close(), thread.join(timeout=5)),
                lambda: command(['docker', 'image', 'rm', '-f', *images]) if images else None,
                lambda: command(['docker', 'buildx', 'rm', namespace]) if builder_created else None,
            ):
                try:
                    cleanup()
                except Exception as error:
                    cleanup_errors.append(error)
            if cleanup_errors:
                if primary is None:
                    primary = cleanup_errors.pop(0)
                    for error in cleanup_errors:
                        primary.add_note(f'Cleanup failed: {type(error).__name__}: {error}')
                    raise primary
                for error in cleanup_errors:
                    primary.add_note(f'Cleanup failed: {type(error).__name__}: {error}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    try:
        integration(json.loads(Path(args.inputs).read_text()), output)
    except Exception as error:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'schema': 1, 'status': 'FAIL', 'error_type': type(error).__name__,
                                     'error': str(error), 'cleanup_errors': getattr(error, '__notes__', [])}) + '\n')
        raise


if __name__ == '__main__':
    main()
