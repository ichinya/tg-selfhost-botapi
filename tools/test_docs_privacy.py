"""The rendered site must not contain private migration state or env files."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_docs import private_site_paths


class PrivateSitePathsTest(unittest.TestCase):
    def test_nested_private_content_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / ".migration-state" / "operation").mkdir(parents=True)
            (root / "docs" / ".migration-state" / "operation" / "state.json").write_text("{}")
            (root / "docs" / ".env.local").write_text("placeholder")
            (root / ".env").write_text("placeholder")
            (root / "docs" / "environment.html").write_text("public")
            paths = {str(path).replace("\\", "/") for path in private_site_paths(root)}
            self.assertIn("docs/.migration-state/operation/state.json", paths)
            self.assertIn("docs/.env.local", paths)
            self.assertIn(".env", paths)
            self.assertNotIn("docs/environment.html", paths)

    def test_download_assets_are_private_at_every_depth(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            names = ('files/bot/media', 'secrets/registry', 'examples/files/config.json',
                     'docs/downloads.config.extra.json', 'Dockerfile.downloads',
                     'docker-compose.downloads.yml')
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic')
            self.assertEqual({p.as_posix() for p in private_site_paths(root)},
                             set(names) | {'files', 'files/bot', 'secrets', 'examples', 'examples/files'})


if __name__ == "__main__":
    unittest.main()
