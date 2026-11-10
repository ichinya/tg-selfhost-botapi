"""Run the replacement page against the network-free UI harness."""
from pathlib import Path
import subprocess
import unittest

class HtmlTests(unittest.TestCase):
    def test_page_scenarios(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tools/migrator_ui_harness.js')], cwd=root, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
