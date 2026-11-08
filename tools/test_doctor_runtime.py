import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
import os
from doctor import parser
from doctor_checks import root_response, process_flags, container_state
from doctor_runtime import Installation, RunError


class RuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "container metadata primitives require POSIX; exercised by Linux CI")
    def test_log_metadata_regular_missing_symlink_and_special_paths(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from doctor_runtime import LOG_CANONICAL
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "server.log"
            regular.write_text("synthetic log sentinel", encoding="utf-8")
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            for path, expected in ((regular, str(regular)), (alias / "server.log", str(regular)),
                                   (alias / "missing" / "server.log", str(root / "missing" / "server.log"))):
                result = subprocess.run(["sh", "-c", LOG_CANONICAL, "doctor", str(path)],
                    capture_output=True, timeout=3)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected + "\n", result.stdout.decode())
            for path in (fifo, regular / "not-a-directory.log", root):
                result = subprocess.run(["sh", "-c", LOG_CANONICAL, "doctor", str(path)],
                    capture_output=True, timeout=3)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(b"", result.stdout)
            if os.geteuid() != 0:
                inaccessible = root / "inaccessible"
                inaccessible.mkdir()
                inaccessible.chmod(0)
                try:
                    result = subprocess.run(["sh", "-c", LOG_CANONICAL, "doctor", str(inaccessible / "missing" / "server.log")],
                        capture_output=True, timeout=3)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(b"", result.stdout)
                finally:
                    inaccessible.chmod(0o700)
            self.assertEqual("synthetic log sentinel", regular.read_text(encoding="utf-8"))

    def test_self_to_self_state_backing_identity(self):
        from unittest.mock import patch
        from doctor_runtime import collect
        args = parser().parse_args(["--scenario", "self-to-self", "--source-project-name", "source"])
        args.migration_data = {"transfer": {"method": "fresh-login"}}
        args.input_secure = True
        for inodes, sources, expected in (
            (("8:2", "8:2"), ("/host/a", "/host/b"), ("fail", "shared_state")),
            (("8:2", None), ("/host/a", "/host/b"), ("unknown", "state_backing_unverified")),
            (("8:2", "8:3"), ("/host/a", "/host/b"), ("pass", "distinct_state")),
            (("8:2", "8:3"), ("/host/a", "/host/a/nested"), ("fail", "shared_state")),
        ):
            with self.subTest(inodes=inodes, sources=sources):
                checks = []
                objects = []
                for inode, source in zip(inodes, sources):
                    obj = Installation(args, None, None, checks, [])
                    obj.storage_data = {"work": {"path": "/state", "inode": inode}}
                    obj.containers = {"botapi": {"Mounts": [{"Destination": "/state", "Source": source}]}}
                    for stage in ("configuration", "runtime", "storage", "exposure", "probes", "unchanged"):
                        setattr(obj, stage, lambda: None)
                    objects.append(obj)
                with patch("doctor_runtime.Installation", side_effect=objects):
                    collect(args, None, None, checks, [])
                result = next(c for c in checks if c["id"] == "migration.state_backing")
                self.assertEqual(expected, (result["status"], result["reason_code"]))

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
