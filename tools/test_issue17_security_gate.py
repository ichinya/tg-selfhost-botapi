import contextlib
import io
import json
import unittest
from unittest import mock
from issue17_security_gate import main, GateFailure, require_clean_candidate, image_gate


class SecurityGate(unittest.TestCase):
    def test_missing_required_gate_blocks_and_redacts_failure(self):
        captured=io.StringIO()
        with mock.patch('issue17_security_gate.output',return_value='a'*40),mock.patch('issue17_security_gate.unit_gate',side_effect=GateFailure('private_error_canary')),contextlib.redirect_stdout(captured):
            self.assertEqual(main(['--unit']),1)
        manifest=json.loads(captured.getvalue())
        self.assertEqual(manifest['gates']['unit']['status'],'FAIL')
        self.assertNotIn('private_error_canary',captured.getvalue())

    def test_unit_failure_identifies_only_fixed_stage(self):
        captured=io.StringIO()
        with mock.patch('issue17_security_gate.require_clean_candidate'), mock.patch('issue17_security_gate.command',side_effect=GateFailure('private_error_canary')), mock.patch('issue17_security_gate.output',return_value='a'*40), contextlib.redirect_stdout(captured):
            self.assertEqual(main(['--unit']),1)
        gate=json.loads(captured.getvalue())['gates']['unit']
        self.assertEqual(gate['stage'],'discovery')
        self.assertNotIn('private_error_canary',captured.getvalue())

    def test_dirty_checkout_refuses_full_discovery(self):
        with mock.patch('issue17_security_gate.output',return_value='?? foreign-test.py'):
            with self.assertRaisesRegex(GateFailure,'clean_candidate_required'):require_clean_candidate()

    def test_existing_image_without_policy_is_rejected(self):
        with mock.patch('issue17_security_gate.output',return_value='[{"Config":{"Labels":{}}}]'):
            with self.assertRaisesRegex(GateFailure,'candidate_policy_missing'):image_gate('fixture')
