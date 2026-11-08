import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProfileContractTests(unittest.TestCase):
    def test_same_fixtures_in_actual_inline_js_and_bash_jq_resolver(self):
        cases = json.loads((ROOT / "tools/fixtures/webhook-profile-v1.json").read_text())["cases"]
        js = subprocess.run(["node", "tools/webhook_profile_ui_harness.cjs", "--resolve"], cwd=ROOT,
                            input=json.dumps([c["input"] for c in cases]), text=True,
                            capture_output=True, timeout=15, check=True)
        actual = json.loads(js.stdout)
        self.assertTrue(shutil.which("jq"), "jq prerequisite missing; run the required CI job")
        for case, expected_js in zip(cases, actual, strict=True):
            with self.subTest(case=case["id"]):
                jq = subprocess.run(["jq", "-f", "tools/webhook_profile_resolver.jq"], cwd=ROOT,
                                    input=json.dumps(case["input"]), text=True, capture_output=True, timeout=5)
                self.assertEqual(jq.returncode, 0, jq.stderr)
                result = json.loads(jq.stdout)
                self.assertEqual(result, expected_js)
                self.assertEqual(result["complete"], case["complete"])
                self.assertEqual(result["missing"], case["missing"])
                self.assertEqual(result["invalid"], case["invalid"])
                self.assertNotIn("Synthetic_secret_7", json.dumps(result))

    def test_generator_and_standalone_route(self):
        result = subprocess.run(["node", "tools/embed_webhook_profile.cjs", "--check"], cwd=ROOT,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (ROOT / "tg_selfhost_botapi_migrator.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("<script>"), 1)
        self.assertNotIn('<script src=', html)


if __name__ == "__main__":
    unittest.main()
