"""Public entry and actual helper client contract."""
from pathlib import Path
import subprocess, unittest
class EntryTests(unittest.TestCase):
    def test_root_entry_and_same_origin_client(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node','tools/test_html_migrator.cjs'],cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
