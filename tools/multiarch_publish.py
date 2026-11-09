"""Single fail-closed publisher: qualify immutable index, then promote it.

No build/latest write is made by qualify. Upload qualification.json before promote.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import urllib.parse

from image_inputs import Registry, canonical, snapshot_hash, validate_snapshot
from multiarch_verify import (EVENTS, context_from_env, validate_context,
                                 validate_pair, validate_qualification)
from multiarch_verify import (command, verify_config, verify_remote,
                                verify_release_index, verify_stored_image)
from multiarch_qualify import file_hash


def gate(context, results, default_branch):
    validate_context(context)
    if context['event'] not in EVENTS or context['branch'] != default_branch:
        raise ValueError('Registry writes require a default-branch non-PR run')
    if results != {'prepare': 'success', 'native': 'success'}:
        raise ValueError('All preparation and native matrix jobs must succeed')


def verify_current_head(context, default_branch):
    """Check Actions origin and wrapper freshness immediately before registry writes."""
    ref = urllib.parse.quote(default_branch, safe="")
    commit = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/{context['repository']}/git/ref/heads/{ref}"], timeout=60))
    run = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/{context['repository']}/actions/runs/{context['run_id']}"], timeout=60))
    if (commit.get("object", {}).get("sha") != context["sha"]
            or run.get("head_sha") != context["sha"] or run.get("head_branch") != default_branch
            or run.get("event") != context["event"] or run.get("path") != context["workflow"]
            or str(run.get("run_attempt")) != context["run_attempt"]
            or run.get("repository", {}).get("full_name") != context["repository"]):
        raise ValueError("Stale wrapper HEAD or wrong Actions run origin; no release write")


class Backend:
    def __init__(self, image, registry):
        self.image, self.registry = image, registry

    def read(self, tag, missing=False):
        return self.registry.manifest(tag, missing=missing)

    def load(self, archive, receipt, inputs):
        subprocess.run(['docker', 'load', '--input', str(archive)], check=True, capture_output=True, timeout=600)
        image_id = receipt['local']['image_id']
        inspected = json.loads(command('docker', 'image', 'inspect', image_id))
        if len(inspected) != 1 or inspected[0].get('Id') != image_id:
            raise ValueError('Archive substituted the tested image/config ID')
        checked = verify_stored_image(image_id, receipt['platform'].split('/')[1], inputs)
        if checked['elf_sha256'] != receipt['local']['elf_sha256']:
            raise ValueError('Archive ELF differs from native-tested binary')

    def push(self, tag, receipt):
        ref = self.image + ':' + tag
        command('docker', 'tag', receipt['local']['image_id'], ref)
        try:
            subprocess.run(['docker', 'push', ref], check=True, capture_output=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass  # Read back the unique candidate before deciding; never retry a write.
        child, _ = self.read(tag)
        return child

    def remote(self, child, arch, inputs, config_id):
        return verify_remote(self.registry, child, arch, inputs, config_id)

    def create(self, tag, children):
        command('docker', 'buildx', 'imagetools', 'create', '--prefer-index=false', '--tag', self.image + ':' + tag,
                *(self.image + '@' + child for child in children))


def checked_index(backend, reference, inputs, pair, expected_digest=None):
    digest, index = backend.read(reference)
    if expected_digest is not None and digest != expected_digest:
        raise ValueError('Index digest differs from approved staging index')
    expected = {arch: receipt['registry']['manifest_digest'] for arch, receipt in pair.items()}
    verify_release_index(index, expected)
    sizes = {item["digest"]: item["size"] for item in index["manifests"]}
    for arch, child in expected.items():
        checked = backend.remote(child, arch, inputs, pair[arch]['local']['image_id'])
        if checked != pair[arch]['registry'] or checked['manifest_size'] != sizes[child]:
            raise ValueError('Remote child/config changed')
    return digest


def qualify(backend, inputs, receipts, context, results, branch, directory, plan):
    gate(context, results, branch)
    pair = validate_pair(copy.deepcopy(receipts), inputs, context)
    # Validate *both* archives before loading or performing any registry mutation.
    for arch, receipt in pair.items():
        archive = directory / arch / 'image.tar'
        if file_hash(archive) != receipt['archive_sha256']:
            raise ValueError('Image archive hash mismatch')
        if file_hash(directory / arch / 'sender.tar') != receipt['sender']['archive_sha256']:
            raise ValueError('Sender archive hash mismatch')
    for arch, receipt in pair.items():
        backend.load(directory / arch / 'image.tar', receipt, inputs)
        sender_receipt = copy.deepcopy(receipt)
        sender_receipt['local']['image_id'] = receipt['sender']['image_id']
        backend.load(directory / arch / 'sender.tar', sender_receipt, inputs)
    build_tag = 'build-' + inputs['build_key']
    existing = backend.read(build_tag, missing=True)
    previous = backend.read('latest', missing=True)
    mode = plan.get('mode')
    if mode == 'reuse':
        previous_qualification = plan['qualification']
        old_pair = validate_qualification(previous_qualification, inputs, context['repository'], branch)
        if existing is None or existing[0] != previous_qualification['index_digest']:
            raise ValueError('Existing immutable build changed before reuse')
        for arch, receipt in pair.items():
            if (receipt['mode'] != 'reuse' or receipt['registry'] != old_pair[arch]['registry']
                    or receipt['compile'] != old_pair[arch]['compile']
                    or receipt['sender']['manifest_digest'] != old_pair[arch]['sender']['manifest_digest']
                    or receipt['sender']['image_id'] != old_pair[arch]['sender']['image_id']):
                raise ValueError('Reuse lost original compilation/digest evidence')
        approved = checked_index(backend, build_tag, inputs, pair, previous_qualification['index_digest'])
    elif mode == 'build':
        if existing is not None:
            raise ValueError('Immutable build tag collision: do not overwrite or repair K')
        if any(receipt['mode'] != 'build' for receipt in pair.values()):
            raise ValueError('Cold build plan needs fresh compile evidence')
        for arch, receipt in pair.items():
            candidate = f"candidate-{inputs['build_key']}-{arch}-{context['run_id']}-{context['run_attempt']}"
            child = backend.push(candidate, receipt)
            receipt['registry'] = backend.remote(child, arch, inputs, receipt['local']['image_id'])
            receipt['compile']['manifest_digest'] = child
            sender_receipt = copy.deepcopy(receipt)
            sender_receipt['local']['image_id'] = receipt['sender']['image_id']
            sender_child = backend.push(candidate + '-sender', sender_receipt)
            backend.remote(sender_child, arch, inputs, receipt['sender']['image_id'])
            receipt['sender']['manifest_digest'] = sender_child
        staging = f"staging-{inputs['build_key']}-{context['run_id']}-{context['run_attempt']}"
        try:
            backend.create(staging, [pair[arch]['registry']['manifest_digest'] for arch in ('amd64', 'arm64')])
        except Exception:
            pass
        approved = checked_index(backend, staging, inputs, pair)
    else:
        raise ValueError('Invalid publication mode')
    value = {'schema': 2, 'contract': inputs['verification_contract'], 'build_key': inputs['build_key'],
             'snapshot_hash': snapshot_hash(inputs), 'inputs': inputs, 'context': context,
             'run_url': f"https://github.com/{context['repository']}/actions/runs/{context['run_id']}/attempts/{context['run_attempt']}",
             'index_digest': approved, 'children': pair, 'status': 'QUALIFIED'}
    validate_qualification(value, inputs, context['repository'], branch)
    promotion = {'schema': 2, 'snapshot_hash': snapshot_hash(inputs), 'context': context, 'mode': mode,
                 'approved_digest': approved, 'previous_latest': previous[0] if previous else None}
    return value, promotion


def promote(backend, inputs, value, promotion, context, results, branch, report_path):
    gate(context, results, branch)
    pair = validate_qualification(value, inputs, context['repository'], branch)
    if (value['context'] != context or promotion.get('context') != context
            or promotion.get('schema') != 2 or promotion.get('snapshot_hash') != snapshot_hash(inputs)
            or promotion.get('approved_digest') != value['index_digest'] or promotion.get('mode') not in ('build', 'reuse')):
        raise ValueError('Promotion belongs to another run/attempt or index')
    approved = checked_index(backend, value['index_digest'], inputs, pair, value['index_digest'])
    build_tag = 'build-' + inputs['build_key']
    existing = backend.read(build_tag, missing=True)
    if existing is not None and existing[0] != approved:
        raise ValueError('Immutable build tag collision at promotion')
    if existing is None:
        if promotion['mode'] != 'build':
            raise ValueError('Reuse cannot recreate a lost immutable build')
        try:
            backend.create(build_tag, [approved])
        except Exception:
            pass
    checked_index(backend, build_tag, inputs, pair, approved)
    # Avoid replacing a concurrently promoted external release. Never auto-rollback.
    current = backend.read('latest', missing=True)
    if (current[0] if current else None) != promotion['previous_latest']:
        raise ValueError('Latest changed since qualification; no promotion attempted')
    report = {'status': 'UNKNOWN', 'context': context, 'approved_digest': approved,
              'previous_latest': promotion['previous_latest'], 'latest_digest': None, 'rollback': 'NOTRUN'}
    write_failed = False
    try:
        try:
            backend.create('latest', [approved])
        except Exception:
            write_failed = True  # A timeout can occur after a successful registry write.
        checked_index(backend, 'latest', inputs, pair, approved)
        report.update(status='PASS', latest_digest=approved,
                      write_response='error_reconciled' if write_failed else 'success')
        return report
    finally:
        report_path.write_bytes(canonical(report) + b'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('qualify', 'promote'))
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--snapshot-hash', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--directory', default='images')
    parser.add_argument('--output', default='publication')
    args = parser.parse_args()
    inputs = validate_snapshot(json.loads(Path(args.snapshot).read_text()), args.snapshot_hash)
    context = context_from_env()
    branch = os.environ['DEFAULT_BRANCH']
    results = json.loads(os.environ['JOB_RESULTS'])
    registry = Registry('ghcr.io', context['repository'].lower(), os.environ.get('GITHUB_ACTOR'), os.environ.get('GH_TOKEN'))
    backend = Backend('ghcr.io/' + context['repository'].lower(), registry)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    gate(context, results, branch)
    verify_current_head(context, branch)
    if args.action == 'qualify':
        directory = Path(args.directory)
        receipts = [json.loads((directory / arch / 'receipt.json').read_text()) for arch in ('amd64', 'arm64')]
        value, promotion = qualify(backend, inputs, receipts, context, results, branch, directory, json.loads(Path(args.plan).read_text()))
        (output / 'qualification.json').write_bytes(canonical(value) + b'\n')
        (output / 'promotion.json').write_bytes(canonical(promotion) + b'\n')
    else:
        promote(backend, inputs, json.loads((output / 'qualification.json').read_text()),
                json.loads((output / 'promotion.json').read_text()), context, results, branch, output / 'report.json')
