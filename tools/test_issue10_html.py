"""Run the actual standalone page in Node, with intercepted fetch and a watchdog."""
from pathlib import Path
import subprocess
import unittest


class HtmlTests(unittest.TestCase):
    def test_page_scenarios(self):
        tools = Path(__file__).resolve().parent
        result = subprocess.run(['node', str(tools / 'issue10_timeout.cjs'), '50',
                                 'node', str(tools / 'issue10_ui_harness.cjs')],
                                text=True, capture_output=True, timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
