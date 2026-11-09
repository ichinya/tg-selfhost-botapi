from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import struct
import unittest
from unittest.mock import patch
import subprocess

from multiarch_verify import (verify_elf, verify_release_index, verify_config, verify_local,
                                verify_remote, verify_version, native_host)
from image_inputs import canonical, sha256
import copy
import json
from unittest.mock import Mock
from pathlib import Path

INDEX_TYPE = "application/vnd.oci.image.index.v1+json"


def descriptor(arch, number, variant=None):
    platform = {"os": "linux", "architecture": arch}
    if variant:
        platform["variant"] = variant
    return {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "sha256:" + number * 64, "size": 100, "platform": platform}


class VerifyImageTest(unittest.TestCase):
    def test_elf_architecture_and_user_agent(self):
        elf = bytearray(b"\x7fELF\x02\x01\x01" + b"\0" * 57 + b"WebhookDelivery/1.0\0")
        struct.pack_into("<I", elf, 20, 1)
        struct.pack_into("<H", elf, 52, 64)
        struct.pack_into("<H", elf, 18, 183)
        self.assertEqual(len(verify_elf(elf, "arm64")), 64)
        with self.assertRaises(ValueError):
            verify_elf(elf, "amd64")
        with self.assertRaises(ValueError):
            verify_elf(elf[:20], "arm64")
        with self.assertRaises(ValueError):
            verify_elf(b"bad", "arm64")
        with self.assertRaises(ValueError):
            verify_elf(elf[:-1] + b'0\0', 'arm64')

    def test_index_requires_exact_platforms_and_digests(self):
        amd, arm = descriptor("amd64", "a"), descriptor("arm64", "b", "v8")
        index = {"schemaVersion": 2, "mediaType": INDEX_TYPE, "manifests": [amd, arm]}
        expected = {"amd64": amd["digest"], "arm64": arm["digest"]}
        self.assertEqual(verify_release_index(index, expected), expected)
        for manifests in ([amd], [amd, amd, arm], [amd, descriptor("arm64", "b", "v7")]):
            with self.subTest(manifests=manifests), self.assertRaises(ValueError):
                verify_release_index({"schemaVersion": 2, "mediaType": INDEX_TYPE, "manifests": manifests})
        with self.assertRaises(ValueError):
            verify_release_index({"schemaVersion": 2, "manifests": [amd, arm]})
        with self.assertRaises(ValueError):
            verify_release_index(index, {"amd64": amd["digest"], "arm64": amd["digest"]})
        cases = [[arm], [amd, amd], [amd, arm, descriptor('s390x', 'c')],
                 [amd, {**arm, 'platform': {'os': 'windows', 'architecture': 'arm64'}}],
                 [amd, {**arm, 'digest': 'latest'}], [amd, {**arm, 'mediaType': INDEX_TYPE}],
                 [amd, {**arm, 'platform': {'os': 'unknown', 'architecture': 'unknown'}}]]
        for manifests in cases:
            with self.subTest(manifests=manifests), self.assertRaises(ValueError):
                verify_release_index({**index, 'manifests': manifests})

    def test_release_excludes_all_attestations(self):
        amd, arm = descriptor("amd64", "a"), descriptor("arm64", "b")
        att = {"digest": "sha256:" + "c" * 64,
               "platform": {"os": "unknown", "architecture": "unknown"},
               "annotations": {"vnd.docker.reference.type": "attestation-manifest",
                               "vnd.docker.reference.digest": amd["digest"]}}
        with self.assertRaises(ValueError):
            verify_release_index({"schemaVersion": 2, "mediaType": INDEX_TYPE, "manifests": [amd, arm, att]})
        att["annotations"]["vnd.docker.reference.digest"] = "sha256:" + "d" * 64
        with self.assertRaises(ValueError):
            verify_release_index({"schemaVersion": 2, "mediaType": INDEX_TYPE, "manifests": [amd, arm, att]})
        del att["annotations"]
        with self.assertRaises(ValueError):
            verify_release_index({"schemaVersion": 2, "mediaType": INDEX_TYPE, "manifests": [amd, arm, att]})


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.inputs = {"bot_api_revision": "a" * 40, "alpine_image": "alpine@sha256:" + "b" * 64,
                       "build_key": "c" * 32, "verification_contract": "native-multiarch-v1",
                       "platforms": ["linux/amd64", "linux/arm64"]}
        self.inputs['expected_version'] = '9.2'
        self.labels = {"org.opencontainers.image.source": "https://github.com/ichinya/tg-selfhost-botapi",
                       "io.tg-selfhost.bot-api-revision": self.inputs["bot_api_revision"],
                       "io.tg-selfhost.base-reference": self.inputs["alpine_image"],
                       "io.tg-selfhost.build-key": self.inputs["build_key"],
                       "io.tg-selfhost.verification-contract": self.inputs["verification_contract"],
                       "io.tg-selfhost.platform-set": "linux/amd64,linux/arm64"}
        self.config = {"Os": "linux", "Architecture": "amd64", "Config": {"Labels": self.labels}, "RootFS": {"Layers": ["sha256:"+"f"*64]}}

    def test_all_labels_and_platform_are_required(self):
        verify_config(self.config, "amd64", self.inputs)
        for key in list(self.labels):
            original = self.labels[key]
            self.labels[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_config(self.config, "amd64", self.inputs)
            self.labels[key] = original
        for key in ("Os", "Architecture"):
            original = self.config[key]
            self.config[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_config(self.config, "amd64", self.inputs)
            self.config[key] = original

    @patch("multiarch_verify.native_host", return_value={"host": "amd64", "daemon": "amd64", "os": "linux"})
    @patch("multiarch_verify.command")
    def test_malformed_inspection_and_timeout_fail(self, run, native):
        run.return_value = "not json"
        with self.assertRaises(ValueError):
            verify_local("image", "amd64", self.inputs)
        run.side_effect = subprocess.TimeoutExpired("docker", 120)
        with self.assertRaises(subprocess.TimeoutExpired):
            verify_local("image", "amd64", self.inputs)

    def test_remote_config_hash_platform_and_tested_id(self):
        raw = canonical({'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': self.labels}, 'rootfs': {'type':'layers','diff_ids':['sha256:'+'f'*64]}})
        config_id = sha256(raw)
        child = 'sha256:' + 'd' * 64
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'config': {'digest': config_id, 'mediaType': 'application/vnd.oci.image.config.v1+json', 'size': len(raw)}}
        registry = Mock()
        registry.manifest_sizes = {child: 100}
        registry.manifest.return_value = (child, manifest)
        registry.get.return_value = raw
        self.assertEqual(verify_remote(registry, child, 'amd64', self.inputs, config_id)['config_digest'], config_id)
        with self.assertRaises(ValueError):
            verify_remote(registry, child, 'amd64', self.inputs, 'sha256:' + 'e' * 64)
        for field, value in (('mediaType', INDEX_TYPE), ('schemaVersion', 1)):
            bad = copy.deepcopy(manifest)
            bad[field] = value
            registry.manifest.return_value = (child, bad)
            with self.assertRaises(ValueError):
                verify_remote(registry, child, 'amd64', self.inputs, config_id)
        registry.manifest_sizes = {child: 100}
        registry.manifest.return_value = (child, manifest)
        registry.get.return_value = raw + b' '
        with self.assertRaises(ValueError):
            verify_remote(registry, child, 'amd64', self.inputs, config_id)
        registry.get.return_value = raw
        with self.assertRaises(ValueError):
            verify_remote(registry, child, 'arm64', self.inputs, config_id)

    def test_local_runs_exact_tested_id_and_removes_extraction_container(self):
        image_id, container = 'sha256:' + 'd' * 64, 'e' * 64
        self.config['Id'] = image_id
        data = bytearray(b'\x7fELF\x02\x01\x01' + b'\0' * 57 + b'WebhookDelivery/1.0\0')
        struct.pack_into('<I', data, 20, 1)
        struct.pack_into('<H', data, 52, 64)
        struct.pack_into('<H', data, 18, 62)
        def run(*args):
            if args[:3] == ('docker', 'image', 'inspect'):
                return json.dumps([self.config])
            if args[:2] == ('docker', 'create'):
                self.assertEqual(args[-1], image_id)
                return container
            if args[:2] == ('docker', 'cp'):
                if args[-2].endswith('source-identity.txt'):
                    from image_inputs import ROOT
                    digest = sha256((ROOT/'patches/webhook-user-agent.patch').read_bytes()).split(':')[1]
                    Path(args[-1]).write_text(self.inputs['bot_api_revision']+'\n'+digest+'  /tmp/webhook-user-agent.patch\n '+'a'*40+' td (pinned)\n')
                else:
                    Path(args[-1]).write_bytes(data)
            return ''
        native = {'host': 'amd64', 'daemon': 'amd64', 'os': 'linux'}
        with patch('multiarch_verify.native_host', return_value=native), patch('multiarch_verify.command', side_effect=run) as commands, patch('multiarch_verify.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Bot API 9.2\n', '')) as executed:
            result = verify_local('moving-tag', 'amd64', self.inputs)
            self.assertEqual(result['image_id'], image_id)
            self.assertTrue(any(c.args[0][-2:] == [image_id, '--version'] for c in executed.call_args_list))
            self.assertTrue(any(c.args[0][:3] == ['docker','rm','-f'] and c.args[0][3].startswith('issue22-extract-') for c in executed.call_args_list))
            struct.pack_into('<H', data, 18, 183)
            commands.reset_mock()
            with self.assertRaises(ValueError):
                verify_local('moving-tag', 'amd64', self.inputs)
            self.assertTrue(any(c.args[0][:3] == ['docker','rm','-f'] and c.args[0][3].startswith('issue22-extract-') for c in executed.call_args_list))

    def test_native_cpu_and_version_are_required(self):
        verify_version('Bot API 9.2\n', '9.2')
        for output in ('', 'Bot API 9.1', 'unrelated 9.2', 'Bot API 9.2.1', 'Bot API 9.2\nextra'):
            with self.assertRaises(ValueError):
                verify_version(output, '9.2')
        with patch('multiarch_verify.platform.system', return_value='Linux'), patch('multiarch_verify.platform.machine', return_value='x86_64'), patch('multiarch_verify.command', return_value=json.dumps({'OSType': 'linux', 'Architecture': 'aarch64'})):
            with self.assertRaises(ValueError):
                native_host('arm64')


class AdditionalIdentityTest(unittest.TestCase):
    def test_descriptor_sizes_are_required_positive_integers(self):
        index = {'schemaVersion':2,'mediaType':INDEX_TYPE,'manifests':[descriptor('amd64','a'),descriptor('arm64','b')]}
        for size in (None,0,-1,True,'100'):
            bad=copy.deepcopy(index); bad['manifests'][1]['size']=size
            with self.subTest(size=size),self.assertRaises(ValueError): verify_release_index(bad)

    def test_source_metadata_binds_revision_patch_and_clean_submodules(self):
        from image_inputs import ROOT
        from multiarch_verify import validate_source_identity
        inputs={'bot_api_revision':'a'*40}
        patch_hash=sha256((ROOT/'patches/webhook-user-agent.patch').read_bytes()).split(':')[1]
        text='a'*40+'\n'+patch_hash+'  /tmp/webhook-user-agent.patch\n '+'b'*40+' td (pinned)\n'
        self.assertEqual(validate_source_identity(text,inputs)['revision'],'a'*40)
        for wrong in (text.replace('a'*40,'c'*40,1),text.replace(patch_hash,'0'*64),text.replace(' '+'b'*40,'+'+'b'*40),text.splitlines()[0]):
            with self.assertRaises(ValueError): validate_source_identity(wrong,inputs)
