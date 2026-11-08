"""Check the replacement adapter syntax."""
from pathlib import Path
import subprocess
import unittest
from issue10_test_support import bash_binary

class ExampleTests(unittest.TestCase):
    def test_bash_adapter_syntax(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([bash_binary(), '-n', str(root / 'migrate_off_to_self.sh')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
