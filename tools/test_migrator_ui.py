"""Run the actual standalone HTML in the independent Node harness."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserProfileTests(unittest.TestCase):
    def test_inline_execution_and_exports(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required; missing runtime is not a skip")
        result = subprocess.run([node, str(ROOT / "tools/migrator_ui_harness.js")], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, "UI harness failed; private output omitted")
        self.assertIn("checks passed", result.stdout)
        for name in ('webhook_profile_ui_harness.cjs','test_issue17_security_browser.cjs'):
            result=subprocess.run([node,str(ROOT/'tools'/name)],cwd=ROOT,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,'standalone privacy harness failed; private output omitted')


if __name__ == "__main__":
    unittest.main()
