import json
from pathlib import Path
import unittest
from urllib.parse import quote
from issue17_security_checks import assert_private_absent

ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'tools/fixtures/issue17_security/cases.json').read_text())


class MarkerMatrix(unittest.TestCase):
    def test_scanner_positive_controls_all_encodings(self):
        markers=list(CASES['markers'].values())
        for marker in markers:
            forms=(marker,quote(marker,safe=''),quote(quote(marker,safe=''),safe=''),
                   ''.join('\\u%04x'%ord(c) for c in marker))
            for form in forms:
                with self.assertRaisesRegex(AssertionError,'^private_marker_detected$'):
                    assert_private_absent(form,markers)
        self.assertGreater(assert_private_absent('GET api 200 12 0.001',markers),0)

    def test_generated_files_are_text_and_inputs_are_not_vendored(self):
        for name in ('tools/migration_diagnostics_main.sh','migrate_off_to_self.sh','tg_selfhost_botapi_migrator.html'):
            content=(ROOT/name).read_bytes()
            self.assertNotIn(b'\0',content)
            content.decode('utf-8')
        script=(ROOT/'tools/webhook_profile_runtime.sh').read_text()
        self.assertIn('Protected input rejected',script)
        self.assertNotIn('issue17_docker',script)
