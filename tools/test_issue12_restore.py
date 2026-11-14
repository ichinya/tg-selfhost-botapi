import copy
import hashlib
import io
import tarfile
import unittest
from check_issue12_restore import validate_backup
from smoke_image import archive_manifest, validate_shutdown
from smoke_image import rehearse_layouts, validate_restore_evidence
from unittest.mock import patch


class RestoreTests(unittest.TestCase):
    def test_both_layout_receipts_are_required(self):
        def evidence(image, gateway, layout):
            return {'layout': layout, 'runtime_smoke': 'PASS', 'restore_rehearsal': 'PASS',
                    'readiness_abort': 'PASS', 'archives_sha256': {
                        name: 'a' * 64 for name in (('state', 'media') if layout == 'nonroot-split' else ('state',))}}
        with patch('smoke_image.runtime', side_effect=evidence) as run:
            record = rehearse_layouts('candidate', 'nginx@sha256:' + 'a' * 64)
            self.assertEqual(run.call_count, 2)
        validate_restore_evidence(record)
        for mutation in ('missing-layout', 'missing-media', 'failed'):
            bad = copy.deepcopy(record)
            if mutation == 'missing-layout': del bad['layouts']['base']
            elif mutation == 'missing-media': del bad['layouts']['nonroot-split']['archives_sha256']['media']
            else: bad['layouts']['base']['readiness_abort'] = 'NOTRUN'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_restore_evidence(bad)

    def test_backup_rejects_aliased_storage(self):
        record, archives = self.fixture('base')
        record['members']['private']['storage_mapping'] = record['members']['state']['storage_mapping']
        with self.assertRaisesRegex(ValueError, 'Aliased'):
            validate_backup(record, archives)

    def archive(self, uid=101, data=b'synthetic-state'):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name in ('.hidden', 'tqueue.binlog', 'webhooks_db.binlog'):
                member = tarfile.TarInfo(name)
                member.uid = member.gid = uid
                member.mode, member.size = 0o600, len(data)
                archive.addfile(member, io.BytesIO(data))
        return stream.getvalue()

    def fixture(self, layout):
        names = ('state', 'private', 'media') if layout == 'nonroot-split' else ('state', 'private')
        archives = {name: self.archive() for name in names}
        record = {'schema': 1, 'snapshot_id': 'a' * 32, 'stopped_cleanly': True,
            'release_receipt_sha256': 'b' * 64, 'config_sha256': 'c' * 64, 'layout': layout,
            'members': {name: {'snapshot_id': 'a' * 32, 'sha256': hashlib.sha256(raw).hexdigest(),
                              'storage_mapping': '/private/' + name} for name, raw in archives.items()}}
        return record, archives

    def test_both_layouts_preserve_hidden_files_and_numeric_identity(self):
        for layout in ('base', 'nonroot-split'):
            record, archives = self.fixture(layout)
            before = validate_backup(record, archives)
            self.assertEqual(before, validate_backup(copy.deepcopy(record), dict(archives)))
            self.assertIn('.hidden', before['state'])
            self.assertNotEqual(archive_manifest(self.archive(uid=0)), before['state'])
            self.assertNotEqual(archive_manifest(self.archive(data=b'new-state')), before['state'])

    def test_mixed_incomplete_forced_or_corrupt_snapshot_fails(self):
        record, archives = self.fixture('nonroot-split')
        for mutation in ('mixed', 'missing', 'forced', 'corrupt'):
            bad, data = copy.deepcopy(record), dict(archives)
            if mutation == 'mixed': bad['members']['media']['snapshot_id'] = 'd' * 32
            elif mutation == 'missing': del data['media']
            elif mutation == 'forced': bad['stopped_cleanly'] = False
            else: data['state'] = self.archive(data=b'changed')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_backup(bad, data)

    def test_sigkill_oom_and_unobserved_stop_cannot_authorize_backup(self):
        state = {'Running': False, 'OOMKilled': False, 'ExitCode': 0}
        good = [{'Action': 'kill', 'Actor': {'Attributes': {'signal': '15'}}},
                {'Action': 'die', 'Actor': {'Attributes': {'exitCode': '0'}}}]
        validate_shutdown(good, state)
        for events in ([], good[:1], good + [{'Action': 'oom'}],
                       [{'Action': 'kill', 'Actor': {'Attributes': {'signal': '9'}}}, good[1]]):
            with self.assertRaises(ValueError): validate_shutdown(events, state)
