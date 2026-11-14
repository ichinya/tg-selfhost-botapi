import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_inputs import build_key, digest, revision


class SavedInputsTest(unittest.TestCase):
    def test_locked_base_images_reject_shell_substitutions(self):
        import json
        from image_inputs import ROOT, validate_lock
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text(encoding='utf8'))
        for field in ('observer_base', 'python_image'):
            for name in ('python:$(id)', 'python:`id`'):
                with self.subTest(field=field, name=name):
                    record['inputs'][field] = name + '@sha256:' + 'a' * 64
                    with self.assertRaises(ValueError):
                        validate_lock(record)

    def test_gateway_change_only_invalidates_qualification(self):
        import copy
        import json
        from image_inputs import ROOT, resolve, validate_lock
        before = resolve()
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text())
        record['discovery']['nginx_candidate_image'] = 'nginx:alpine@sha256:' + 'f' * 64
        record['discovery']['nginx_amd64_digest'] = 'sha256:' + 'e' * 64
        with patch('image_inputs.Path.read_text', return_value=json.dumps(record)), \
             patch('image_inputs.read_policy', return_value=record['apk_policy']):
            after = resolve()
        self.assertEqual(before['build_key'], after['build_key'])
        self.assertNotEqual(before['qualification_key'], after['qualification_key'])
        for schema in (True, 2, None):
            bad = copy.deepcopy(record)
            bad['schema'] = schema
            with self.assertRaises(ValueError): validate_lock(bad)

    def test_version_extractor_rejects_missing_or_ambiguous_version(self):
        from image_inputs import extract_source_version
        source = 'project(TelegramBotApi VERSION 10.3 LANGUAGES CXX)'
        self.assertEqual(extract_source_version(source), '10.3')
        for invalid in ('project(other VERSION 1.0)', source + '\n' + source):
            with self.assertRaises(ValueError):
                extract_source_version(invalid)

    def test_explicit_wrapper_candidate_retains_saved_upstream_inputs(self):
        import json
        from image_inputs import ROOT, save_wrapper_candidate
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text())
        with patch('image_inputs.Path.read_text', return_value=json.dumps(record)), \
             patch('image_inputs.require_committed_recipe'), \
             patch('image_inputs.checkout_revision', return_value='a' * 40), \
             patch('image_inputs.Path.write_text') as write:
            save_wrapper_candidate('saved.json', 'candidate.json')
        saved = json.loads(write.call_args.args[0])
        original = record['inputs'].copy()
        original['wrapper_revision'] = 'a' * 40
        self.assertEqual(saved['inputs'], original)
        self.assertIsNone(saved['selected_release'])

    def test_discovery_captures_utc_once(self):
        import json
        from datetime import datetime, timezone
        from image_inputs import ROOT, resolve, save_discovery
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text())
        candidate = resolve()
        observed = datetime(2026, 11, 8, tzinfo=timezone.utc)
        with patch('image_inputs.datetime') as clock, \
             patch('image_inputs.resolve', return_value=candidate) as resolver, \
             patch('image_inputs.registry_candidate', return_value=(record['discovery']['alpine_index_digest'], record['discovery']['alpine_amd64_digest'])), \
             patch('image_inputs.Path.write_text'):
            clock.now.return_value = observed
            save_discovery('candidate.json')
            clock.now.assert_called_once_with(timezone.utc)
            resolver.assert_called_once_with('discovery', observed_at=observed)

    def test_discovery_roundtrip_preserves_dynamic_nginx(self):
        import io
        import json
        import tempfile
        from datetime import datetime, timezone
        from image_inputs import ROOT, resolve, save_discovery
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text(encoding='utf8'))
        policy = record['apk_policy']
        observed = datetime.fromisoformat(record['discovery']['observed_date']).replace(tzinfo=timezone.utc)
        responses = [io.BytesIO(b'project(TelegramBotApi VERSION 99.1 LANGUAGES CXX)'),
                     io.BytesIO(json.dumps({'release_branches': [{'rel_branch': 'v' + policy['stable_branch'], 'eol_date': '2099-01-01'}]}).encode())]
        index = 'sha256:' + 'b' * 64
        child = 'sha256:' + 'c' * 64
        discovered = []
        def capture(*args, **kwargs):
            result = resolve(*args, **kwargs)
            discovered.append(result)
            return result
        with tempfile.TemporaryDirectory() as tmp, patch('image_inputs.resolve', side_effect=capture), \
             patch('image_inputs.datetime') as clock, \
             patch('image_inputs.require_committed_recipe'), patch('image_inputs.revision', return_value='a' * 40), patch('image_inputs.checkout_revision', return_value='d' * 40), \
             patch('image_inputs.submodules', return_value={'td': 'e' * 40}), \
             patch('image_inputs.digest', return_value=index), patch('image_inputs.registry_candidate', return_value=(index, child)) as registry, \
             patch('image_inputs.urlopen', side_effect=responses), patch('image_inputs.subprocess.run'), \
             patch('image_inputs.nginx_version', return_value='1.99.2'):
            clock.now.return_value = observed
            path = Path(tmp) / 'inputs.json'
            saved = save_discovery(path)
            replay = resolve(inputs_file=path)
            self.assertEqual(saved['discovery']['nginx_version'], '1.99.2')
            self.assertEqual(replay['nginx_version'], '1.99.2')
            self.assertEqual(replay['nginx_image'], 'nginx:alpine@' + index)
            self.assertEqual(replay, discovered[0])
            registry.assert_any_call('nginx:alpine')

    def test_locked_replay_and_public_projection(self):
        from image_inputs import resolve, build_environment, public_environment
        with patch('image_inputs.command', side_effect=AssertionError('offline replay')):
            inputs = resolve()
        env = build_environment(inputs)
        self.assertEqual(env['WRAPPER_REVISION'], inputs['wrapper_revision'])
        self.assertEqual(env['APK_REFRESH_ID'], inputs['apk_refresh_id'])
        self.assertNotEqual(inputs['wrapper_revision'], inputs['bot_api_revision'])
        public = public_environment(inputs)
        self.assertEqual(public['BOTAPI_IMAGE'], 'tg-selfhost-botapi:local')
        self.assertEqual(public['GATEWAY_IMAGE'], inputs['nginx_image'])
        self.assertEqual(public['BUILD_JOBS'], '1')

    def test_bad_lock_and_refresh_changes(self):
        import copy
        import json
        from image_inputs import ROOT, resolve, validate_lock, refresh_id
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text())
        original = resolve()
        for field, value in [('platform', 'linux/arm64'), ('wrapper_revision', 'local'),
                             ('apk_refresh_window', '2026-W45'), ('apk_refresh_generation', True),
                             ('apk_refresh_id', 'unrelated')]:
            bad = copy.deepcopy(record)
            bad['inputs'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_lock(bad)
        version = original['apk_policy_version']
        for version, day, generation in [(version, '2026-11-09', 0), (version, '2026-11-08', 1), (version + 1, '2026-11-08', 0)]:
            changed = {**original, 'apk_refresh_id': refresh_id(version, day, generation)}
            self.assertNotEqual(build_key(original, {}), build_key(changed, {}))
        self.assertNotEqual(build_key(original, {}), build_key({**original, 'platform': 'linux/arm64'}, {}))

    def test_observation_date_is_not_a_build_input(self):
        import json
        from image_inputs import ROOT, resolve
        original = resolve()
        record = json.loads((ROOT / 'image-inputs.lock.json').read_text())
        record['discovery']['observed_date'] = '2026-11-10'
        with patch('image_inputs.Path.read_text', return_value=json.dumps(record)):
            # Policy is an independent file, so pin it while replacing the lock reader.
            with patch('image_inputs.read_policy', return_value=record['apk_policy']):
                self.assertEqual(original, resolve())


class CandidateRegressionTest(unittest.TestCase):
    def test_locked_recipe_change_changes_key_without_network_discovery(self):
        import json
        import tempfile
        from image_inputs import ROOT, resolve, save_wrapper_candidate
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = root / 'Dockerfile'
            recipe.write_bytes(b'first recipe')
            source = ROOT / 'image-inputs.lock.json'
            candidate = root / 'candidate.json'
            policy = json.loads(source.read_text(encoding='utf8'))['apk_policy']
            with patch('image_inputs.ROOT', root), patch('image_inputs.RECIPE', ('Dockerfile',)), \
                 patch('image_inputs.DOWNLOADS_RECIPE', ('Dockerfile',)), \
                 patch('image_inputs.recipe_files', side_effect=lambda: {'Dockerfile': recipe.read_bytes()}), \
                 patch('image_inputs.read_policy', return_value=policy), \
                 patch('image_inputs.checkout_revision', return_value='a' * 40), \
                 patch('image_inputs.require_committed_recipe'):
                save_wrapper_candidate(source, candidate)
                before = resolve(inputs_file=candidate)['build_key']
                recipe.write_bytes(b'changed recipe')
                self.assertNotEqual(resolve(inputs_file=candidate)['build_key'], before)
                save_wrapper_candidate(candidate, candidate)
                self.assertEqual(resolve(inputs_file=candidate)['wrapper_revision'], 'a' * 40)

    def test_capture_rejects_uncommitted_recipe(self):
        import subprocess
        from image_inputs import require_committed_recipe
        with patch('image_inputs.subprocess.run', side_effect=[None, subprocess.CalledProcessError(1, 'git diff')]):
            with self.assertRaisesRegex(ValueError, 'Commit recipe changes'):
                require_committed_recipe()

    def test_capture_checks_all_discovered_recipe_files(self):
        from image_inputs import require_committed_recipe
        files = {'Dockerfile': b'', 'tools/observability/extra.py': b'',
                 'tools/webhook_sender/extra.cpp': b''}
        with patch('image_inputs.recipe_files', return_value=files), \
             patch('image_inputs.subprocess.run') as run:
            require_committed_recipe()
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(set(args[args.index('--') + 1:]), set(files))

    def test_qualify_logs_in_before_registry_access(self):
        from image_inputs import ROOT
        workflow = (ROOT / '.github/workflows/image.yml').read_text(encoding='utf8')
        qualify = workflow.split('  image:', 1)[1]
        login = qualify.index('uses: docker/login-action@v4')
        self.assertLess(login, qualify.index('Check previously published build'))
        self.assertLess(login, qualify.index('docker pull'))
        self.assertIn('registry: ghcr.io', qualify[login:])
        self.assertIn('username: ${{ github.actor }}', qualify[login:])
        self.assertIn('password: ${{ secrets.GITHUB_TOKEN }}', qualify[login:])


class BuildInputsTest(unittest.TestCase):
    def test_any_upstream_change_invalidates_published_build(self):
        inputs = dict(source="a", base="b")
        files = {"Dockerfile": b"recipe", "patch": b"header"}
        original = build_key(inputs, files)
        for key in inputs:
            with self.subTest(key=key):
                self.assertNotEqual(original, build_key({**inputs, key: "changed"}, files))
        self.assertNotEqual(original, build_key(inputs, {**files, "patch": b"new header"}))
        from image_inputs import RECIPE, ROOT
        name = 'patches/webhook-user-agent.patch'
        self.assertIn(name, RECIPE)
        recipe = {p: (ROOT / p).read_bytes() for p in RECIPE}
        self.assertNotEqual(build_key(inputs, recipe), build_key(inputs, {**recipe, name: recipe[name] + b'changed'}))

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
