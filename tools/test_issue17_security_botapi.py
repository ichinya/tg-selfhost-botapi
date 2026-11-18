from pathlib import Path
import unittest
from image_inputs import RECIPE, build_key

ROOT=Path(__file__).resolve().parents[1]


class BotApiPrivacyRecipe(unittest.TestCase):
    def test_patch_and_driver_are_recipe_inputs(self):
        patch='patches/botapi-secrets-redaction.patch'
        self.assertIn(patch,RECIPE)
        self.assertIn('tools/fixtures/issue17_security/botapi_log_driver.cpp',RECIPE)
        self.assertNotEqual(build_key({}, {patch:b'a'}),build_key({}, {patch:b'b'}))
        recipe=(ROOT/'Dockerfile').read_text()
        self.assertLess(recipe.index('webhook-user-agent.patch'),recipe.index('botapi-secrets-redaction.patch'))
        self.assertIn('build/botapi-privacy-driver',recipe)
        source=(ROOT/patch).read_text()
        self.assertIn('privacy_log.set_sink(&log)',source)
        self.assertIn('sink_->do_append',source)
        self.assertIn('options.use_gdb = false',source)
