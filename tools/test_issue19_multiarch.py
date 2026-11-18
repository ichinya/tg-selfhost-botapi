import copy
import json
import struct
import subprocess
import unittest
from unittest.mock import patch

from multiarch_publish import promote, validate_pair
from multiarch_verify import verify_elf
class PairTests(unittest.TestCase):
    def test_exact_pair_and_rejections(self):
        pair=[dict(architecture=arch,sha='a'*40,run_id='1',inputs={'source':'s','build_key':arch,'platform':'linux/'+arch},components={role:'ghcr.io/example/api@sha256:'+'a'*64 for role in ('botapi','observer','downloads')},native=True,qualified=True) for arch in ('amd64','arm64')]
        validate_pair(pair,'a'*40,'1')
        for change in ('sha','native','inputs','components'):
            bad=copy.deepcopy(pair)
            bad[1][change]={'sha':'b'*40,'native':False,'inputs':{'source':'other'},'components':{}}[change]
            with self.subTest(change=change),self.assertRaises(ValueError): validate_pair(bad,'a'*40,'1')

    def test_native_elf_rejects_wrong_architecture(self):
        header = bytearray(64)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<H', header, 18, 183)
        struct.pack_into('<I', header, 20, 1)
        struct.pack_into('<H', header, 52, 64)
        binary = header + b'WebhookDelivery/1.0\0'
        verify_elf(binary, 'arm64')
        with self.assertRaisesRegex(ValueError, 'architecture mismatch'):
            verify_elf(binary, 'amd64')

    def test_invalid_later_index_leaves_all_release_tags_untouched(self):
        image = 'ghcr.io/example/api'
        manifests = []
        receipts = []
        for architecture, value in (('amd64', 'a'), ('arm64', 'b')):
            digest = 'sha256:' + value * 64
            manifests.append({'digest': digest, 'platform': {'os': 'linux', 'architecture': architecture},
                              'mediaType': 'application/vnd.oci.image.manifest.v1+json'})
            receipts.append({'architecture': architecture, 'components': {
                role: image + '@' + digest for role in ('botapi', 'observer', 'downloads')}})
        index = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                 'manifests': manifests}

        def buildx(command, **kwargs):
            value = {**index, 'manifests': manifests[:1]} if '-downloads:latest' in command[5] else index
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(value))

        with patch('multiarch_publish.subprocess.run', side_effect=buildx) as run:
            with self.assertRaisesRegex(ValueError, 'two runnable manifests'):
                promote(receipts, image)
            self.assertEqual(run.call_count, 3)
            self.assertTrue(all('--dry-run' in call.args[0] for call in run.call_args_list))
