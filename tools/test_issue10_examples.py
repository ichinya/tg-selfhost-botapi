"""Check the replacement adapter syntax."""
from pathlib import Path
import subprocess
import shutil
import unittest
from issue10_test_support import bash_binary

class ExampleTests(unittest.TestCase):
    def test_bash_adapter_syntax(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([bash_binary(), '-n', str(root / 'migrate_off_to_self.sh')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standalone_bash_harness(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([shutil.which('node') or 'node', str(root / 'tools/test_issue10_bash.cjs')], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
