from pathlib import Path
import os, subprocess, unittest
class AdapterTests(unittest.TestCase):
    def test_regeneration_uses_only_canonical_adapter(self):
        root=Path(__file__).resolve().parents[1]
        subprocess.run(['node','tools/embed_webhook_profile.cjs','--check'],cwd=root,check=True)
        text=(root/'migrate_off_to_self.sh').read_text()
        self.assertIn('tools/migration_executor.sh',text); self.assertNotIn('wp_migration_main',text)
    @unittest.skipUnless(os.name=='posix','POSIX shell syntax gate')
    def test_bash_adapter_syntax(self):
        root=Path(__file__).resolve().parents[1]
        for path in ('migrate_off_to_self.sh','tools/migration_executor.sh','tools/migration_adapter.sh'):
            subprocess.run(['bash','-n',str(root/path)],check=True)
