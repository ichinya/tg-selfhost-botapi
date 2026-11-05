"""Native checks for the WSL guard and the independent outer deadline."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from issue10_test_support import bash_binary


class PlatformTests(unittest.TestCase):
    def test_relative_override_is_rejected_before_process_start(self):
        with patch.dict(os.environ, {'ISSUE10_BASH': 'bash'}, clear=False):
            with self.assertRaisesRegex(RuntimeError, 'absolute'):
                bash_binary()

    def test_wsl_launchers_are_rejected_before_process_start(self):
        if os.name != 'nt':
            candidates = ['/windows/system32/bash.exe', '/windows/sysnative/bash.exe', '/bin/wsl.exe']
        else:
            candidates = ['C:/Windows/System32/bash.exe', 'C:/Windows/Sysnative/bash.exe', 'C:/Windows/System32/wsl.exe']
        for candidate in candidates:
            with self.subTest(candidate=candidate), patch.dict(os.environ, {'ISSUE10_BASH': candidate}):
                with self.assertRaisesRegex(RuntimeError, 'WSL'):
                    bash_binary()

    def test_outer_deadline_ends_an_unresponsive_native_child(self):
        tools = Path(__file__).resolve().parent
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for migration tests')
        result = subprocess.run([node, str(tools / 'issue10_timeout.cjs'), '0.2', node,
                                 '-e', 'setInterval(() => {}, 1000)'],
                                text=True, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
        self.assertIn('Outer timeout', result.stderr)


if __name__ == '__main__':
    unittest.main()
