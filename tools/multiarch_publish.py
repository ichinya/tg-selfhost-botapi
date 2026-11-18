"""Publish a qualified bundle and switch its Bot API release pointer last."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from multiarch_verify import verify_index


ANNOTATION_PREFIX = 'io.tg-selfhost.release.'
IMAGETOOLS = ['docker', 'buildx', 'imagetools']

def validate_pair(receipts,sha,run):
    if len(receipts)!=2 or {r.get('architecture') for r in receipts}!={'amd64','arm64'}:
        raise ValueError('two distinct native architectures required')
    shared=None
    for r in receipts:
        if set(r)!={'architecture','sha','run_id','inputs','components','native','qualified'} or r['sha']!=sha or r['run_id']!=run or r['native'] is not True or r['qualified'] is not True:
            raise ValueError('qualification origin mismatch')
        if set(r['components'])!={'botapi','observer','downloads'}: raise ValueError('incomplete bundle')
        for ref in r['components'].values():
            if not re.fullmatch(r'ghcr.io/[a-z0-9_./-]+@sha256:[0-9a-f]{64}',ref): raise ValueError('immutable qualified reference required')
        inputs=dict(r['inputs']); inputs.pop('platform',None); inputs.pop('build_key',None)
        if shared is not None and inputs!=shared: raise ValueError('source/base/window/recipe differ')
        shared=inputs
    return receipts

def main():
    p=argparse.ArgumentParser(); p.add_argument('--receipts',required=True); p.add_argument('--image',required=True)
    args=p.parse_args()
    if not re.fullmatch(r'ghcr.io/[a-z0-9_./-]+',args.image): raise ValueError('invalid repository')
    receipts=[json.loads(path.read_text()) for path in Path(args.receipts).glob('**/qualification.json')]
    validate_pair(receipts,os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'])
    promote(receipts, args.image)


def inspect_digest(ref):
    result = subprocess.run([*IMAGETOOLS, 'inspect', '--format', '{{.Manifest.Digest}}', ref],
                            check=True, capture_output=True, text=True, timeout=120)
    digest = result.stdout.strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('registry did not return an index digest')
    return digest


def publish_index(repository, stage, command, expected, annotations):
    annotation_args = [arg for key, value in annotations.items()
                       for arg in ('--annotation', f'index:{key}={value}')]
    subprocess.run([*command, *annotation_args], check=True, timeout=120)
    pinned = repository + '@' + inspect_digest(stage)
    result = subprocess.run([*IMAGETOOLS, 'inspect', '--raw', pinned],
                            check=True, capture_output=True, timeout=120)
    index = json.loads(result.stdout)
    verify_index(index, expected)
    if any((index.get('annotations') or {}).get(key) != value for key, value in annotations.items()):
        raise ValueError('published release annotations do not match the qualified bundle')
    return pinned


def promote(receipts, image):
    components = {role: {receipt['architecture']: receipt['components'][role] for receipt in receipts}
                  for role in ('observer', 'downloads', 'botapi')}
    release = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()[:32]
    plans = {}
    for role, refs in components.items():
        repository = image + ('-downloads' if role == 'downloads' else '')
        stage = f'{repository}:release-{role}-{release}'
        expected = {arch: ref.rsplit('@', 1)[1] for arch, ref in refs.items()}
        command = [*IMAGETOOLS, 'create', '--tag', stage, *refs.values()]
        preview = subprocess.run([*command, '--dry-run'], check=True, capture_output=True, timeout=120)
        verify_index(json.loads(preview.stdout), expected)
        plans[role] = (repository, stage, command, expected)

    companions = {role: publish_index(*plans[role], {}) for role in ('observer', 'downloads')}
    annotations = {ANNOTATION_PREFIX + role: ref for role, ref in companions.items()}
    botapi = publish_index(*plans['botapi'], annotations)

    # Compatibility aliases are conveniences. Consumers of a matched bundle
    # resolve both companion digests through the Bot API index annotations.
    for role, alias in (('observer', image + ':observer-latest'),
                        ('downloads', image + '-downloads:latest'), ('botapi', image + ':latest')):
        pinned = botapi if role == 'botapi' else companions[role]
        subprocess.run([*IMAGETOOLS, 'create', '--tag', alias, pinned], check=True, timeout=120)
        if inspect_digest(alias) != pinned.rsplit('@', 1)[1]:
            raise ValueError('published tag does not match its qualified index digest')

if __name__=='__main__': main()
