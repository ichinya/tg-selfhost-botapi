import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
"""Exercise publication decisions and external action order with a fake registry."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from image_inputs import sha256
from multiarch_qualify import file_hash
from multiarch_publish import qualify, promote
from test_multiarch_qualify import fixtures

SUCCESS = {'prepare': 'success', 'native': 'success'}
INDEX = 'application/vnd.oci.image.index.v1+json'
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'


class FakeBackend:
    def __init__(self, pair):
        self.calls, self.values, self.remote_values = [], {}, {}
        self.pair = pair
        self.fault = None

    def read(self, tag, missing=False):
        self.calls.append(('read', tag))
        if self.fault == 'auth':
            raise RuntimeError('auth error')
        if tag not in self.values:
            if missing:
                return None
            raise ValueError('missing reference')
        return copy.deepcopy(self.values[tag])

    def load(self, archive, receipt, inputs):
        self.calls.append(('load', receipt['platform']))
        if self.fault == 'load':
            raise ValueError('config mismatch after load')

    def push(self, tag, receipt):
        self.calls.append(('push', tag))
        arch = receipt['platform'].split('/')[1]
        if self.fault == 'push' and arch == 'arm64':
            raise RuntimeError('candidate push failed')
        child = 'sha256:' + (('a' if arch == 'amd64' else 'b') if tag.endswith('-sender') else ('5' if arch == 'amd64' else '6')) * 64
        self.remote_values[child] = {'manifest_digest': child, 'config_digest': receipt['local']['image_id'], 'manifest_size':100}
        return child

    def remote(self, child, arch, inputs, config_id):
        self.calls.append(('remote', arch))
        value = self.remote_values[child]
        if self.fault == 'config' or value['config_digest'] != config_id:
            raise ValueError('remote config mismatch')
        return copy.deepcopy(value)

    def create(self, tag, sources):
        self.calls.append(('create', tag, list(sources)))
        if self.fault == 'latest_timeout' and tag == 'latest':
            raise TimeoutError('unknown registry write result')
        if len(sources) == 2:
            manifests = [{'mediaType': MANIFEST, 'digest': child, 'size': 100, 'platform': {'os': 'linux', 'architecture': arch}}
                         for arch, child in zip(('amd64', 'arm64'), sources)]
            if self.fault == 'incomplete':
                manifests.pop()
            index = {'schemaVersion': 2, 'mediaType': INDEX, 'manifests': manifests}
            digest = sha256(json.dumps(index, sort_keys=True).encode())
            value = (digest, index)
            self.values[digest] = value
        else:
            value = self.values[sources[0]]
        self.values[tag] = value
        if self.fault == 'latest_timeout_after_write' and tag == 'latest':
            raise TimeoutError('write committed but response lost')

    def release_writes(self):
        return [call for call in self.calls if call[0] == 'create' and (call[1] == 'latest' or call[1].startswith('build-'))]


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.inputs, self.context, self.pair = fixtures()
        for arch, receipt in self.pair.items():
            path = self.directory / arch
            path.mkdir()
            (path / 'image.tar').write_bytes((arch + '-image').encode())
            receipt['archive_sha256'] = file_hash(path / 'image.tar')
            (path / 'sender.tar').write_bytes((arch + '-sender').encode())
            receipt['sender']['archive_sha256'] = file_hash(path / 'sender.tar')
        self.backend = FakeBackend(self.pair)

    def qualify(self):
        return qualify(self.backend, self.inputs, list(self.pair.values()), self.context, SUCCESS,
                       'main', self.directory, {'mode': 'build'})

    def promote(self, value, promotion):
        return promote(self.backend, self.inputs, value, promotion, self.context, SUCCESS, 'main', self.directory / 'report.json')

    def test_matrix_failures_and_pr_make_no_writes(self):
        for status in ('failure', 'skipped', 'cancelled', 'UNKNOWN'):
            with self.subTest(status=status), self.assertRaises(ValueError):
                qualify(self.backend, self.inputs, list(self.pair.values()), self.context,
                        {'prepare': 'success', 'native': status}, 'main', self.directory, {'mode': 'build'})
        for context in ({**self.context, 'event': 'pull_request'}, {**self.context, 'branch': 'feature'}):
            with self.assertRaises(ValueError):
                qualify(self.backend, self.inputs, list(self.pair.values()), context, SUCCESS, 'main', self.directory, {'mode': 'build'})
        self.assertEqual(self.backend.calls, [])

    def test_success_qualifies_before_release_and_promotes_same_index(self):
        value, promotion = self.qualify()
        self.assertEqual(self.backend.release_writes(), [])
        self.assertEqual({c[1].split('-')[-2] for c in self.backend.calls if c[0] == 'push' and not c[1].endswith('-sender')}, {'123'})
        report = self.promote(value, promotion)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(self.backend.values['latest'][0], value['index_digest'])
        writes = self.backend.release_writes()
        self.assertEqual([c[1] for c in writes], ['build-' + self.inputs['build_key'], 'latest'])
        self.assertTrue(all(c[2] == [value['index_digest']] for c in writes))

    def test_archive_or_receipt_substitution_prevents_all_mutations(self):
        (self.directory / 'arm64' / 'image.tar').write_bytes(b'substituted')
        with self.assertRaises(ValueError):
            self.qualify()
        self.assertEqual(self.backend.calls, [])
        self.pair['arm64']['context']['run_attempt'] = '2'
        with self.assertRaises(ValueError):
            self.qualify()
        self.assertEqual(self.backend.calls, [])

    def test_errors_before_staging_gate_never_write_release(self):
        for fault in ('load', 'push', 'config', 'incomplete', 'auth'):
            self.backend = FakeBackend(self.pair)
            self.backend.fault = fault
            with self.subTest(fault=fault), self.assertRaises((ValueError, RuntimeError)):
                self.qualify()
            self.assertEqual(self.backend.release_writes(), [])

    def test_existing_build_collision_does_not_repair_tag(self):
        self.backend.values['build-' + self.inputs['build_key']] = ('sha256:' + '8' * 64, {})
        with self.assertRaises(ValueError):
            self.qualify()
        self.assertEqual(self.backend.release_writes(), [])
        self.assertFalse(any(c[0] == 'push' for c in self.backend.calls))

    def test_current_attempt_is_required_at_promotion(self):
        value, promotion = self.qualify()
        promotion['context'] = {**self.context, 'run_attempt': '2'}
        with self.assertRaises(ValueError):
            self.promote(value, promotion)
        self.assertEqual(self.backend.release_writes(), [])

    def test_unknown_promotion_is_reported_without_rollback(self):
        value, promotion = self.qualify()
        self.backend.fault = 'latest_timeout'
        with self.assertRaises(ValueError):
            self.promote(value, promotion)
        report = json.loads((self.directory / 'report.json').read_text())
        self.assertEqual(report['status'], 'UNKNOWN')
        self.assertEqual(report['rollback'], 'NOTRUN')
        self.assertEqual(len(self.backend.release_writes()), 2)

    def test_ambiguous_write_is_reconciled_by_read(self):
        value, promotion = self.qualify()
        self.backend.fault = 'latest_timeout_after_write'
        report = self.promote(value, promotion)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['write_response'], 'error_reconciled')

    def test_reuse_keeps_compile_evidence_and_does_not_rebuild_or_push(self):
        value, promotion = self.qualify()
        self.promote(value, promotion)
        original = copy.deepcopy(value)
        current = {**self.context, 'run_id': '124', 'run_attempt': '2'}
        receipts = copy.deepcopy(list(value['children'].values()))
        for receipt in receipts:
            receipt.update(context=current, mode='reuse')
        self.backend.calls = []
        new, promotion = qualify(self.backend, self.inputs, receipts, current, SUCCESS, 'main', self.directory,
                                 {'mode': 'reuse', 'qualification': original})
        self.assertFalse(any(c[0] in ('push', 'create') for c in self.backend.calls))
        for arch in ('amd64', 'arm64'):
            self.assertEqual(new['children'][arch]['compile'], original['children'][arch]['compile'])
        promote(self.backend, self.inputs, new, promotion, current, SUCCESS, 'main', self.directory / 'report.json')

    def test_external_latest_change_blocks_promotion(self):
        value, promotion = self.qualify()
        self.backend.values['latest'] = ('sha256:' + '8' * 64, {})
        with self.assertRaises(ValueError):
            self.promote(value, promotion)
        self.assertFalse(any(c[0] == 'create' and c[1] == 'latest' for c in self.backend.calls))


class ExtraPublicationFaultTest(unittest.TestCase):
    setUp = PublishTest.setUp
    qualify = PublishTest.qualify
    def test_substituted_sender_archive_prevents_all_writes(self):
        (self.directory/'arm64'/'sender.tar').write_bytes(b'wrong-sender')
        with self.assertRaises(ValueError):
            self.qualify()
        self.assertEqual(self.backend.calls, [])

    def test_stale_or_wrong_actions_origin_is_rejected(self):
        from unittest.mock import patch
        from multiarch_publish import verify_current_head
        context = self.context
        commit = {'object': {'sha': context['sha']}}
        run = {'head_sha':context['sha'],'head_branch':'main','event':'push',
               'path':context['workflow'],'run_attempt':1,'repository':{'full_name':context['repository']}}
        with patch('multiarch_publish.subprocess.check_output',side_effect=[json.dumps(commit).encode(),json.dumps(run).encode()]):
            verify_current_head(context,'main')
        for bad in ({**run,'head_sha':'0'*40},{**run,'event':'pull_request'},{**run,'run_attempt':2}):
            with patch('multiarch_publish.subprocess.check_output',side_effect=[json.dumps(commit).encode(),json.dumps(bad).encode()]), self.assertRaises(ValueError):
                verify_current_head(context,'main')
        with patch('multiarch_publish.subprocess.check_output',side_effect=[json.dumps({'object':{'sha':'0'*40}}).encode(),json.dumps(run).encode()]), self.assertRaises(ValueError):
            verify_current_head(context,'main')

    def test_swapped_version_or_missing_sender_never_reaches_registry(self):
        for mutation in ('version','sender','policy','source'):
            bad = copy.deepcopy(self.pair)
            if mutation == 'version': bad['arm64']['local']['version'] = '1.0'
            elif mutation == 'sender': bad['arm64']['sender']['negative'] = 'NOTRUN'
            elif mutation == 'source': bad['arm64']['local']['source']['patch_sha256'] = 'sha256:'+'0'*64
            else: bad['arm64']['contract'] = 'old'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                qualify(self.backend,self.inputs,list(bad.values()),self.context,SUCCESS,'main',self.directory,{'mode':'build'})
            self.assertEqual(self.backend.calls,[])
