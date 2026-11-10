"""Ensure diagnostic files cannot pass the rendered-site checker."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DiagnosticPublicationTest(unittest.TestCase):
    def test_private_storage_stays_excluded_from_git_and_pages(self):
        self.assertIn('/logs', (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines())
        config = (ROOT / '_config.yml').read_text(encoding='utf-8')
        self.assertIn('  - logs', config.split('exclude:', 1)[1].split('navigation:', 1)[0])

    def test_locales_describe_the_same_helper_contract(self):
        for language in ('en', 'ru'):
            with self.subTest(language=language):
                migration = (ROOT / 'docs' / language / 'migration.md').read_text(encoding='utf-8')
                configuration = (ROOT / 'docs' / language / 'configuration.md').read_text(encoding='utf-8')
                maintenance = (ROOT / 'docs' / language / 'maintenance.md').read_text(encoding='utf-8')
                prerequisites = (ROOT / 'docs' / language / 'getting-started.md').read_text(encoding='utf-8')
                for text in (migration, configuration):
                    for setting in ('MIGRATION_CONNECT_TIMEOUT', 'MIGRATION_REQUEST_DEADLINE', '1..60', '1..300'):
                        self.assertIn(setting, text)
                for field in ('CONFIRMED_REJECTION', 'UNKNOWN', 'NOT_SENT', 'exit 3', 'logs/migration',
                              'intent.json', 'receipt.json', 'summary.json', 'transport-error.txt',
                              'getWebhookInfo', '0700', '0600', 'raw-curl', 'generated Bash'):
                    self.assertIn(field, migration)
                for field in ('logs/migration', '0700', '0600', 'raw', 'schema', 'lock'):
                    self.assertIn(field.lower(), maintenance.lower())
                for tool in ('mktemp', 'date', 'stat', 'chmod'):
                    self.assertIn(tool, prerequisites)
                self.assertIn('../../tg_selfhost_botapi_migrator.html', migration)

    def test_docs_workflow_checks_fresh_build_with_synthetic_sentinel(self):
        workflow = (ROOT / '.github/workflows/docs.yml').read_text(encoding='utf-8')
        self.assertLess(workflow.index('mkdir -p logs/migration'), workflow.index('actions/jekyll-build-pages'))
        self.assertIn('test ! -e .site-check/logs/migration/issue11-sentinel.txt', workflow)
        self.assertIn('tools/check_docs.py .site-check', workflow)

    def test_logs_are_rejected_from_complete_site(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            pages = ["index.html", "docs/index.html", "contributing.html"]
            for language in ("en", "ru"):
                pages.extend(f"docs/{language}/{name}.html" for name in
                             ("index", "getting-started", "configuration", "migration", "maintenance"))
            for name in pages:
                path = site / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("<!doctype html><html></html>", encoding="utf-8")
            (site / "tg_selfhost_botapi_migrator.html").write_bytes(
                (ROOT / "tg_selfhost_botapi_migrator.html").read_bytes())
            client = site / "assets/js/migration-client.mjs"
            client.parent.mkdir(parents=True)
            client.write_bytes((ROOT / "assets/js/migration-client.mjs").read_bytes())
            command = [sys.executable, str(ROOT / "tools/check_docs.py"), str(site)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            sentinel = site / "logs/migration/issue11-sentinel.txt"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("synthetic", encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Non-documentation content published: logs", result.stderr)
            sentinel.unlink()
            sentinel.parent.rmdir()
            sentinel.parent.parent.rmdir()
            (site / 'tg_selfhost_botapi_migrator.html').write_bytes(b'changed copy')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('The original migrator must be copied without changes', result.stderr)


if __name__ == "__main__":
    unittest.main()
