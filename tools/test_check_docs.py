from pathlib import Path
import tempfile
import unittest
import uuid
from check_docs import PRIVATE_CONTENT, check_private_content


class PrivacyTests(unittest.TestCase):
    def test_each_runtime_surface_is_rejected(self):
        root = Path(tempfile.gettempdir()) / ('filedocs-' + uuid.uuid4().hex)
        root.mkdir(mode=0o777)
        try:
            self.assertEqual([], check_private_content(root))
            for name in PRIVATE_CONTENT:
                path = root / name
                path.touch()
                self.assertEqual(1, len(check_private_content(root)), name)
                path.unlink()
        finally:
            root.rmdir()

    def test_pages_excludes_every_file_example_surface(self):
        config = (Path(__file__).resolve().parents[1] / '_config.yml').read_text(encoding='utf-8')
        for name in ('examples', 'media', 'secrets', 'files', 'Dockerfile.downloads',
                     'docker-compose.files.yml', 'docker-compose.downloads.yml'):
            self.assertIn('  - ' + name + '\n', config)
