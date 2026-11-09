from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
"""Contract tests for evidence trust and run isolation."""
import copy
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from image_inputs import CONTRACT, snapshot_hash
from multiarch_qualify import validate_receipt, validate_pair, validate_qualification, find_qualification


def fixtures():
    inputs = {'schema': 2, 'verification_contract': CONTRACT, 'platforms': ['linux/amd64', 'linux/arm64'],
              'bot_api_revision': 'a' * 40, 'alpine_image': 'alpine:3.22@sha256:' + 'b' * 64,
              'base_children': {'linux/amd64': 'sha256:' + 'c' * 64, 'linux/arm64': 'sha256:' + 'd' * 64},
              'expected_version': '9.2', 'build_key': 'e' * 32}
    context = {'repository': 'owner/repo', 'workflow': '.github/workflows/image.yml', 'event': 'push',
               'branch': 'main', 'sha': 'f' * 40, 'run_id': '123', 'run_attempt': '1'}
    pair = {}
    for arch, n in (('amd64', '1'), ('arm64', '2')):
        config = 'sha256:' + n * 64
        pair[arch] = {'schema': 2, 'contract': CONTRACT, 'build_key': inputs['build_key'],
                      'snapshot_hash': snapshot_hash(inputs), 'inputs': copy.deepcopy(inputs), 'platform': 'linux/' + arch,
                      'context': copy.deepcopy(context), 'mode': 'build', 'archive_sha256': 'sha256:' + '3' * 64,
                      'local': {'image_id': config, 'elf_sha256': '4' * 64, 'version': '9.2', 'ua': 'WebhookDelivery/1.0',
                                'native': {'host': arch, 'daemon': arch, 'os': 'linux'}, 'rootfs':['sha256:'+'f'*64]},
                      'checks': {key: 'PASS' for key in ('config', 'elf', 'version', 'ua', 'native', 'entrypoint_syntax', 'runtime_contents')},
                      'sender': {'status': 'PASS', 'negative': 'PASS', 'queue_acknowledged': True,
                                 'image_id': 'sha256:' + ('8' if arch == 'amd64' else '9') * 64,
                                 'elf_sha256': '4' * 64, 'archive_sha256': 'sha256:' + 'a' * 64},
                      'smoke': {'status': 'PASS'}, 'registry': None,
                      'compile': {'status': 'PASS', 'patch': 'PASS', 'cmake': 'PASS', 'cold': True,
                                  'config_id': config, 'snapshot_hash': snapshot_hash(inputs),
                                  'context': copy.deepcopy(context), 'build_record': {'buildx.build.ref': 'builder/node/record'}}}
    from image_inputs import ROOT, sha256
    for receipt in pair.values():
        receipt['local']['source'] = {'revision': inputs['bot_api_revision'],
            'patch_sha256': sha256((ROOT/'patches/webhook-user-agent.patch').read_bytes()),
            'submodules': [' '+'a'*40+' td (pinned)']}
    return inputs, context, pair


def qualification():
    inputs, context, pair = fixtures()
    for arch, receipt in pair.items():
        child = 'sha256:' + ('5' if arch == 'amd64' else '6') * 64
        receipt['registry'] = {'manifest_digest': child, 'config_digest': receipt['local']['image_id'], 'manifest_size':100}
        receipt['compile']['manifest_digest'] = child
        receipt['sender']['manifest_digest'] = 'sha256:' + ('a' if arch == 'amd64' else 'b') * 64
    value = {'schema': 2, 'contract': CONTRACT, 'build_key': inputs['build_key'], 'snapshot_hash': snapshot_hash(inputs),
             'inputs': inputs, 'context': context, 'children': pair, 'index_digest': 'sha256:' + '7' * 64, 'status': 'QUALIFIED'}
    return inputs, context, value


class QualificationTest(unittest.TestCase):
    def test_receipt_requires_pass_and_exact_context(self):
        inputs, context, pair = fixtures()
        validate_pair(list(pair.values()), inputs, context)
        for status in ('failed', 'skipped', 'NOTRUN', 'UNKNOWN'):
            bad = copy.deepcopy(pair['arm64'])
            bad['checks']['native'] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_receipt(bad, inputs, context)
        for key in ('run_id', 'run_attempt', 'repository'):
            bad = copy.deepcopy(pair['arm64'])
            bad['context'][key] = 'other'
            with self.assertRaises(ValueError):
                validate_receipt(bad, inputs, context)

    def test_missing_duplicate_and_compile_evidence_rejected(self):
        inputs, context, pair = fixtures()
        for receipts in ([pair['amd64']], [pair['amd64'], pair['amd64']]):
            with self.assertRaises(ValueError):
                validate_pair(receipts, inputs, context)
        for key in ('patch', 'cmake', 'config_id', 'snapshot_hash', 'build_record'):
            bad = copy.deepcopy(pair['amd64'])
            bad['compile'][key] = ''
            with self.assertRaises(ValueError):
                validate_receipt(bad, inputs, context)

    def test_trust_requires_success_default_branch_workflow(self):
        inputs, context, value = qualification()
        run = {'id': 123, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
               'repository': {'full_name': 'owner/repo'}, 'path': '.github/workflows/image.yml',
               'head_branch': 'main', 'event': 'push', 'head_sha': context['sha']}
        validate_qualification(value, inputs, 'owner/repo', 'main', run)
        for field, wrong in (('conclusion', 'failure'), ('event', 'pull_request'), ('head_branch', 'feature'),
                             ('path', '.github/workflows/other.yml'), ('run_attempt', 2), ('head_sha', 'a' * 40)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_qualification(value, inputs, 'owner/repo', 'main', {**run, field: wrong})

    def test_reuse_retains_original_compile_but_requires_current_checks(self):
        inputs, context, value = qualification()
        receipt = copy.deepcopy(value['children']['arm64'])
        original = copy.deepcopy(receipt['compile'])
        current = {**context, 'run_id': '124', 'run_attempt': '2'}
        receipt.update(mode='reuse', context=current)
        validate_receipt(receipt, inputs, current, published=True)
        self.assertEqual(receipt['compile'], original)
        receipt['registry']['manifest_digest'] = 'sha256:' + '9' * 64
        with self.assertRaises(ValueError):
            validate_receipt(receipt, inputs, current, published=True)

    def test_lost_qualification_is_failure(self):
        inputs, context, value = qualification()
        with patch('multiarch_qualify.gh', return_value=[{'artifacts': []}]):
            with self.assertRaises(ValueError):
                find_qualification(inputs, 'owner/repo', 'main', value['index_digest'])

    def test_expired_and_pr_artifacts_cannot_supply_proof(self):
        inputs, context, value = qualification()
        artifact = {'id': 1, 'name': 'qualification-' + inputs['build_key'] + '-123-1', 'expired': False,
                    'created_at': (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),
                    'workflow_run': {'id': 123}}
        with patch('multiarch_qualify.gh', return_value=[{'artifacts': [artifact]}]) as api:
            with self.assertRaises(ValueError):
                find_qualification(inputs, 'owner/repo', 'main', value['index_digest'])
            self.assertEqual(api.call_count, 1)
        artifact['created_at'] = datetime.now(timezone.utc).isoformat()
        with patch('multiarch_qualify.gh', side_effect=[[{'artifacts': [artifact]}],
                                                        {'conclusion': 'success', 'head_branch': 'main', 'event': 'pull_request'}]) as api:
            with self.assertRaises(ValueError):
                find_qualification(inputs, 'owner/repo', 'main', value['index_digest'])
            self.assertEqual(api.call_count, 2)


class NativeContractTest(unittest.TestCase):
    def test_readiness_requires_exact_status_and_body(self):
        from multiarch_qualify import exact_no_bot
        body = b'{"ok":false,"error_code":404,"description":"Not Found"}'
        self.assertTrue(exact_no_bot(404, body))
        for status, value in ((200, body), (404, b"not found"), (404, b'{"ok":false}'), (502, body)):
            self.assertFalse(exact_no_bot(status, value))

    def test_receiver_rejects_duplicate_or_wrong_header_and_wrong_nonce(self):
        import importlib.util
        from email.message import Message
        spec = importlib.util.spec_from_file_location('owned_receiver', Path(__file__).parent/'webhook_sender'/'receiver.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        headers = Message(); headers['User-Agent'] = 'WebhookDelivery/1.0'
        body = b'{"update_id":1,"message":{"text":"nonce"}}'
        self.assertTrue(module.valid_delivery('POST','/probe',headers,body,'nonce','WebhookDelivery/1.0'))
        self.assertFalse(module.valid_delivery('POST','/probe',headers,body,'wrong','WebhookDelivery/1.0'))
        headers['User-Agent'] = 'WebhookDelivery/1.0'
        self.assertFalse(module.valid_delivery('POST','/probe',headers,body,'nonce','WebhookDelivery/1.0'))

    def test_sender_negative_control_must_return_failure(self):
        import json, subprocess
        from multiarch_qualify import sender_probe
        checked = {'image_id':'sha256:'+'a'*64,'elf_sha256':'b'*64,'version':'9.2'}
        response = {'status':'PASS','post':True,'user_agent':'WebhookDelivery/1.0','queue_acknowledged':True}
        with patch('multiarch_qualify.verify_local', return_value=checked), patch('multiarch_qualify.command', return_value=json.dumps(response)), patch('multiarch_qualify.subprocess.run', return_value=subprocess.CompletedProcess([],0)):
            with self.assertRaises(ValueError):
                sender_probe('sender','amd64',{},checked)


class RuntimeContentsTest(unittest.TestCase):
    @patch("multiarch_qualify.subprocess.run")
    def test_unresolved_library_or_failed_contents_check_is_rejected(self, cleanup):
        import subprocess
        from multiarch_qualify import runtime_contents
        for output in ('libssl.so: not found','Error loading shared library libstdc++.so'):
            with patch('multiarch_qualify.command',return_value=output), self.assertRaises(ValueError):
                runtime_contents('sha256:'+'a'*64)
        with patch('multiarch_qualify.command',side_effect=subprocess.CalledProcessError(1,['docker'])),self.assertRaises(subprocess.CalledProcessError):
            runtime_contents('sha256:'+'a'*64)
