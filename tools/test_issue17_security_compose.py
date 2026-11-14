import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ComposeSecretsTest(unittest.TestCase):
    def model(self, *files):
        env = dict(os.environ, API_ID="id-canary", API_HASH="hash-canary",
                   TELEGRAM_API_ID_SECRET_PATH="/tmp/issue17-id",
                   TELEGRAM_API_HASH_SECRET_PATH="/tmp/issue17-hash")
        command = ["docker", "compose"]
        for file in files:
            command.extend(["-f", file])
        result = subprocess.run(command + ["config", "--format", "json"], cwd=ROOT,
                                env=env, text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_secret_and_legacy_models(self):
        base = "docker-compose.yml"
        for build in ((), ("docker-compose.build.yml",)):
            legacy = self.model(base, *build)["services"]["botapi"]["environment"]
            self.assertEqual(legacy["TELEGRAM_API_ID"], "id-canary")
            model = self.model(base, *build, "docker-compose.secrets.yml")
            bot = model["services"]["botapi"]
            self.assertNotIn("TELEGRAM_API_ID", bot["environment"])
            self.assertNotIn("TELEGRAM_API_HASH", bot["environment"])
            self.assertEqual(bot["environment"]["TELEGRAM_API_ID_FILE"], "/run/secrets/telegram_api_id")
            self.assertEqual(bot["environment"]["TELEGRAM_API_HASH_FILE"], "/run/secrets/telegram_api_hash")
            self.assertNotIn("secrets", model["services"]["gateway"])
            self.assertNotIn("id-canary", json.dumps(model))
            self.assertNotIn("hash-canary", json.dumps(model))
            overlay = self.model(base, *build, "docker-compose.secrets.yml", "docker-compose.observability.yml")
            for service in ("gateway", "observer"):
                self.assertNotIn("secrets", overlay["services"][service])
            self.assertNotIn("id-canary", json.dumps(overlay))
            self.assertNotIn("hash-canary", json.dumps(overlay))


if __name__ == "__main__":
    unittest.main()
