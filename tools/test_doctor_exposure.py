import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
from doctor import parser
from doctor_checks import nginx_config, nginx_routes, backing
from doctor_runtime import Installation


class ExposureTests(unittest.TestCase):
    def test_split_media_consumers_are_scoped_readonly_and_still_unknown(self):
        for source, rw, unsafe in (('/host/media/bot-a', False, False),
                                   ('/host/media', False, True),
                                   ('/host/media/bot-a', True, True),
                                   ('/host/state', False, True)):
            obj = Installation(parser().parse_args(['--scenario', 'official-to-self']), None, None, [], [])
            obj.process = dict(work='/state', temp='/temp', files='/media')
            obj.containers = {'botapi': {'Mounts': [dict(Destination='/state', Source='/host/state'),
                dict(Destination='/media', Source='/host/media')]},
                'downloads': {'Mounts': [dict(Source=source, Destination='/media/bot-a', RW=rw)]}}
            obj.exposure()
            self.assertEqual(unsafe, any(c['status'] == 'fail' for c in obj.checks))
            self.assertTrue(any(c['reason_code'] == 'http_handler_unverified' for c in obj.checks) or unsafe)

    def test_shipped_logging_map_and_unknown_routes(self):
        from pathlib import Path
        config = (Path(__file__).resolve().parent.parent / "nginx.conf").read_text()
        roots, proxies, listens, unknown = nginx_routes(nginx_config(config))
        self.assertEqual(([], ["http://botapi:8081"], [80], False), (roots, proxies, listens, unknown))
        for extra in ("server { root $uri_redacted; }", "server { unknown_route on; }",
                      "map $uri $uri_redacted { root /private; }",
                      "map $request_uri $legacy_file_request { default 0; root /private; }",
                      "server { if ($legacy_file_request) { proxy_pass http://other:80; } }"):
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

    def test_only_known_static_denial_is_understood(self):
        self.assertFalse(nginx_routes(nginx_config('server { location /file/ { return 404; } }'))[-1])
        for directive in ('return $status;', 'return 302 /elsewhere;', 'return 40;',
                          'return 404 { root /private; }', 'rewrite / /other;',
                          'try_files $uri /fallback;', 'auth_basic on;'):
            with self.subTest(directive=directive):
                self.assertTrue(nginx_routes(nginx_config('server { location / { ' + directive + ' } }'))[-1])

    def test_current_alias_and_safe_gateway(self):
        for unsafe in (True, False):
            obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), None, None, [], [])
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

    def test_stats_and_alternative_root(self):
        roots, proxies, _, dynamic = nginx_routes(nginx_config('server { location /alternative { root /var/lib/telegram-bot-api; } location /s { proxy_pass http://botapi:8082; } }'))
        self.assertEqual(["/var/lib/telegram-bot-api"], roots)
        self.assertEqual(["http://botapi:8082"], proxies)
        self.assertFalse(dynamic)
