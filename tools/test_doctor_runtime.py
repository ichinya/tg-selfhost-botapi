import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
from doctor import parser
from doctor_checks import root_response, process_flags, container_state
from doctor_runtime import Installation, RunError


class RuntimeTests(unittest.TestCase):
    def test_lifecycle_is_more_than_running(self):
        for flag in ("Paused", "Restarting", "Dead"):
            self.assertEqual("fail", container_state({"State": {"Running": True, flag: True}})[0])
        self.assertEqual(("fail", "service_unhealthy"), container_state({"State": {"Running": True, "Health": {"Status": "unhealthy"}}}))
        self.assertEqual("unknown", container_state({"State": {"Running": True, "Health": {"Status": "starting"}}})[0])

    def test_direct_route_unavailable_is_not_gateway_failure(self):
        class Transport:
            def get(self, url):
                raise RunError("unavailable")
        obj = self.installation()
        obj.http = Transport()
        obj.probe("direct_http", "http://127.0.0.1/")
        obj.probe("gateway_http", "http://127.0.0.1/")
        self.assertEqual(["unknown", "fail"], [c["status"] for c in obj.checks])
        obj.local_bridge = lambda: True
        obj.probe("direct_http", "http://127.0.0.1/")
        self.assertEqual("fail", obj.checks[-1]["status"])

    def test_actual_image_digest_provenance_and_pinned_mismatch(self):
        from doctor_mock import StackRunner
        for local in (False, True):
            runner = StackRunner()
            if local:
                runner.model["services"]["botapi"]["build"] = {"context": "."}
            obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), runner, None, [], [])
            obj.configuration()
            obj.runtime()
            image = next(i for i in obj.images if i["role"] == "target.botapi")
            self.assertEqual("local_build" if local else "registry_digest_unavailable", image["registry_digest_reason"])
            self.assertEqual(runner.containers[0]["Image"], image["image_id"])
        runner = StackRunner(pinned=True)
        runner.images[runner.containers[0]["Image"]]["RepoDigests"] = ["synthetic@sha256:" + "8" * 64]
        obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), runner, None, [], [])
        obj.configuration()
        obj.runtime()
        self.assertTrue(any(c["reason_code"] == "digest_mismatch" and c["status"] == "fail" for c in obj.checks))

    def test_root_contract(self):
        valid = b'{"ok":false,"error_code":404}'
        self.assertTrue(root_response(404, "application/json; charset=utf-8", valid))
        for status, kind, body in [(200, "application/json", valid), (404, "text/html", valid),
                                   (302, "application/json", valid), (404, "application/json", b'{"ok":false,"error_code":true}'),
                                   (404, "application/json", b"x" * 16385)]:
            self.assertFalse(root_response(status, kind, body))

    def test_flags(self):
        self.assertEqual({"dir": "/a b", "http-port": "8081", "local": True},
                         process_flags(["--dir=/a b", "--http-port", "8081", "--local"]))
        for args in (["--dir"], ["--dir=x", "--dir=y"], ["unrecognised"]):
            with self.assertRaises(ValueError):
                process_flags(args)

    def installation(self, url=None):
        args = parser().parse_args(["--scenario", "official-to-self"] + (["--gateway-url", url] if url else []))
        obj = Installation(args, None, None, [], [])
        obj.gateway_route_verified = True
        obj.published_routes_supported = lambda: True
        obj.containers["gateway"] = {"NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18080"}]}}}
        return obj

    def test_binding_mapping(self):
        self.assertEqual(("http://127.0.0.1:18080/", "80/tcp"), self.installation().gateway_endpoint())
        self.assertEqual((None, None), self.installation("https://external.invalid/api/").gateway_endpoint())
        obj = self.installation()
        obj.containers["gateway"]["NetworkSettings"]["Ports"]["80/tcp"].append({"HostIp": "::", "HostPort": "18080"})
        self.assertEqual((None, None), obj.gateway_endpoint())

    def test_capture_tokenless_http(self):
        class Transport:
            calls = []
            def get(self, url):
                self.calls.append(url)
                return 404, "application/json", b'{"ok":false,"error_code":404}'
        obj = self.installation()
        obj.http = Transport()
        obj.probes()
        self.assertEqual(["http://127.0.0.1:18080/"], obj.http.calls)
        self.assertFalse(any("bot" in u or "stat" in u or "telegram.org" in u for u in obj.http.calls))
        obj.http.calls.clear()
        obj.published_routes_supported = lambda: False
        obj.probes()
        self.assertFalse(obj.http.calls)
        self.assertEqual("endpoint_mapping_unverified", obj.checks[-1]["reason_code"])
