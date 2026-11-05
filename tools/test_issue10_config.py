"""Exercise helper configuration through a real Bash subprocess, without network."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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
        for name, contents in {'curl': 'printf "%s\\n" "$*" >> "$CALLS"; exit 1',
                               'jq': 'exit 1'}.items():
            path = self.bin / name
            path.write_text('#!/bin/sh\n' + contents + '\n')
            path.chmod(0o755)
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'CALLS': str(self.root / 'calls')}

    def run_helper(self, *args, **env):
        return subprocess.run(['bash', str(self.script), '123:synthetic', *args],
                              cwd=self.cwd, env={**self.env, **env}, input='n\n',
                              text=True, capture_output=True, timeout=10)

    def calls(self):
        path = self.root / 'calls'
        return path.read_text() if path.exists() else ''

    def test_default_is_script_relative_not_cwd(self):
        (self.cwd / '.env').write_text('SELF_BOT_URL=http://wrong\n')
        (self.script.parent / '.env').write_text('SELF_BOT_URL=http://correct\n')
        self.run_helper()
        self.assertIn('http://correct/', self.calls())
        self.assertNotIn('http://wrong', self.calls())

    def test_process_alias_overrides_file_and_argument_overrides_both(self):
        path = self.cwd / 'settings with spaces'
        path.write_text('API_ID=123\nAPI_HASH=placeholder\nSELF_BOT_URL=http://file\n')
        self.run_helper('http://argument', ENV_FILE=str(path), TELEGRAM_BOT_URL='http://process')
        self.assertIn('http://argument/', self.calls())

    def test_missing_empty_and_invalid_explicit_file_stop_before_curl(self):
        for contents in (None, '', 'SELF_BOT_URL="unterminated\n'):
            path = self.cwd / 'invalid'
            if contents is not None:
                path.write_text(contents)
            result = self.run_helper(ENV_FILE=str(path), SELF_BOT_URL='http://local')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls(), '')
            if path.exists():
                path.unlink()

    def test_absent_default_uses_process(self):
        self.run_helper(SELF_BOT_URL='http://process')
        self.assertIn('http://process/', self.calls())


if __name__ == '__main__':
    unittest.main()
