"""Controller regressions; these do not replace the Docker permission matrix."""
import importlib.util
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("permissions", ROOT / "tools/check_runtime_permissions.py")
permissions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(permissions)


class ControllerTest(unittest.TestCase):
    def test_http_404_is_ready_but_a_failed_wget_is_not(self):
        self.assertTrue(permissions.http_ready(1, "  HTTP/1.1 404 Not Found\n"))
        self.assertTrue(permissions.http_ready(0, "  HTTP/1.1 200 OK\n"))
        self.assertFalse(permissions.http_ready(1, "wget: connection refused\n"))
        self.assertFalse(permissions.http_ready(127, "  HTTP/1.1 404 Not Found\n"))
        self.assertFalse(permissions.http_ready(0, "HTTP/garbage\n"))

    def test_compose_validation_rejects_workspace_mount_and_egress(self):
        root = (ROOT / ".issue-flow/issue-21/controller-test").resolve()
        service = {
            "container_name": "issue21-test-botapi", "restart": "no",
            "network_mode": "none", "user": "1000:2000", "image": "candidate:test",
            "environment": {"TELEGRAM_API_ID": "12345",
                            "TELEGRAM_API_HASH": "synthetic-placeholder",
                            "TELEGRAM_LOCAL": "true"},
            "volumes": [dict(type="bind", source=str(root / name), target=target,
                             bind=dict(create_host_path=False)) for name, target in
                        (("data", permissions.STATE), ("temp", permissions.TEMP))],
        }
        permissions.validate_botapi(service, root, "issue21-test-botapi", "candidate:test")
        service["volumes"][0]["source"] = str(ROOT / "data")
        with self.assertRaises(RuntimeError):
            permissions.validate_botapi(service, root, "issue21-test-botapi", "candidate:test")
        service["volumes"][0]["source"] = str(root / "data")
        service["network_mode"] = "bridge"
        with self.assertRaises(RuntimeError):
            permissions.validate_botapi(service, root, "issue21-test-botapi", "candidate:test")

    def test_all_mandatory_scenarios_run_and_failures_propagate(self):
        matrix = permissions.Matrix("candidate:test")
        calls = []
        names = ("check_platform", "named_volumes", "binds_and_negatives", "fixture",
                 "compose_matrix", "reader", "verify_image", "close")
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(matrix, name, side_effect=lambda n=name: calls.append(n)))
            matrix.execute()
            self.assertEqual(calls, list(names))
            with patch.object(matrix, "binds_and_negatives", side_effect=RuntimeError("mandatory failure")):
                with self.assertRaisesRegex(RuntimeError, "mandatory failure"):
                    matrix.execute()
            self.assertEqual(calls[-1], "close")

    def test_reader_documentation_matches_the_runnable_fixture(self):
        fixture = (ROOT / "tools/fixtures/issue21/docker-compose.reader.yml").read_text(encoding="utf-8").rstrip()
        for language in ("en", "ru"):
            for page in ("configuration", "getting-started"):
                with self.subTest(language=language, page=page):
                    text = (ROOT / f"docs/{language}/{page}.md").read_text(encoding="utf-8")
                    self.assertIn("```yaml\n" + fixture + "\n```", text)


if __name__ == "__main__":
    unittest.main()
