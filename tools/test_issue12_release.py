"""Release approval is distinct from code completion and discovery."""
import copy
import unittest
from unittest.mock import patch
from qualify_release import publish, validate_evidence, sha
from image_inputs import recipe_files, resolve, ROOT
from release_contract import GATES, validate_receipt
import test_issue12_contract


class QualificationTests(unittest.TestCase):
    def fixture(self):
        fixture = test_issue12_contract.ReleaseManifestTest()
        fixture.setUp()
        receipt = fixture.fixture()
        for gate in receipt['checks'].values():
            gate.update(status='PASS', evidence_sha256='a' * 64)
        return fixture.inputs, receipt

    def test_every_required_gate_and_component_is_required(self):
        inputs, receipt = self.fixture()
        validate_receipt(receipt, inputs, approved=True)
        for gate in GATES:
            bad = copy.deepcopy(receipt)
            bad['checks'][gate] = {'status': 'NOTRUN', 'evidence_sha256': None}
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                validate_receipt(bad, inputs, approved=True)
        for name in receipt['components']:
            bad = copy.deepcopy(receipt)
            del bad['components'][name]
            with self.subTest(component=name), self.assertRaises(ValueError):
                validate_receipt(bad, inputs, approved=True)

    def test_pass_words_cannot_publish_without_evidence(self):
        _, receipt = self.fixture()
        with self.assertRaisesRegex(ValueError, 'executed gate evidence'):
            validate_evidence({'checks': receipt['checks']}, None)
        with patch('qualify_release.subprocess.run') as command:
            with self.assertRaises(ValueError):
                publish('local:test', 'ghcr.io/example/botapi', {}, {}, None, 'observer:test', 'downloads:test')
            command.assert_not_called()

    def test_foreign_qualification_key_cannot_be_selected(self):
        inputs, receipt = self.fixture()
        receipt['qualification_key'] = '0' * 32
        with self.assertRaises(ValueError):
            validate_receipt(receipt, inputs, approved=True)

    def test_changed_component_prevents_any_registry_write(self):
        inputs = resolve()
        candidate = {'qualification_key': inputs['qualification_key'], 'image': {'config_id': 'original'},
            'gateway': {}, 'recipe_sha256': {p: sha(raw) for p, raw in recipe_files().items()},
            'components': {'botapi': {'config_id': 'original'}}}
        with patch('qualify_release.validate_evidence'), patch('qualify_release.image_evidence', return_value=candidate['image']), \
             patch('qualify_release.gateway_evidence', return_value={}), \
             patch('qualify_release.component', return_value={'config_id': 'changed'}), \
             patch('qualify_release.subprocess.run') as command:
            with self.assertRaisesRegex(ValueError, 'changed before publication'):
                publish('local:test', 'ghcr.io/example/botapi', inputs, candidate, ROOT, 'observer:test', 'downloads:test')
            command.assert_not_called()

    def test_dependency_stages_do_not_absorb_following_docker_instruction(self):
        text = (ROOT / 'Dockerfile').read_text()
        self.assertNotIn('\\\n\n\nFROM', text)
        self.assertTrue(text.rstrip().endswith('FROM runtime AS production'))
