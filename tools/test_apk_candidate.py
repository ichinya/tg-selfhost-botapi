import json
import os
import subprocess
import unittest
from unittest.mock import patch
import apk_candidate as candidate


class CandidateTests(unittest.TestCase):
    def test_registry_errors_fail_closed(self):
        for message in ('unauthorized', 'network timeout', 'forbidden', 'unknown response'):
            with self.subTest(message=message), patch.object(candidate, 'run', side_effect=subprocess.CalledProcessError(1, 'inspect', stderr=message)):
                with self.assertRaises(RuntimeError): candidate.registry_digest('repo:build-key')
        with patch.object(candidate, 'run', side_effect=subprocess.CalledProcessError(1, 'inspect', stderr='manifest unknown')):
            self.assertIsNone(candidate.registry_digest('repo:build-key'))

    def test_prepare_reuse_pins_digest(self):
        with patch.object(candidate, 'registry_digest', return_value='sha256:' + 'a' * 64), patch.object(candidate, 'run') as run:
            result = candidate.prepare({'build_key': 'key', 'platform': 'linux/amd64'}, 'repo', False)
            self.assertEqual(result['mode'], 'reuse')
            self.assertIn('@sha256:', result['image'])
            run.assert_called_once()

    def test_pr_always_builds_without_registry_access(self):
        with patch.object(candidate, 'registry_digest') as registry:
            self.assertEqual(candidate.prepare({'build_key': 'key'}, 'repo', True)['mode'], 'build')
            registry.assert_not_called()

    def test_missing_gates_or_changed_inputs_reject(self):
        with self.assertRaises(ValueError): candidate.assert_qualified({'key': 'a'}, {'inputs': {'key': 'a'}, 'gates': {'metadata': 'PASS'}})
        with self.assertRaises(ValueError): candidate.assert_qualified({'key': 'a'}, {'inputs': {'key': 'b'}, 'gates': dict.fromkeys(('metadata', 'smoke', 'apk_refresh', 'unit', 'compose'), 'PASS')})

    def test_pr_write_guard(self):
        with patch.dict(os.environ, {'DEFAULT_BRANCH': 'main', 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/heads/main'}):
            with self.assertRaises(ValueError): candidate.write_guard()

    def test_new_build_and_qualified_reuse_config_binding(self):
        inputs = {'build_key': 'key'}
        receipt = {'inputs': inputs, 'gates': dict.fromkeys(('metadata', 'smoke', 'apk_refresh', 'unit', 'compose'), 'PASS'), 'image_config_id': 'config'}
        digest = 'sha256:' + 'a' * 64
        for mode in ('build', 'reuse'):
            state = {'mode': mode, 'digest': digest}
            with self.subTest(mode=mode), patch.object(candidate, 'write_guard'), patch.object(candidate, 'assert_fresh'), patch.object(candidate, 'registry_config', return_value='config'), patch.object(candidate, 'registry_digest', side_effect=[None, digest]), patch.object(candidate, 'run') as run, patch.dict(os.environ, {'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1'}):
                result = candidate.publish_candidate(state, inputs, receipt, 'repo')
                self.assertEqual(result['candidate_digest'], digest)
                self.assertEqual(run.call_count, 2 if mode == 'build' else 0)

    def test_successful_promotion_reads_back_digest(self):
        from pathlib import Path
        inputs = {'build_key': 'key'}
        digest = 'sha256:' + 'a' * 64
        receipt = {'inputs': inputs, 'gates': dict.fromkeys(('metadata', 'smoke', 'apk_refresh', 'unit', 'compose'), 'PASS'), 'candidate_digest': digest, 'image_config_id': 'config'}
        with patch.object(candidate, 'write_guard'), patch.object(candidate, 'assert_fresh'), patch.object(candidate, 'registry_config', return_value='config'), patch.object(candidate, 'registry_digest', side_effect=[None, digest, 'previous', digest]), patch.object(candidate, 'run') as run, patch.object(candidate, 'assert_latest_not_newer'), patch.object(candidate, 'save') as save:
            candidate.promote(inputs, receipt, 'repo', Path('evidence'))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(save.call_args.args[1]['status'], 'PASS')

    def test_collision_never_mutates_latest(self):
        inputs = {'build_key': 'key'}
        receipt = {'inputs': inputs, 'gates': dict.fromkeys(('metadata', 'smoke', 'apk_refresh', 'unit', 'compose'), 'PASS'), 'candidate_digest': 'sha256:a', 'image_config_id': 'config'}
        with patch.object(candidate, 'write_guard'), patch.object(candidate, 'assert_fresh'), patch.object(candidate, 'registry_config', return_value='config'), patch.object(candidate, 'registry_digest', return_value='sha256:other'), patch.object(candidate, 'run') as run:
            with self.assertRaises(ValueError): candidate.promote(inputs, receipt, 'repo', None)
            run.assert_not_called()

    def test_stale_run_never_writes(self):
        with patch.object(candidate, 'write_guard'), patch.object(candidate, 'assert_qualified'), patch.object(candidate, 'assert_fresh', side_effect=ValueError('stale')), patch.object(candidate, 'run') as run:
            with self.assertRaises(ValueError): candidate.publish_candidate({}, {}, {}, 'repo')
            run.assert_not_called()

    def test_wrong_config_never_mutates_latest(self):
        with patch.object(candidate, 'write_guard'), patch.object(candidate, 'assert_qualified'), patch.object(candidate, 'assert_fresh'), patch.object(candidate, 'registry_config', return_value='wrong'), patch.object(candidate, 'run') as run:
            with self.assertRaises(ValueError): candidate.promote({}, {'candidate_digest': 'sha256:a', 'image_config_id': 'config'}, 'repo', None)
            run.assert_not_called()

    def test_pr_policy_uses_event_base_sha(self):
        import tempfile
        from pathlib import Path
        base = 'a' * 40
        with tempfile.TemporaryDirectory() as folder:
            event = Path(folder) / 'event.json'
            event.write_text(json.dumps({'pull_request': {'base': {'sha': base}}, 'repository': {'default_branch': 'main'}}))
            policy = {'policy_version': 1, 'refresh': 'utc-day', 'generation': 0}
            with patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(event), 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_BASE_REF': 'moving-branch'}), patch.object(candidate, 'run') as run, patch.object(candidate, 'read_remote_policy', return_value=policy) as read, patch.object(candidate, 'read_policy', return_value=policy):
                candidate.policy_check()
            run.assert_called_once_with('git', 'fetch', '--no-tags', 'origin', base)
            read.assert_called_once_with(base)

    def test_schedule_policy_needs_no_before_sha(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            event = Path(folder) / 'event.json'
            event.write_text(json.dumps({'repository': {'default_branch': 'main'}}))
            policy = {'policy_version': 1, 'refresh': 'utc-day', 'generation': 1}
            with patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(event), 'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_BASE_REF': ''}), patch.object(candidate, 'run') as run, patch.object(candidate, 'read_remote_policy', return_value=policy), patch.object(candidate, 'read_policy', return_value=policy):
                candidate.policy_check()
            run.assert_called_once_with('git', 'fetch', '--no-tags', 'origin', 'main')

    def test_every_failed_gate_and_unresolved_scanner_blocks(self):
        gates = dict.fromkeys(('metadata', 'smoke', 'apk_refresh', 'unit', 'compose'), 'PASS')
        for gate in gates:
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                candidate.assert_qualified({}, {'inputs': {}, 'gates': {**gates, gate: 'NOTRUN'}})
        with self.assertRaises(ValueError):
            candidate.assert_qualified({}, {'inputs': {}, 'gates': gates, 'scanner': {'status': 'UNKNOWN'}})

    def test_latest_refresh_order_including_midnight(self):
        inputs = {'apk_refresh_window': '2026-11-10', 'generation': 1, 'platform': 'linux/amd64'}
        for window, generation, reject in [('2026-11-09', '1', False), ('2026-11-10', '1', False),
                                            ('2026-11-11', '1', True), ('2026-11-10', '2', True)]:
            labels = {'io.tg-selfhost.apk-refresh-window': window, 'io.tg-selfhost.apk-refresh-generation': generation}
            with self.subTest(window=window, generation=generation), patch.object(candidate, 'run', side_effect=['', json.dumps([{'Config': {'Labels': labels}}])]):
                if reject:
                    with self.assertRaises(ValueError): candidate.assert_latest_not_newer('repo', inputs, 'digest')
                else:
                    candidate.assert_latest_not_newer('repo', inputs, 'digest')

    def test_reuse_repeats_smoke_and_uses_qualified_config(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder)
            (evidence / 'apk-refresh.json').write_text(json.dumps({'status': 'PASS', 'build_key': 'key'}))
            (evidence / 'gates.json').write_text(json.dumps({'build_key': 'key', 'unit': 'PASS', 'compose': 'PASS'}))
            metadata = {'image_config_id': 'qualified-config', 'gates': {'metadata': 'PASS'}}
            state = {'mode': 'reuse', 'image': 'repo@digest', 'digest': 'digest'}
            with patch.object(candidate, 'metadata_receipt', return_value=metadata) as validate, patch.object(candidate, 'run') as run:
                result = candidate.qualify(state, {'build_key': 'key'}, evidence)
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertIn('qualified-config', call.args)
            self.assertEqual(validate.call_args.args[0], 'repo@digest')
            self.assertEqual(result['gates']['smoke'], 'PASS')


if __name__ == '__main__':
    unittest.main()
