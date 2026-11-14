import unittest
from pathlib import Path
class ProfileUITests(unittest.TestCase):
    def test_all_actions_directions_and_secret_fields_are_private(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/'tools/migration_executor.html').read_text()
        for mode in ('preserve','set','polling','local_to_local'):
            self.assertIn('value="'+mode+'"',ui)
        self.assertIn('type="password"',ui)
        self.assertNotIn('executeInBrowser',ui)
