"""Check the PR/main boundary for expensive workflows."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'


class CISplitTests(unittest.TestCase):
    def test_expensive_jobs_require_main_and_authorized_event(self):
        for filename, job in [('files.yml', 'qualify'), ('migration-executor.yml', 'executor-acceptance'),
                              ('migration-safety.yml', 'persistent-volumes'),
                              ('gateway-upload-acceptance.yml', 'transport'), ('doctor.yml', 'runtime')]:
            text = (WORKFLOWS / filename).read_text()
            section = text.split('  ' + job + ':\n', 1)[1].split('    runs-on:', 1)[0]
            with self.subTest(filename=filename):
                self.assertIn("github.ref == 'refs/heads/main'", section)
                self.assertIn("github.event_name == 'workflow_dispatch'", section)
                self.assertIn("github.event_name == 'push'", section)

    def test_pr_has_one_full_discovery_gate(self):
        security = (WORKFLOWS / 'issue17-security.yml').read_text()
        self.assertIn('  pull_request:\n  push:', security)
        self.assertIn('issue17_security_gate.py --unit', security)
        for filename in ('doctor.yml', 'gateway-upload-acceptance.yml', 'html-migrator.yml'):
            self.assertNotIn("-p 'test_*.py'", (WORKFLOWS / filename).read_text())


if __name__ == '__main__':
    unittest.main()
