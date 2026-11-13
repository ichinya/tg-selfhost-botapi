from pathlib import Path
import unittest
from check_docs import private_site_paths

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_both_languages_describe_pending_selection_and_cold_restore(self):
        for lang in ('en', 'ru'):
            maintenance = (ROOT / 'docs' / lang / 'maintenance.md').read_text(encoding='utf8')
            for marker in ('selected_release: null', 'SIGKILL', '--numeric-owner', 'binding.key',
                           '--no-build', 'verification deferred to CI/gates'):
                self.assertIn(marker, maintenance)
        self.assertTrue((ROOT / 'tg_selfhost_botapi_migrator.html').is_file())

    def test_pages_declares_locks_and_generated_inputs_private(self):
        config = (ROOT / '_config.yml').read_text()
        workflow = (ROOT / '.github/workflows/docs.yml').read_text()
        for name in ('image-inputs.lock.json', 'image-release.lock.json', '.env.build', 'selected.env', 'releases'):
            self.assertIn('  - ' + name, config)
            self.assertIn('test ! -e .site-check/' + name, workflow)
