"""Run the network-free browser migrator contract tests."""
import pathlib
import subprocess
import shutil
import unittest


class HtmlMigratorTests(unittest.TestCase):
    def test_node_contract(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node.js 24 is required to run the HTML migrator suite')
        result = subprocess.run([node, 'tools/test_html_migrator.cjs'], cwd=root,
                                capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
