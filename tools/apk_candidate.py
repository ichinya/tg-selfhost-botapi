"""Issue #23 orchestration. Registry writes are explicit CI-only phases."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from image_inputs import ROOT, RECIPE, build_key, check_generation, read_policy
from image_metadata import receipt as metadata_receipt


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=1800).strip()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def registry_digest(image):
    try:
        value = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', image, '--format', '{{json .Manifest}}'))['digest']
    except subprocess.CalledProcessError as error:
        message = (error.stderr or '').lower()
        if ('manifest unknown' in message or 'manifest_unknown' in message) and not any(x in message for x in ('unauthorized', 'denied', 'timeout', 'forbidden')):
            return None
        raise RuntimeError('Registry state UNKNOWN; promotion stopped') from error
    if not re.fullmatch('sha256:[0-9a-f]{64}', value):
        raise ValueError('Invalid registry digest')
    return value


def registry_config(image):
    manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', image, '--raw'))
    if 'manifests' in manifest:
        matches = [m for m in manifest['manifests'] if m.get('platform') == {'architecture': 'amd64', 'os': 'linux'}]
        if len(matches) != 1:
            raise ValueError('Ambiguous registry platform')
        repo = image.split('@')[0]
        manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', repo + '@' + matches[0]['digest'], '--raw'))
    value = manifest.get('config', {}).get('digest', '')
    if not re.fullmatch('sha256:[0-9a-f]{64}', value):
        raise ValueError('Invalid registry config ID')
    return value


def read_remote_policy(ref):
    run('git', 'cat-file', '-e', ref + '^{commit}')
    listing = run('git', 'ls-tree', '--name-only', ref, '--', 'tools/apk_policy.json')
    if not listing:
        return None
    # Same strict parser as the resolver, without resolving time/upstream again.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'policy.json'
        path.write_text(run('git', 'show', ref + ':tools/apk_policy.json'), encoding='utf-8')
        return read_policy(path)


def policy_check():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if os.environ['GITHUB_EVENT_NAME'] == 'pull_request':
        ref = event['pull_request']['base']['sha']
        if not re.fullmatch('[0-9a-f]{40}', ref):
            raise ValueError('PR base SHA UNKNOWN')
        run('git', 'fetch', '--no-tags', 'origin', ref)
    elif os.environ['GITHUB_EVENT_NAME'] == 'push':
        ref = event.get('before', '')
        if not re.fullmatch('[0-9a-f]{40}', ref) or ref == '0' * 40:
            raise ValueError('Previous push policy UNKNOWN')
        run('git', 'fetch', '--no-tags', 'origin', ref)
    else:
        branch = os.environ.get('GITHUB_BASE_REF') or event['repository']['default_branch']
        run('git', 'fetch', '--no-tags', 'origin', branch)
        ref = 'FETCH_HEAD'
    check_generation(read_policy(ROOT / 'tools/apk_policy.json'), read_remote_policy(ref))


def prepare(inputs, repo, pull_request):
    # PR always compiles: no reliance on anonymous package visibility or credentials.
    digest = None if pull_request else registry_digest(repo + ':build-' + inputs['build_key'])
    if digest:
        image = repo + '@' + digest
        run('docker', 'pull', '--platform', inputs['platform'], image)
        return {'mode': 'reuse', 'image': image, 'digest': digest}
    return {'mode': 'build', 'image': 'botapi-candidate:check', 'digest': None}


def qualify(state, inputs, evidence):
    refresh = json.loads((evidence / 'apk-refresh.json').read_text())
    if refresh.get('status') != 'PASS' or refresh.get('build_key') != inputs['build_key']:
        raise ValueError('apk cache regression gate did not pass for this snapshot')
    gates = json.loads((evidence / 'gates.json').read_text())
    if gates != {'build_key': inputs['build_key'], 'unit': 'PASS', 'compose': 'PASS'}:
        raise ValueError('Unit/Compose gates did not pass for this snapshot')
    directory = evidence / 'image'
    directory.mkdir(parents=True, exist_ok=True)
    result = metadata_receipt(state['image'], inputs, directory, state['mode'], state['digest'])
    config = result['image_config_id']
    run('docker', 'run', '--rm', '--network', 'none', '--cpus', '2', '--memory', '512m', config, '--version')
    run('docker', 'run', '--rm', '--network', 'none', '--cpus', '2', '--memory', '512m', '--entrypoint', 'sh', config, '-ec',
        'grep -aq "WebhookDelivery/1.0" /usr/local/bin/telegram-bot-api; sh -n /docker-entrypoint.sh')
    result['gates'].update(smoke='PASS', apk_refresh='PASS', unit='PASS', compose='PASS')
    save(evidence / 'receipt.json', result)
    return result


def assert_qualified(inputs, receipt):
    if receipt.get('inputs') != inputs or any(receipt.get('gates', {}).get(gate) != 'PASS' for gate in ('metadata', 'smoke', 'apk_refresh', 'unit', 'compose')):
        raise ValueError('Candidate has not passed all gates')
    if receipt.get('scanner', {}).get('status', 'NOTRUN') not in ('NOTRUN', 'PASS'):
        raise ValueError('Blocking or unresolved scanner finding')


def write_guard():
    branch = os.environ['DEFAULT_BRANCH']
    if os.environ.get('GITHUB_EVENT_NAME') == 'pull_request' or os.environ.get('GITHUB_REF') != 'refs/heads/' + branch:
        raise ValueError('Registry writes require the default branch')


def assert_fresh(inputs):
    branch = os.environ['DEFAULT_BRANCH']
    run('git', 'fetch', '--no-tags', 'origin', branch)
    files = {name: subprocess.check_output(['git', 'show', 'FETCH_HEAD:' + name], timeout=120) for name in RECIPE}
    identity = {k: v for k, v in inputs.items() if k != 'build_key'}
    if build_key(identity, files) != inputs['build_key']:
        raise ValueError('Default-branch recipe changed; stale run')
    if run('git', 'rev-parse', 'HEAD') != run('git', 'rev-parse', 'FETCH_HEAD'):
        raise ValueError('Default branch advanced; stale run')


def assert_latest_not_newer(repo, inputs, digest):
    if not digest:
        return
    image = repo + '@' + digest
    run('docker', 'pull', '--platform', inputs['platform'], image)
    labels = json.loads(run('docker', 'image', 'inspect', image))[0]['Config'].get('Labels') or {}
    window = labels.get('io.tg-selfhost.apk-refresh-window')
    generation = labels.get('io.tg-selfhost.apk-refresh-generation')
    # A legacy image may predate refresh evidence, but a partially present identity is UNKNOWN.
    if window is None and generation is None:
        return
    if not isinstance(window, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', window) or not str(generation).isdigit():
        raise ValueError('Latest refresh identity UNKNOWN')
    if window > inputs['apk_refresh_window'] or int(generation) > inputs['generation']:
        raise ValueError('Latest has a newer refresh; refusing stale rerun')


def publish_candidate(state, inputs, receipt, repo):
    write_guard()
    assert_qualified(inputs, receipt)
    assert_fresh(inputs)
    if state['mode'] == 'reuse':
        digest = state['digest']
    else:
        tag = repo + ':candidate-' + inputs['build_key'] + '-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
        if registry_digest(tag) is not None:
            raise ValueError('Candidate tag exists; do not overwrite an earlier attempt')
        run('docker', 'tag', receipt['image_config_id'], tag)
        run('docker', 'push', tag)
        digest = registry_digest(tag)
    if not digest or registry_config(repo + '@' + digest) != receipt['image_config_id']:
        raise ValueError('Registry candidate differs from qualified config')
    return {**receipt, 'candidate_digest': digest}


def promote(inputs, receipt, repo, evidence):
    write_guard()
    assert_qualified(inputs, receipt)
    assert_fresh(inputs)
    digest = receipt.get('candidate_digest')
    if not digest or registry_config(repo + '@' + digest) != receipt['image_config_id']:
        raise ValueError('Candidate config verification failed')
    tag = repo + ':build-' + inputs['build_key']
    existing = registry_digest(tag)
    if existing is not None and existing != digest:
        raise ValueError('Build-key collision; increase policy generation')
    if existing is None:
        run('docker', 'buildx', 'imagetools', 'create', '--prefer-index=false', '--tag', tag, repo + '@' + digest)
    if registry_digest(tag) != digest:
        raise ValueError('Build tag read-back failed')
    previous = registry_digest(repo + ':latest')
    assert_latest_not_newer(repo, inputs, previous)
    save(evidence / 'promotion.json', {'previous_latest': previous, 'candidate_digest': digest, 'status': 'NOTRUN'})
    # Refresh branch/window check immediately before latest mutation.
    assert_fresh(inputs)
    run('docker', 'buildx', 'imagetools', 'create', '--prefer-index=false', '--tag', repo + ':latest', repo + '@' + digest)
    actual = registry_digest(repo + ':latest')
    save(evidence / 'promotion.json', {'previous_latest': previous, 'candidate_digest': digest, 'latest_digest': actual,
                                     'status': 'PASS' if actual == digest else 'UNKNOWN'})
    if actual != digest:
        raise ValueError('Latest read-back UNKNOWN; inspect registry before further action')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('policy', 'prepare', 'qualify', 'publish-candidate', 'promote'))
    parser.add_argument('--inputs', default='evidence/inputs.json')
    parser.add_argument('--evidence', default='evidence')
    args = parser.parse_args()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == 'policy':
            policy_check()
            return
        inputs = json.loads(Path(args.inputs).read_text())
        repo = 'ghcr.io/' + os.environ['GITHUB_REPOSITORY'].lower()
        state_path = evidence / 'state.json'
        if args.phase == 'prepare':
            state = prepare(inputs, repo, os.environ['GITHUB_EVENT_NAME'] == 'pull_request')
            save(state_path, state)
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write('mode=' + state['mode'] + '\n')
            return
        state = json.loads(state_path.read_text())
        if args.phase == 'qualify':
            qualify(state, inputs, evidence)
            return
        receipt = json.loads((evidence / 'receipt.json').read_text())
        if args.phase == 'publish-candidate':
            save(evidence / 'receipt.json', publish_candidate(state, inputs, receipt, repo))
        else:
            promote(inputs, receipt, repo, evidence)
    except Exception as error:
        # No raw command output: diagnostics may include registry authentication details.
        save(evidence / ('failure-' + args.phase + '.json'), {'phase': args.phase, 'status': 'FAIL', 'error_type': type(error).__name__})
        raise


if __name__ == '__main__':
    main()
