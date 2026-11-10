"""Validate captured Alpine package inventories without executing the image."""
import re
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import os


def parse_installed(text):
    if not text.strip():
        raise ValueError("empty apk inventory")
    packages = []
    names = set()
    for stanza in re.split(r"\n\s*\n", text.strip()):
        fields = {}
        for line in stanza.splitlines():
            if len(line) < 2 or line[1] != ':':
                raise ValueError("malformed apk inventory")
            key, value = line[0], line[2:]
            if key in ('P', 'V', 'A', 'o'):
                if key in fields or not value:
                    raise ValueError("duplicate or empty apk field")
                fields[key] = value
        if not {'P', 'V', 'A'} <= fields.keys():
            raise ValueError("missing apk package fields")
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.-]*', fields['P']):
            raise ValueError('invalid apk package name')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.~-]*-r\d+', fields['V']):
            raise ValueError("apk package revision missing")
        if fields['P'] in names:
            raise ValueError("duplicate apk package")
        names.add(fields['P'])
        packages.append({'name': fields['P'], 'version': fields['V'],
                         'arch': fields['A'], 'origin': fields.get('o', fields['P'])})
    return sorted(packages, key=lambda item: item['name'])


def validate_packages(packages, required, architecture):
    by_name = {package['name']: package for package in packages}
    missing = set(required) - by_name.keys()
    if missing:
        raise ValueError('missing packages: ' + ', '.join(sorted(missing)))
    if any(package['arch'] not in (architecture, 'noarch') for package in packages):
        raise ValueError('unexpected package architecture')


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def library_capture_name(path):
    if not path.startswith(('/lib/', '/usr/lib/')) or '..' in Path(path).parts:
        raise ValueError('Invalid runtime library path')
    return hashlib.sha256(path.encode()).hexdigest()


def extract_image(image, directory):
    """Copy evidence and binary from a container owned by this invocation."""
    container = docker('create', image)
    if not re.fullmatch(r'[0-9a-f]{12,64}', container):
        raise ValueError('invalid container identifier')
    try:
        subprocess.run(['docker', 'cp', f'{container}:/usr/share/tg-selfhost-botapi/.',
                        str(directory)], check=True)
        subprocess.run(['docker', 'cp', f'{container}:/usr/local/bin/telegram-bot-api',
                        str(directory / 'telegram-bot-api')], check=True)
        subprocess.run(['docker', 'cp', f'{container}:/lib/apk/db/installed',
                        str(directory / 'actual-installed')], check=True)
        libraries = directory / 'runtime-libraries'
        libraries.mkdir(exist_ok=True)
        for record in json.loads((directory / 'build/dynamic-owners.json').read_text()):
            name = library_capture_name(record['path'])
            subprocess.run(['docker', 'cp', '-L', f"{container}:{record['path']}",
                            str(libraries / name)], check=True)
    finally:
        subprocess.run(['docker', 'rm', '-f', container], check=True,
                       stdout=subprocess.DEVNULL)


def receipt(image, inputs, directory, mode='build', candidate_digest=None):
    inspect = json.loads(docker('image', 'inspect', image))[0]
    labels = inspect['Config'].get('Labels') or {}
    expected = {'io.tg-selfhost.build-key': str(inputs['build_key']),
                'io.tg-selfhost.bot-api-revision': str(inputs['bot_api_revision']),
                'io.tg-selfhost.apk-refresh-id': str(inputs['apk_refresh_id']),
                'io.tg-selfhost.apk-policy-version': str(inputs['policy_version']),
                'io.tg-selfhost.apk-refresh-window': str(inputs['apk_refresh_window']),
                'io.tg-selfhost.apk-refresh-generation': str(inputs['generation']),
                'io.tg-selfhost.platform': str(inputs['platform'])}
    if any(labels.get(k) != v for k, v in expected.items()):
        raise ValueError('image labels do not match resolved inputs')
    if inputs['platform'] != 'linux/amd64' or inspect['Os'] != 'linux' or inspect['Architecture'] != 'amd64':
        raise ValueError('unexpected image platform')
    extract_image(image, directory)
    result = {}
    hashes = {}
    for stage, required in [('build', {'alpine-sdk', 'linux-headers', 'git', 'zlib-dev', 'openssl-dev', 'gperf', 'cmake'}),
                            ('runtime', {'openssl', 'libstdc++'})]:
        path = directory / stage
        if (path / 'schema').read_text().strip() != '1' or (path / 'arch').read_text().strip() != 'x86_64':
            raise ValueError('unsupported capture schema or architecture')
        if (path / 'refresh-id').read_text().strip() != inputs['apk_refresh_id']:
            raise ValueError('inventory refresh does not match inputs')
        packages = parse_installed((path / 'installed').read_text())
        validate_packages(packages, required, 'x86_64')
        repos = (path / 'repositories').read_text().strip()
        version = (path / 'apk-version').read_text().strip()
        repositories = [line.strip() for line in repos.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if (not repositories or any(not re.fullmatch(r'https://[A-Za-z0-9./_-]+/alpine/v3\.22/(main|community)/?', repo) for repo in repositories)):
            raise ValueError('repositories must use stable Alpine 3.22 over HTTPS')
        if not version:
            raise ValueError('missing repositories or apk version')
        if (not (path / 'world').read_text().strip()
                or not re.fullmatch(r'3\.22\.\d+', (path / 'alpine-release').read_text().strip())):
            raise ValueError('missing world or unexpected Alpine release')
        result[stage] = {'repositories': repos, 'apk_version': version, 'packages': packages}
        for file in path.iterdir():
            if file.is_file():
                hashes[f'{stage}/{file.name}'] = hashlib.sha256(file.read_bytes()).hexdigest()
    if (directory / 'actual-installed').read_bytes() != (directory / 'runtime/installed').read_bytes():
        raise ValueError('runtime inventory differs from final installed database')
    binary_hash = hashlib.sha256((directory / 'telegram-bot-api').read_bytes()).hexdigest()
    if (directory / 'build' / 'binary.sha256').read_text().split()[0] != binary_hash:
        raise ValueError('binary hash does not match build evidence')
    links = (directory / 'build' / 'link-commands.txt').read_text().strip()
    dynamic = (directory / 'build' / 'dynamic.txt').read_text().strip()
    static = (directory / 'build' / 'static-archives.txt').read_text().strip()
    if not links or '(NEEDED)' not in dynamic or not static:
        raise ValueError('missing link evidence')
    record = json.loads((directory / 'build/compile-receipt.json').read_text())
    expected_compile = dict(BOT_API_REVISION=inputs['bot_api_revision'], ALPINE_IMAGE=inputs['alpine_image'],
                            BUILD_FINGERPRINT=inputs['build_key'], APK_REFRESH_ID=inputs['apk_refresh_id'],
                            TARGETPLATFORM=inputs['platform'])
    required_hashes = {'schema', 'arch', 'refresh-id', 'installed', 'repositories', 'apk-version',
                       'binary.sha256', 'link-commands.txt', 'dynamic.txt', 'dynamic-owners.json', 'static-archives.txt', 'world', 'alpine-release', 'pre-strip.sha256', 'link-map.txt', 'build-facts.json'}
    if (record.get('schema') != 1 or record.get('inputs') != expected_compile
            or record.get('binary_sha256') != binary_hash or not record.get('source_submodules')
            or set(record.get('hashes', {})) != required_hashes):
        raise ValueError('invalid original compile record')
    for name, expected_hash in record['hashes'].items():
        if hashes['build/' + name] != expected_hash:
            raise ValueError('compile evidence hash mismatch: ' + name)
    pre_strip = (directory / 'build/pre-strip.sha256').read_text().split()[0]
    facts = json.loads((directory / 'build/build-facts.json').read_text())
    link_map = (directory / 'build/link-map.txt').read_text()
    if (not re.fullmatch('[0-9a-f]{64}', pre_strip) or not link_map.strip()
            or facts.get('source_revision') != inputs['bot_api_revision']
            or any(not facts.get(k) for k in ('compiler', 'cmake', 'linker', 'cmake_cache'))):
        raise ValueError('Missing compiler, map or pre-strip evidence')
    archives = json.loads(static)
    package_owners = {p['name'] + '-' + p['version'] for p in result['build']['packages']}
    runtime_owners = {p['name'] + '-' + p['version'] for p in result['runtime']['packages']}
    dynamic_owners = json.loads((directory / 'build/dynamic-owners.json').read_text())
    if not isinstance(dynamic_owners, list) or not dynamic_owners:
        raise ValueError('missing dynamic ownership')
    for library in dynamic_owners:
        if (set(library) != {'path', 'sha256', 'owner'} or library['owner'] not in package_owners
                or library['owner'] not in runtime_owners
                or not library['path'].startswith('/') or not re.fullmatch('[0-9a-f]{64}', library['sha256'])):
            raise ValueError('invalid dynamic ownership')
        actual = directory / 'runtime-libraries' / library_capture_name(library['path'])
        if hashlib.sha256(actual.read_bytes()).hexdigest() != library['sha256']:
            raise ValueError('Final runtime library differs from resolved build library')
    if not isinstance(archives, list) or not archives:
        raise ValueError('missing static archives')
    for archive in archives:
        if (set(archive) != {'path', 'sha256', 'owner'} or not re.fullmatch('[0-9a-f]{64}', archive['sha256'])
                or not archive['path'].endswith('.a') or not archive['path'].startswith('/')):
            raise ValueError('invalid static archive record')
        if archive['owner'].startswith('source:'):
            if archive['owner'] != 'source:' + inputs['bot_api_revision'] or not archive['path'].startswith('/usr/src/telegram-bot-api/'):
                raise ValueError('invalid source library linkage')
        elif archive['owner'] not in package_owners:
            raise ValueError('static archive owner is absent from build inventory')
        if archive['path'] not in links or archive['path'] not in link_map:
            # Build-tree archives may appear relative to the final command/map cwd.
            relative = archive['path'].removeprefix('/usr/src/telegram-bot-api/build/')
            if relative not in links or relative not in link_map:
                raise ValueError('Archive is not tied to the final target command and map')
    linkage = {}
    for family, prefixes in {'zlib': ('libz.',), 'OpenSSL': ('libssl.', 'libcrypto.'),
                             'libstdc++': ('libstdc++.',)}.items():
        modes = []
        if any(Path(p['path']).name.startswith(prefixes) for p in archives):
            modes.append('static')
        if any(Path(p['path']).name.startswith(prefixes) for p in dynamic_owners):
            modes.append('dynamic')
        linkage[family] = '+'.join(modes) if modes else 'not-linked'
    if mode not in ('build', 'reuse') or (candidate_digest is not None and not re.fullmatch('sha256:[0-9a-f]{64}', candidate_digest)):
        raise ValueError('invalid verification identity')
    return {'schema': 2, 'inputs': inputs, 'image_config_id': inspect['Id'],
            'binary_sha256': binary_hash, 'inventories': result,
            'link_commands': links, 'dynamic': dynamic,
            'static_ownership': archives, 'dynamic_ownership': dynamic_owners,
            'original_compile_record': record, 'evidence_sha256': hashes,
            'candidate_digest': candidate_digest, 'mode': mode,
            'pre_strip_sha256': pre_strip, 'build_facts': facts,
            'important_linkage': linkage,
            'scanner': {'status': 'NOTRUN'},
            'run': os.environ.get('GITHUB_RUN_ID'), 'attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
            'gates': {'metadata': 'PASS', 'smoke': 'NOTRUN', 'apk_refresh': 'NOTRUN'}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=('build', 'reuse'), default='build')
    parser.add_argument('--candidate-digest')
    args = parser.parse_args()
    inputs = json.loads(Path(args.inputs).read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as temp:
        result = receipt(args.image, inputs, Path(temp), args.mode, args.candidate_digest)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
