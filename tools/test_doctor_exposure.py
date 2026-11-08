import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
from doctor import parser
from doctor_checks import nginx_config, nginx_routes, backing
from doctor_runtime import Installation


class ExposureTests(unittest.TestCase):
    def test_shipped_logging_map_and_unknown_routes(self):
        from pathlib import Path
        config = (Path(__file__).resolve().parent.parent / "nginx.conf").read_text()
        roots, proxies, listens, unknown = nginx_routes(nginx_config(config))
        self.assertEqual(([], ["http://botapi:8081"], [80], False), (roots, proxies, listens, unknown))
        for extra in ("server { root $uri_redacted; }", "server { unknown_route on; }",
                      "map $uri $uri_redacted { root /private; }"):
            self.assertTrue(nginx_routes(nginx_config(config + extra))[-1])
        roots, _, _, unknown = nginx_routes(nginx_config(config + "server { alias /private; }"))
        self.assertIn("/private", roots)
        self.assertFalse(unknown)

    def test_parser_includes_and_dynamic(self):
        text = '# configuration file /etc/nginx/nginx.conf:\nhttp { include /etc/nginx/conf.d/*.conf; }\n# configuration file /etc/nginx/conf.d/default.conf:\nserver { listen 80; location / { proxy_pass http://botapi:8081; } }'
        _, proxies, listens, unknown = nginx_routes(nginx_config(text))
        self.assertEqual((["http://botapi:8081"], [80], False), (proxies, listens, unknown))
        self.assertTrue(nginx_routes(nginx_config('server { location / { alias $dynamic; } }'))[-1])
        for text in ('server {', 'include missing.conf;', 'server { location / { root "/a b"; }'):
            with self.assertRaises(ValueError):
                nginx_config(text)

    def test_backing(self):
        self.assertEqual("/private/data/binlog", backing("/media/binlog", [{"Destination": "/media", "Source": "/private/data"}]))

    def test_current_alias_and_safe_gateway(self):
        for unsafe in (True, False):
            obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
            obj.process = {"flags": {}, "port": "8081"}
            obj.containers = {
                "botapi": {"Config": {}, "Mounts": [{"Destination": "/var/lib/telegram-bot-api", "Source": "/private/state"}]},
                "gateway": {"Mounts": ([{"Destination": "/var/lib/telegram-bot-api", "Source": "/private/state", "RW": False}] if unsafe else []),
                            "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}]}}}}
            config = 'server { listen 80; location / { proxy_pass http://botapi:8081; } '
            config += 'location /file/ { alias /var/lib/telegram-bot-api/; } }' if unsafe else '}'
            obj.exec = lambda *a, **kw: config.encode()
            obj.exposure()
            found = next(c for c in obj.checks if c["id"].endswith(".state_exposure"))
            self.assertEqual("fail" if unsafe else "pass", found["status"])

    def test_root_in_separate_namespace_is_not_shared_state(self):
        obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
        obj.process = {"flags": {}, "port": "8081"}
        obj.containers = {
            "botapi": {"Config": {}, "Mounts": [
                {"Destination": "/var/lib/telegram-bot-api", "Source": "/private/state"},
                {"Destination": "/tmp/telegram-bot-api", "Source": "/private/temp"}]},
            "gateway": {"Mounts": [], "NetworkSettings": {"Ports": {}}},
        }
        obj.exec = lambda *a, **kw: b"server { listen 80; root /tmp; location / { proxy_pass http://botapi:8081; } }"
        obj.exposure()
        result = next(c for c in obj.checks if c["id"].endswith(".state_exposure"))
        self.assertEqual(("pass", "state_mount_isolated"), (result["status"], result["reason_code"]))

    def test_log_paths_and_incomplete_evidence(self):
        from doctor_runtime import LOG_CANONICAL, RunError
        for argv, env, shared, canonical, expected in (
            ("/logs/server.log", None, True, "/logs/server.log", "fail"),
            (None, "/logs/server.log", True, "/logs/server.log", "fail"),
            ("/logs/server.log", "/safe/server.log", True, "/logs/server.log", "fail"),
            ("/safe/server.log", "/logs/server.log", True, "/logs/server.log", "fail"),
            ("/logs/server.log", None, False, "/logs/server.log", "pass"),
            ("relative.log", None, False, None, "unknown"),
            ("/logs/server.log", None, False, None, "unknown"),
            (None, None, False, None, "pass"),
        ):
            with self.subTest(argv=argv, env=env, shared=shared, canonical=canonical):
                obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
                obj.process = {"flags": {"log": argv} if argv else {}, "port": "8081"}
                obj.containers = {
                    "botapi": {"Config": {"Env": ["TELEGRAM_LOG_FILE=" + env] if env else []}, "Mounts": [
                        {"Destination": "/var/lib/telegram-bot-api", "Source": "/private/state"},
                        {"Destination": "/logs", "Source": "/private/logs"}]},
                    "gateway": {"Mounts": ([{"Destination": "/served", "Source": "/private/logs", "RW": False}] if shared else []),
                                "NetworkSettings": {"Ports": {}}},
                }
                def execute(service, *args, **kwargs):
                    if LOG_CANONICAL in args:
                        if canonical is None:
                            raise RunError()
                        return (args[-1] + "\n").encode()
                    return b"server { listen 80; location / { proxy_pass http://botapi:8081; } location /alt { alias /served; } }"
                obj.exec = execute
                obj.exposure()
                checks = {c["id"].split(".")[-1]: c for c in obj.checks}
                if expected == "fail":
                    self.assertEqual("fail", checks["state_mount_accessible"]["status"])
                    self.assertEqual("fail", checks["state_exposure"]["status"])
                else:
                    self.assertEqual(expected, checks["state_exposure"]["status"])
                self.assertNotIn("/logs/server.log", str(obj.checks))

    def test_log_flag_forms(self):
        from doctor_checks import process_flags
        self.assertEqual({"log": "/logs/file"}, process_flags(["--log=/logs/file"]))
        self.assertEqual({"log": "/logs/file"}, process_flags(["--log", "/logs/file"]))

    def test_missing_or_partial_mount_evidence_is_unknown_but_preserves_fail(self):
        for service in ("botapi", "gateway"):
            for evidence in (None, {}, [None], [{"Destination": "/unmapped"}]):
                for shared in (False, True):
                    with self.subTest(service=service, evidence=evidence, shared=shared):
                        obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
                        obj.process = {"flags": {}, "port": "8081"}
                        mount = {"Destination": "/var/lib/telegram-bot-api", "Source": "/state"}
                        obj.containers = {
                            "botapi": {"Config": {}, "Mounts": [mount]},
                            "gateway": {"Mounts": [mount] if shared else [], "NetworkSettings": {"Ports": {}}},
                        }
                        # Preserve confirmed mappings alongside an incomplete additional entry.
                        obj.containers[service]["Mounts"] = ([mount] + evidence if shared and isinstance(evidence, list) else evidence)
                        obj.exec = lambda *a, **kw: b"server { listen 80; root /var/lib/telegram-bot-api; location / { proxy_pass http://botapi:8081; } }"
                        obj.exposure()
                        finding = next(c for c in obj.checks if c["id"].endswith(".state_exposure"))
                        expected = "fail" if shared and isinstance(evidence, list) else "unknown"
                        self.assertEqual(expected, finding["status"])

    def test_canonical_path_keeps_spaces(self):
        from doctor_runtime import LOG_CANONICAL
        obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
        obj.process = {"flags": {"log": "/link"}, "port": "8081"}
        obj.containers = {
            "botapi": {"Config": {}, "Mounts": [
                {"Destination": "/var/lib/telegram-bot-api", "Source": "/state"},
                {"Destination": "/private/log ", "Source": "/shared/log"}]},
            "gateway": {"Mounts": [{"Destination": "/served", "Source": "/shared/log"}],
                        "NetworkSettings": {"Ports": {}}},
        }
        obj.exec = lambda service, *args, **kwargs: (b"/private/log \n" if LOG_CANONICAL in args else
            b"server { listen 80; location / { proxy_pass http://botapi:8081; } }")
        obj.exposure()
        self.assertTrue(any(c["id"].endswith(".state_mount_accessible") and c["status"] == "fail" for c in obj.checks))

    def test_log_backing_namespace_file_mount_and_canonical_matrix(self):
        from doctor_runtime import LOG_CANONICAL
        state = {"Destination": "/var/lib/telegram-bot-api", "Source": "/host/state"}
        for name, log, canonical, api_mounts, http_mounts, expected in (
            ("bind-directory", "/logs/server.log", "/logs/server.log",
             [{"Type": "bind", "Destination": "/logs", "Source": "/host/logs"}],
             [{"Type": "bind", "Destination": "/served", "Source": "/host/logs", "RW": False}], "fail"),
            ("bind-file-below-root", "/logs/server.log", "/logs/server.log",
             [{"Type": "bind", "Destination": "/logs/server.log", "Source": "/host/file"}],
             [{"Type": "bind", "Destination": "/served/file", "Source": "/host/file", "RW": False}], "fail"),
            ("named-volume", "/logs/server.log", "/logs/server.log",
             [{"Type": "volume", "Destination": "/logs", "Source": "/volumes/logs/_data"}],
             [{"Type": "volume", "Destination": "/served", "Source": "/volumes/logs/_data", "RW": False}], "fail"),
            ("canonical-symlink", "/link/server.log", "/logs/server.log",
             [{"Destination": "/logs", "Source": "/host/logs"}],
             [{"Destination": "/served", "Source": "/host/logs"}], "fail"),
            ("private-layer", "/logs/server.log", "/logs/server.log", [], [], "pass"),
            ("separate-namespace", "/logs/server.log", "/logs/server.log",
             [{"Destination": "/logs", "Source": "/host/private"}],
             [{"Destination": "/logs", "Source": "/host/public"}], "pass"),
            ("nested-mount", "/logs/nested/server.log", "/logs/nested/server.log",
             [{"Destination": "/logs", "Source": "/host/logs"}, {"Destination": "/logs/nested", "Source": "/host/nested"}],
             [{"Destination": "/served", "Source": "/host/nested"}], "fail"),
            ("nested-shadow", "/logs/nested/server.log", "/logs/nested/server.log",
             [{"Destination": "/logs", "Source": "/host/logs"}, {"Destination": "/logs/nested", "Source": "/host/nested"}],
             [{"Destination": "/served", "Source": "/host/logs"}], "pass"),
        ):
            with self.subTest(name=name):
                obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
                obj.process = {"flags": {"log": log}, "port": "8081"}
                obj.containers = {
                    "botapi": {"Config": {}, "Mounts": [state] + api_mounts},
                    "gateway": {"Mounts": http_mounts, "NetworkSettings": {"Ports": {}}},
                }
                obj.exec = lambda service, *args, **kwargs: ((canonical + "\n").encode() if LOG_CANONICAL in args else
                    b"server { listen 80; location /alternate { alias /served; } location / { proxy_pass http://botapi:8081; } }")
                obj.exposure()
                result = next(c for c in obj.checks if c["id"].endswith(".state_exposure"))
                self.assertEqual(expected, result["status"])
                if expected == "fail":
                    self.assertEqual("state_root_exposed", result["reason_code"])

    def test_stats_and_alternative_root(self):
        roots, proxies, _, dynamic = nginx_routes(nginx_config('server { location /alternative { root /var/lib/telegram-bot-api; } location /s { proxy_pass http://botapi:8082; } }'))
        self.assertEqual(["/var/lib/telegram-bot-api"], roots)
        self.assertEqual(["http://botapi:8082"], proxies)
        self.assertFalse(dynamic)
