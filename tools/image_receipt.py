"""Create a CI receipt; manual gates must never be inferred from smoke."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from image_inputs import RECIPE, ROOT


def receipt(inputs, inventories, reused, image=None, smoke_passed=False):
    return {'schema': 1, 'inputs': inputs,
            'recipe_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in RECIPE},
            'qualification_version': 1, 'record_kind': 'local-candidate-not-approved',
            'apk_policy': 'utc-day; canonical evidence schema 2', 'approved': False,
            'inventories': inventories, 'image': image, 'checks': {'runtime_smoke': 'PASS' if smoke_passed else 'NOTRUN', 'delivery': 'NOTRUN', 'restore': 'NOTRUN'},
            'reused': reused, 'build_provenance': 'NOT_CLAIMED' if reused else 'CI_LOCAL_BUILD'}


def main():
    import tempfile
    from image_metadata import receipt as apk_receipt
    inputs = json.loads(Path(os.environ['INPUTS_FILE']).read_text())
    with tempfile.TemporaryDirectory() as temp:
        result = apk_receipt(os.environ.get('CANDIDATE_IMAGE', 'botapi-candidate:check'), inputs,
                             Path(temp), 'reuse' if os.environ.get('REUSED') == 'true' else 'build')
    Path('receipt-' + inputs['build_key'] + '.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
