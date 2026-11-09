import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from check_docs import check

SCRIPT = Path(__file__).resolve().parents[1] / "migrate_off_to_self.sh"

class PublishedDiagnosticsTests(unittest.TestCase):
    def test_published_logs_are_rejected_and_retained_html_is_byte_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required = ['index.html', 'docs/index.html', 'contributing.html']
            for language in ('en', 'ru'):
                required.extend('docs/' + language + '/' + name + '.html' for name in
                                ('index', 'getting-started', 'configuration', 'migration', 'maintenance'))
            for name in required:
                page = root / name
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text('<html></html>')
            retained = root / 'tg_selfhost_botapi_migrator.html'
            shutil.copyfile(SCRIPT.parent / retained.name, retained)
            with contextlib.redirect_stdout(io.StringIO()):
                check(root)
            (root / 'logs/migration').mkdir(parents=True)
            (root / 'logs/migration/sentinel').write_text('private')
            with self.assertRaisesRegex(SystemExit, 'Non-documentation content published: logs'):
                check(root)
            shutil.rmtree(root / 'logs')
            retained.write_text('changed')
            with self.assertRaisesRegex(SystemExit, 'original migrator must be copied without changes'):
                check(root)


if __name__ == '__main__':
    unittest.main()
