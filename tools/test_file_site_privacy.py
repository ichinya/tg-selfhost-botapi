"""Owned file-profile privacy checks; independent of other issue drafts."""
from pathlib import Path
import unittest
from tools.check_docs import PRIVATE_CONTENT, check_private_content


class FileSitePrivacyTests(unittest.TestCase):
    def test_all_profile_sources_and_private_data_are_excluded(self):
        config = (Path(__file__).resolve().parents[1] / '_config.yml').read_text(encoding='utf-8')
        for name in PRIVATE_CONTENT:
            self.assertIn('  - ' + name + '\n', config)

    def test_private_path_detection_without_filesystem_writes(self):
        from unittest.mock import MagicMock
        root = MagicMock()
        root.__truediv__.return_value.exists.return_value = True
        self.assertEqual(len(check_private_content(root)), len(PRIVATE_CONTENT))


if __name__ == '__main__':
    unittest.main()
