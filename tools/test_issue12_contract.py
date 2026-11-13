import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from image_inputs import ROOT, resolve
from release_contract import GATES, select_release, validate_inputs, validate_receipt, validate_selected


class ReleaseManifestTest(unittest.TestCase):
    def setUp(self):
        self.inputs = resolve()

    def fixture(self):
        return dict(schema=1, qualification_version=1, build_key=self.inputs['build_key'],
                    qualification_key=self.inputs['qualification_key'],
                    components={name: {'image': 'ghcr.io/example/' + name + ':release@sha256:' + 'c' * 64,
                        'config_id': 'sha256:' + 'b' * 64, 'rootfs_sha256': 'f' * 64}
                        for name in ('botapi', 'observer', 'downloads', 'sender')},
                    platform='linux/amd64', server_revision=self.inputs['bot_api_revision'],
                    server_version=self.inputs['bot_api_version'], tdlib_revision=self.inputs['submodules']['td'],
                    wrapper_revision=self.inputs['wrapper_revision'], config_id='sha256:' + 'b' * 64,
                    index_digest='sha256:' + 'c' * 64, platform_digest='sha256:' + 'd' * 64,
                    binary_sha256='e' * 64, recipe_sha256={'Dockerfile': 'f' * 64},
                    inventories_sha256={'runtime-packages.txt': 'f' * 64}, patch_sha256='1' * 64,
                    entrypoint_sha256='2' * 64,
                    checks={name: {'status': 'NOTRUN', 'evidence_sha256': None} for name in GATES},
                    provenance='ci', gateway={'image': self.inputs['nginx_image'], 'platform_digest': self.inputs['nginx_platform_digest'], 'config_id':'sha256:'+'9'*64, 'version':self.inputs['nginx_version']})

    def test_cli_selection_uses_ci_snapshot_instead_of_repository_lock(self):
        import hashlib
        import subprocess
        import sys
        import tempfile
        from image_inputs import recipe_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = json.loads((ROOT / 'image-inputs.lock.json').read_text(encoding='utf8'))
            (root / 'image-inputs.lock.json').write_text(json.dumps(lock), encoding='utf8')
            lock['inputs']['wrapper_revision'] = 'a' * 40
            snapshot = root / 'inputs.json'
            snapshot.write_text(json.dumps(lock), encoding='utf8')
            ci = resolve(inputs_file=snapshot)
            receipt = self.fixture()
            receipt.update(wrapper_revision=ci['wrapper_revision'], build_key=ci['build_key'], qualification_key=ci['qualification_key'])
            receipt['checks'] = {name: {'status': 'PASS', 'evidence_sha256': 'a' * 64} for name in GATES}
            receipt['recipe_sha256'] = {p: hashlib.sha256(raw).hexdigest() for p, raw in recipe_files().items()}
            receipt['components']['botapi']['image'] = 'ghcr.io/example/botapi:build@' + receipt['index_digest']
            path = root / 'receipt.json'
            path.write_text(json.dumps(receipt), encoding='utf8')
            cmd = [sys.executable, str(ROOT / 'tools/release_contract.py'), '--root', str(root),
                   '--select-receipt', str(path), '--botapi-image', 'ghcr.io/example/botapi:build@' + receipt['index_digest']]
            old = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(old.returncode, 0)
            self.assertIn('differs from saved inputs', old.stderr)
            selected = subprocess.run(cmd + ['--inputs-file', str(snapshot)], capture_output=True, text=True)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertTrue((root / 'releases/receipts' / (hashlib.sha256(path.read_bytes()).hexdigest() + '.json')).exists())

    def test_replay_never_resolves_time_or_network(self):
        with (patch('image_inputs.command', side_effect=AssertionError('network')),
              patch('image_inputs.datetime') as clock):
            self.assertEqual(resolve(), resolve())
            clock.now.assert_not_called()

    def test_pending_inputs_and_empty_selection(self):
        doc = json.loads((ROOT / 'image-inputs.lock.json').read_text(encoding='utf-8'))
        validate_inputs(doc)
        self.assertIsNone(validate_selected({'schema': 1, 'selected_release': None}, self.inputs))
        doc['token'] = 'forbidden'
        with self.assertRaises(ValueError):
            validate_inputs(doc)

    def test_missing_gates_never_approve(self):
        receipt = self.fixture()
        validate_receipt(receipt, self.inputs)
        with self.assertRaises(ValueError):
            validate_receipt(receipt, self.inputs, approved=True)
        for field in ('config_id', 'server_revision', 'platform', 'build_key', 'checks'):
            bad = copy.deepcopy(receipt)
            bad[field] = 'wrong'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_receipt(bad, self.inputs)

    def test_pass_requires_evidence_and_unknown_fields_fail(self):
        receipt = self.fixture()
        receipt['checks']['runtime_ua']['status'] = 'PASS'
        with self.assertRaises(ValueError):
            validate_receipt(receipt, self.inputs)
        receipt = self.fixture()
        receipt['provenance'] = 'manual-live'
        receipt['checks'] = {name: {'status': 'PASS', 'evidence_sha256': 'a' * 64} for name in GATES}
        receipt['checks']['image']['status'] = 'NOTRUN'
        receipt['checks']['image']['evidence_sha256'] = None
        with self.assertRaises(ValueError):
            validate_receipt(receipt, self.inputs, approved=True)
        receipt = self.fixture()
        receipt['webhook_url'] = 'private'
        with self.assertRaises(ValueError):
            validate_receipt(receipt, self.inputs)

    def test_selection_exports_only_qualified_exact_digest_and_public_images(self):
        import hashlib
        from image_inputs import recipe_files
        receipt = self.fixture()
        receipt['checks'] = {name: {'status': 'PASS', 'evidence_sha256': 'a' * 64} for name in GATES}
        receipt['recipe_sha256'] = {p: hashlib.sha256(raw).hexdigest() for p, raw in recipe_files().items()}
        raw = json.dumps(receipt).encode()
        image = 'ghcr.io/example/botapi:release@' + receipt['index_digest']
        selected, env = select_release(self.inputs, raw, image)
        self.assertEqual(validate_selected(selected, self.inputs, raw)['botapi_image'], image)
        self.assertEqual(env.splitlines(), ['BOTAPI_IMAGE=' + image,
            'OBSERVER_IMAGE=' + receipt['components']['observer']['image'],
            'DOWNLOADS_IMAGE=' + receipt['components']['downloads']['image'], 'GATEWAY_IMAGE=' + self.inputs['nginx_image']])
        with self.assertRaises(ValueError):
            select_release(self.inputs, raw, image.replace(receipt['index_digest'], 'sha256:' + '0' * 64))
        for gate in GATES:
            bad = copy.deepcopy(receipt)
            bad['checks'][gate] = {'status': 'NOTRUN', 'evidence_sha256': None}
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                select_release(self.inputs, json.dumps(bad).encode(), image)
        receipt['recipe_sha256']['Dockerfile'] = '0' * 64
        with self.assertRaises(ValueError):
            select_release(self.inputs, json.dumps(receipt).encode(), image)


if __name__ == '__main__':
    unittest.main()
