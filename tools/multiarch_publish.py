"""Validate same-run native qualification receipts before any manifest update."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path

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
    for component,suffix in (('botapi',':latest'),('observer',':observer-latest'),('downloads','-downloads:latest')):
        subprocess.run(['docker','buildx','imagetools','create','--tag',args.image+suffix,*[r['components'][component] for r in receipts]],check=True,timeout=120)

if __name__=='__main__': main()
