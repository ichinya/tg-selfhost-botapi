"""Exercise helper configuration through a real Bash subprocess, without network."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue10_test_support import bash_binary, posix_path

SCRIPT = Path(__file__).resolve().parents[1] / 'migrate_off_to_self.sh'


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = self.root / 'script' / 'helper.sh'
        self.script.parent.mkdir()
        shutil.copy(SCRIPT, self.script)
        self.cwd = self.root / 'other'
        self.cwd.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name, contents in {'curl': 'printf "%s\\n" "$*" >> "$CALLS"; printf \'{"ok":false,"error_code":404,"description":"Not Found"}\\n404\'',
                               'jq': 'exit 0'}.items():
            path = self.bin / name
            path.write_text('#!/bin/sh\n' + contents + '\n', encoding='utf-8', newline='\n')
            path.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key.upper() in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC')}
        self.env.update(CALLS=(self.root / 'calls').as_posix())

    def run_helper(self, *args, **env):
        return subprocess.run([bash_binary(), '-c', 'PATH="$1:$PATH"; export PATH; shift; exec "$0" "$@"',
                               self.script.as_posix(), posix_path(self.bin), '123:synthetic', *args],
                              cwd=self.cwd, env={**self.env, **env}, input='n\n',
                              text=True, capture_output=True, timeout=10)

    def calls(self):
        path = self.root / 'calls'
        return path.read_text() if path.exists() else ''

    def test_default_is_script_relative_not_cwd(self):
        (self.cwd / '.env').write_text('SELF_BOT_URL=http://wrong\n', newline='\n')
        (self.script.parent / '.env').write_text('SELF_BOT_URL=http://correct\n', newline='\n')
        self.run_helper()
        self.assertIn('http://correct/', self.calls())
        self.assertNotIn('http://wrong', self.calls())

    def test_process_alias_overrides_file_and_argument_overrides_both(self):
        path = self.cwd / 'settings with spaces'
        path.write_text('API_ID=123\nAPI_HASH=placeholder\nSELF_BOT_URL=http://file\n', newline='\n')
        self.run_helper('http://argument', ENV_FILE=str(path), TELEGRAM_BOT_URL='http://process')
        self.assertIn('http://argument/', self.calls())

    def test_missing_empty_and_invalid_explicit_file_stop_before_curl(self):
        for contents in (None, '', 'SELF_BOT_URL="unterminated\n'):
            path = self.cwd / 'invalid'
            if contents is not None:
                path.write_text(contents, newline='\n')
            result = self.run_helper(ENV_FILE=str(path), SELF_BOT_URL='http://local')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls(), '')
            if path.exists():
                path.unlink()

    def test_absent_default_uses_process(self):
        self.run_helper(SELF_BOT_URL='http://process')
        self.assertIn('http://process/', self.calls())

    def test_process_alias_beats_file_canonical_without_argument(self):
        (self.script.parent / '.env').write_text('SELF_BOT_URL=http://file\n', newline='\n')
        self.run_helper(TELEGRAM_BOT_URL='http://process')
        self.assertIn('http://process/', self.calls())

    def test_canonical_beats_alias_in_each_source(self):
        for source in ('file', 'process'):
            with self.subTest(source=source):
                settings = dict(SELF_BOT_URL='http://canonical', TELEGRAM_BOT_URL='http://alias')
                if source == 'file':
                    (self.script.parent / '.env').write_text(
                        '\n'.join(f'{key}={value}' for key, value in settings.items()) + '\n', newline='\n')
                    settings = {}
                self.run_helper(**settings)
                self.assertIn('http://canonical/', self.calls())
                self.assertNotIn('http://alias', self.calls())

    def test_relative_explicit_file_with_spaces_and_compose_keys(self):
        (self.cwd / 'settings file').write_text(
            'API_ID=123\nAPI_HASH=placeholder\nTELEGRAM_BOT_URL=http://relative\n', newline='\n')
        self.run_helper(ENV_FILE='settings file')
        self.assertIn('http://relative/', self.calls())

    def test_empty_explicit_path_is_not_default(self):
        result = self.run_helper(ENV_FILE='', SELF_BOT_URL='http://local')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), '')

    def test_hook_and_drop_precedence_in_preview(self):
        (self.script.parent / '.env').write_text(
            'SELF_BOT_URL=http://file\nWEBHOOK_URL=https://file/hook\nWEB_HOOK=https://file-alias/hook\n'
            'DROP_PENDING_UPDATES=true\n', newline='\n')
        result = self.run_helper(SELF_BOT_URL='http://process', WEB_HOOK='https://process/hook',
                                 DROP_PENDING_UPDATES='false')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Webhook: https://process/hook', result.stdout)
        self.assertIn('Drop updates: false', result.stdout)
        result = self.run_helper('http://argument', 'https://argument/hook',
                                 WEBHOOK_URL='https://process/hook', WEB_HOOK='https://alias/hook')
        self.assertIn('Webhook: https://argument/hook', result.stdout)
        self.assertNotIn('/bot123:', self.calls())

    def test_file_canonical_hook_beats_file_alias(self):
        (self.script.parent / '.env').write_text(
            'SELF_BOT_URL=http://file\nWEBHOOK_URL=https://canonical/hook\nWEB_HOOK=https://alias/hook\n', newline='\n')
        result = self.run_helper()
        self.assertIn('Webhook: https://canonical/hook', result.stdout)

    def test_invalid_drop_stops_before_network(self):
        result = self.run_helper(SELF_BOT_URL='http://local', DROP_PENDING_UPDATES='invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), '')

    def test_unreadable_explicit_file_stops_before_network(self):
        if os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0):
            self.skipTest('Unreadable-file permission check requires a non-root POSIX runner')
        path = self.cwd / 'private'
        path.write_text('SELF_BOT_URL=http://private\n', newline='\n')
        path.chmod(0)
        try:
            result = self.run_helper(ENV_FILE=str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls(), '')
        finally:
            path.chmod(0o600)


if __name__ == '__main__':
    unittest.main()
