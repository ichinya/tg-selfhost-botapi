from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import unittest
import json
from unittest.mock import patch

from image_inputs import build_key, checked_base, digest, platforms, revision, validate_base_index
from image_inputs import Registry, resolve_base, canonical, sha256
from image_inputs import SafeRedirect, validate_snapshot, CONTRACT, RECIPE, snapshot_hash, resolve
import copy
import urllib.error


class BuildInputsTest(unittest.TestCase):
    def test_resolver_uses_one_revision_and_checks_ci_and_local_defaults(self):
        mapping = {'linux/amd64': 'sha256:' + 'c' * 64, 'linux/arm64': 'sha256:' + 'd' * 64}
        with patch('image_inputs.revision', return_value='a' * 40) as source, patch('image_inputs.urllib.request.urlopen') as fetch, patch('image_inputs.Registry'), patch('image_inputs.resolve_base', return_value=('sha256:' + 'b' * 64, mapping)) as base:
            fetch.return_value.__enter__.return_value.read.return_value = b'project(TelegramBotApi VERSION 10.3 LANGUAGES CXX)'
            inputs = resolve()
            self.assertEqual(source.call_count, 1)
            self.assertEqual(inputs['base_children'], mapping)
            self.assertEqual(base.call_count, 2)
            self.assertEqual(base.call_args_list[0].args[0], '3.22')
            self.assertTrue(base.call_args_list[1].args[0].startswith('sha256:'))
            validate_snapshot(inputs, snapshot_hash(inputs))

    def test_snapshot_hash_and_recipe_must_match(self):
        from pathlib import Path
        from image_inputs import ROOT
        inputs = {'schema': 2, 'verification_contract': CONTRACT, 'platforms': ['linux/amd64', 'linux/arm64'],
                  'bot_api_revision': 'a' * 40,
                  'alpine_image': 'alpine:3.22@sha256:' + 'b' * 64,
                  'base_children': {'linux/amd64': 'sha256:' + 'c' * 64, 'linux/arm64': 'sha256:' + 'd' * 64}}
        inputs['build_key'] = build_key(inputs, {name: (ROOT / name).read_bytes() for name in RECIPE})
        validate_snapshot(inputs, snapshot_hash(inputs))
        with self.assertRaises(ValueError):
            validate_snapshot(inputs, 'sha256:' + '0' * 64)
        for key, value in (('schema', 1), ('platforms', ['linux/amd64']),
                           ('verification_contract', 'old'), ('bot_api_revision', 'unknown'),
                           ('base_children', {'linux/amd64': 'sha256:' + 'c' * 64})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_snapshot({**inputs, key: value})

    def test_redirect_drops_credentials_and_rejects_http(self):
        import urllib.request
        request = urllib.request.Request('https://ghcr.io/v2/o/i/blobs/sha256:a', headers={'Authorization': 'Bearer placeholder'})
        handler = SafeRedirect()
        result = handler.redirect_request(request, None, 302, '', {}, 'https://cdn.example/blob')
        self.assertIsNone(result.get_header('Authorization'))
        with self.assertRaises(ValueError):
            handler.redirect_request(request, None, 302, '', {}, 'http://cdn.example/blob')

    def test_revision_rejects_missing_or_extra_refs(self):
        for output in ('', 'a' * 40 + ' refs/heads/not-master', 'a' * 40 + ' refs/heads/master extra'):
            with patch('image_inputs.command', return_value=output), self.assertRaises(ValueError):
                revision('tdlib/telegram-bot-api')

    def test_child_and_policy_invalidate_key(self):
        inputs = {'platforms': ['linux/amd64', 'linux/arm64'],
                  'base_children': {'linux/amd64': 'a', 'linux/arm64': 'b'}, 'policy': 'v1'}
        changed = copy.deepcopy(inputs)
        changed['base_children']['linux/arm64'] = 'c'
        self.assertNotEqual(build_key(inputs, {}), build_key(changed, {}))
        self.assertNotEqual(build_key(inputs, {}), build_key({**inputs, 'policy': 'v2'}, {}))

    def test_registry_digest_and_auth_errors_are_not_absence(self):
        registry = Registry('ghcr.io', 'owner/image')
        with patch('image_inputs.registry_open', side_effect=urllib.error.HTTPError('url', 403, 'forbidden', {}, None)):
            with self.assertRaises(RuntimeError):
                registry.manifest('build-test', missing=True)
        with patch('image_inputs.registry_open', side_effect=urllib.error.HTTPError('url', 404, 'missing', {}, None)):
            self.assertIsNone(registry.manifest('build-test', missing=True))
        with patch('image_inputs.registry_open') as fetch:
            response = fetch.return_value.__enter__.return_value
            response.read.return_value = b'{}'
            response.headers.get.return_value = None
            with self.assertRaises(ValueError):
                registry.get('blobs', 'sha256:' + 'a' * 64)

    def test_resolved_base_checks_child_config(self):
        from unittest.mock import Mock
        index = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                 'manifests': [{'platform': {'os': 'linux', 'architecture': arch}, 'digest': 'sha256:' + n * 64}
                               for arch, n in (('amd64', 'a'), ('arm64', 'b'))]}
        child = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                 'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'digest': 'sha256:' + 'c' * 64}}
        registry = Mock()
        registry.manifest.side_effect = [('sha256:' + 'd' * 64, index), ('sha256:' + 'a' * 64, child), ('sha256:' + 'b' * 64, child)]
        registry.get.side_effect = [canonical({'os': 'linux', 'architecture': 'amd64'}), canonical({'os': 'linux', 'architecture': 'amd64'})]
        with self.assertRaises(ValueError):
            resolve_base('3.22', registry)

    def test_platform_order_and_invalid_sets(self):
        inputs = {"platforms": ["linux/arm64", "linux/amd64"], "contract": "native-multiarch-v1"}
        self.assertEqual(build_key(inputs, {}), build_key({**inputs, "platforms": list(reversed(inputs["platforms"]))}, {}))
        self.assertNotEqual(build_key(inputs, {}), build_key({**inputs, "contract": "other"}, {}))
        for value in (["linux/amd64", "linux/amd64"], ["linux/amd64"], ["linux/amd64", "linux/s390x"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                platforms(value)

    def test_base_must_be_complete_index(self):
        def child(arch, number):
            return {"platform": {"os": "linux", "architecture": arch}, "digest": "sha256:" + number * 64, "size":100, "mediaType":"application/vnd.oci.image.manifest.v1+json"}
        index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                 "manifests": [child("amd64", "1"), child("arm64", "2")]}
        validate_base_index(json.dumps(index))
        for manifests in ([child("amd64", "1")], [child("amd64", "1"), child("amd64", "2"), child("arm64", "3")],
                          [child("amd64", "1"), child("arm64", "1")]):
            with self.subTest(manifests=manifests), self.assertRaises(ValueError):
                validate_base_index(json.dumps({**index, "manifests": manifests}))
        with self.assertRaises(ValueError):
            validate_base_index('{}')

    def test_base_inspection_failure_is_not_an_input(self):
        with patch("image_inputs.digest", return_value="sha256:" + "a" * 64), patch("image_inputs.command", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                checked_base("alpine:3.22")
    def test_any_upstream_change_invalidates_published_build(self):
        inputs = dict(source="a", base="b")
        files = {"Dockerfile": b"recipe", "patch": b"header"}
        original = build_key(inputs, files)
        for key in inputs:
            with self.subTest(key=key):
                self.assertNotEqual(original, build_key({**inputs, key: "changed"}, files))
        self.assertNotEqual(original, build_key(inputs, {**files, "patch": b"new header"}))

    def test_order_does_not_force_a_rebuild(self):
        self.assertEqual(build_key(dict(a=1, b=2), dict(x=b"x", y=b"y")),
                         build_key(dict(b=2, a=1), dict(y=b"y", x=b"x")))

    def test_recipe_file_boundaries_are_significant(self):
        self.assertNotEqual(build_key({}, {"a": b"bc"}), build_key({}, {"ab": b"c"}))

    def test_invalid_upstream_values_fail_closed(self):
        with patch("image_inputs.command", return_value="not-a-sha\trefs/heads/master"):
            with self.assertRaises(ValueError):
                revision("tdlib/telegram-bot-api")
        with patch("image_inputs.command", return_value='{"digest": "latest"}'):
            with self.assertRaises(ValueError):
                digest("alpine:3.22")

    def test_network_failure_does_not_produce_new_inputs(self):
        with patch("image_inputs.command", side_effect=TimeoutError("registry timeout")):
            with self.assertRaises(TimeoutError):
                digest("alpine:3.22")


if __name__ == "__main__":
    unittest.main()


class SavedSnapshotContractTest(unittest.TestCase):
    def test_saved_cli_never_resolves_upstream(self):
        from image_inputs import main
        import tempfile,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'saved.json'; path.write_text('{"fixture":true}')
            value={'build_key':'a'*32,'bot_api_revision':'b'*40,'alpine_image':'alpine:3.22@sha256:'+'c'*64,'verification_contract':CONTRACT}
            with patch('image_inputs.resolve',side_effect=AssertionError('must not resolve')),patch('image_inputs.validate_snapshot',return_value=value) as validate,patch.object(sys,'argv',['image_inputs.py','--input',str(path),'--snapshot-hash','expected']),patch('builtins.print'):
                main()
                self.assertEqual(validate.call_args.args,({'fixture':True},'expected'))


class BaseRoundTripTest(unittest.TestCase):
    def test_real_content_hashes_sizes_and_both_configs_are_checked(self):
        from image_inputs import Registry,resolve_base,MANIFEST_TYPES,CONFIG_TYPES,INDEX_TYPES
        blobs={}; descriptors=[]
        for arch in ('amd64','arm64'):
            config=canonical({'os':'linux','architecture':arch})
            config_id=sha256(config); blobs[('blobs',config_id)]=config
            manifest=canonical({'schemaVersion':2,'mediaType':MANIFEST_TYPES[0],
                'config':{'digest':config_id,'size':len(config),'mediaType':CONFIG_TYPES[0]}})
            child=sha256(manifest); blobs[('manifests',child)]=manifest
            descriptors.append({'digest':child,'size':len(manifest),'mediaType':MANIFEST_TYPES[0],
                                'platform':{'os':'linux','architecture':arch}})
        index=canonical({'schemaVersion':2,'mediaType':INDEX_TYPES[0],'manifests':descriptors})
        blobs[('manifests','3.22')]=index
        registry=Registry('example.com','fixture')
        with patch.object(registry,'get',side_effect=lambda kind,ref,**kw:blobs[(kind,ref)]):
            digest,children=resolve_base('3.22',registry)
            self.assertEqual(digest,sha256(index)); self.assertEqual(set(children),{'linux/amd64','linux/arm64'})
            config_key=next(key for key in blobs if key[0]=='blobs')
            blobs[config_key]+=b' '
            with self.assertRaises(ValueError): resolve_base('3.22',registry)
