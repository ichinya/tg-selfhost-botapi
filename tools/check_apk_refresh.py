"""Exercise both real apk branches with warm cache and unchanged base/source."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from image_inputs import ROOT, refresh_id, validate_lock


def run(*args):
    return subprocess.check_output(args, timeout=400)


def check(inputs):
    validate_lock({'schema': 1, 'inputs': inputs, 'selected_release': None})
    refreshed = refresh_id(inputs['apk_policy_version'], inputs['apk_refresh_window'], inputs['apk_refresh_generation'] + 1)
    prefix = 'botapi-apk-check-' + uuid.uuid4().hex
    tags = []
    evidence = {}
    try:
        for stage in ('build', 'runtime', 'observer'):
            original = None
            for number, identity in enumerate((inputs['apk_refresh_id'], refreshed)):
                tag = f'{prefix}:{stage}-{number}'
                tags.append(tag)
                # The second build uses the same builder cache; do not pass --no-cache.
                target = (['--file', 'tools/observability/Dockerfile', '--build-arg', 'OBSERVER_BASE=' + inputs['observer_base'],
                           '--build-arg', 'BUILD_FINGERPRINT=' + inputs['build_key']]
                          if stage == 'observer' else ['--target', stage + '-deps', '--build-arg', 'ALPINE_IMAGE=' + inputs['alpine_image']])
                subprocess.run(['docker', 'build', *target, '--build-arg', 'APK_REFRESH_ID=' + identity,
                    '--tag', tag, str(ROOT)], check=True, timeout=400)
                config = run('docker', 'image', 'inspect', '--format', '{{.Id}}', tag).decode().strip()
                path = '/usr/share/tg-selfhost-botapi/' + stage + '/'
                actual = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', config,
                             path + ('refresh-id' if stage == 'observer' else stage + '-apk.txt'))
                if actual.decode().splitlines()[-1] != identity:
                    raise ValueError('Stale warm-cache apk layer')
                installed = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', config, path + 'installed')
                evidence[f'{stage}-{number}'] = {'config_id': config, 'refresh_id': identity,
                    'installed_sha256': hashlib.sha256(installed).hexdigest()}
                if original is None:
                    original = (config, installed)
                else:
                    if original[0] == config or run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', original[0], path + 'installed') != original[1]:
                        raise ValueError('Refresh reused stale config or changed original evidence')
        return {'warm_cache': 'PASS', 'stages': evidence}
    finally:
        if tags:
            try:
                result = subprocess.run(['docker', 'image', 'rm', *tags], check=False, timeout=60)
                if result.returncode:
                    print('Warning: failed to remove apk-check images', file=sys.stderr)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f'Warning: failed to remove apk-check images: {exc}', file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(check(json.loads(args.inputs.read_text())), sort_keys=True) + '\n', encoding='utf8')
