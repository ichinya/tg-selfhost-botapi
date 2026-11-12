"""Offline tests: no Docker discovery, pulls or long sleeps."""
import hashlib
import http.client
import json
import select
import shutil
import socket
import subprocess
import time
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_gateway_uploads as gateway
from gateway_upload_mock import Multipart, Handler, State


@unittest.skipUnless(shutil.which("nginx") and sys.platform != "win32", "nginx POSIX fixture unavailable")
class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.upstream.state = State()
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        def port():
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                return s.getsockname()[1]
        self.public, self.trusted, management = port(), port(), port()
        conf = (gateway.ROOT / "nginx.conf").read_text(encoding="utf-8")
        conf = conf.replace("listen 80;", f"listen 127.0.0.1:{self.public};")
        conf = conf.replace("listen 82;", f"listen 127.0.0.1:{self.trusted};")
        conf = conf.replace("listen 81;", f"listen 127.0.0.1:{management};")
        conf = conf.replace("~*^80:.+", f"~*^{self.public}:.+")
        conf = conf.replace("http://botapi:8081", f"http://127.0.0.1:{self.upstream.server_port}")
        conf = conf.replace("/var/cache/nginx/client_temp", self.tmp.name + "/spool")
        conf = conf.replace("/var/log/nginx/access.log", self.tmp.name + "/access.log")
        conf = conf.replace("/var/log/nginx/error.log", self.tmp.name + "/error.log")
        conf = conf.replace("client_body_timeout 300s;", "client_body_timeout 2s;")
        path = Path(self.tmp.name) / "nginx.conf"
        path.write_text(f"pid {self.tmp.name}/nginx.pid;\nevents {{}}\nhttp {{\n{conf}\n}}\n")
        subprocess.run(["nginx", "-t", "-p", self.tmp.name, "-c", str(path)], check=True, capture_output=True)
        self.process = subprocess.Popen(["nginx", "-p", self.tmp.name, "-c", str(path), "-g", "daemon off;"], stderr=subprocess.PIPE)
        self.addCleanup(self.stop_nginx)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.public), timeout=.1).close()
                break
            except OSError:
                time.sleep(.02)
        else:
            self.fail("nginx did not start: " + self.process.stderr.read().decode())

    def stop_nginx(self):
        self.process.terminate()
        self.process.communicate(timeout=5)

    def send(self, method, path, headers=None, body=None, port=None):
        conn = http.client.HTTPConnection("127.0.0.1", port or self.public, timeout=4)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def hold(self, case, address="127.0.0.1"):
        sock = socket.socket()
        sock.settimeout(4)
        sock.bind((address, 0))
        sock.connect(("127.0.0.1", self.trusted))
        sock.sendall((f"POST /bot12345:synthetic/sendDocument HTTP/1.1\r\nHost: test\r\nX-Case: {case}\r\nTransfer-Encoding: chunked\r\n\r\n1\r\nx\r\n").encode())
        time.sleep(.05)
        return sock

    def test_public_rejects_chunked_methods_and_get_bodies_before_upstream(self):
        path = "/bot12345:synthetic/sendDocument"
        for method in ("PUT", "DELETE", "PATCH"):
            self.assertEqual(self.send(method, path, {"X-Case": method}, b"x"), 403)
        for method in ("GET", "HEAD"):
            self.assertEqual(self.send(method, path, {"X-Case": method}, b"x"), 400)
        results = []
        def chunk(i):
            results.append(self.send("POST", path, {"Transfer-Encoding": "chunked", "X-Case": f"chunk{i}"}, b"1\r\nx\r\n0\r\n\r\n"))
        threads = [threading.Thread(target=chunk, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [411] * 4)
        self.assertFalse(self.upstream.state.receipts)
        self.assertFalse(list((Path(self.tmp.name) / "spool").rglob("*")))

    def test_slots_release_after_abort_and_timeout_rpc_and_second_client(self):
        first, second = self.hold("first"), self.hold("second")
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        rejected = self.hold("rejected")
        self.addCleanup(rejected.close)
        self.assertIn(b" 429 ", rejected.recv(4096))
        other = self.hold("other", "127.0.0.2")
        self.addCleanup(other.close)
        other2 = self.hold("other2", "127.0.0.2")
        self.addCleanup(other2.close)
        overflow = self.hold("overflow", "127.0.0.3")
        self.addCleanup(overflow.close)
        self.assertIn(b" 429 ", overflow.recv(4096))
        self.assertEqual(self.send("GET", "/bot12345:synthetic/getMe"), 200)
        first.close()
        time.sleep(.3)
        replacement = self.hold("replacement")
        self.addCleanup(replacement.close)
        self.assertFalse(select.select([replacement], [], [], .1)[0])
        self.assertEqual(second.recv(4096), b"")  # nginx records 408 then closes
        self.assertIn(' 408 ', (Path(self.tmp.name) / "access.log").read_text())
        time.sleep(.3)
        after = self.hold("after")
        self.addCleanup(after.close)
        self.assertFalse(select.select([after], [], [], .1)[0])
        self.assertFalse(self.upstream.state.receipts)

    def test_rate_burst_returns_429_without_upstream(self):
        path = "/bot12345:synthetic/sendDocument"
        statuses = [self.send("POST", path, {"X-Case": f"burst{i}"}, b"") for i in range(12)]
        self.assertIn(429, statuses)
        for i, status in enumerate(statuses):
            if status == 429:
                self.assertNotIn(f"burst{i}", self.upstream.state.receipts)


class GatewayTests(unittest.TestCase):
    def test_exact_multipart_and_split_boundaries(self):
        with gateway.temporary_directory() as directory:
            body = gateway.Body(Path(directory) / "source", 103, total=2048)
            data = b"".join(body)
            self.assertEqual(len(data), 2048)
            for step in (1, 2, 23, 128, 65536):
                parser = Multipart(gateway.BOUNDARY)
                for offset in range(0, len(data), step):
                    parser.feed(data[offset:offset + step])
                receipt = parser.finish()
                self.assertEqual(receipt["body_sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(receipt["parts"][1]["bytes"], 103)
                self.assertEqual(receipt["parts"][1]["sha256"], hashlib.sha256(bytes(103)).hexdigest())

    def test_truncated_and_impossible(self):
        with gateway.temporary_directory() as directory:
            with self.assertRaises(ValueError):
                gateway.Body(Path(directory) / "source", 500, 5)
        with self.assertRaises(ValueError):
            Multipart(b"boundary").finish()

    def test_http_expect_length_and_chunked(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.state = State()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with gateway.temporary_directory() as directory:
                body = gateway.Body(Path(directory) / "source", 130000)
                for framing in (False, True):
                    result = gateway.request("127.0.0.1", server.server_port, body, str(framing), chunked=framing)
                    self.assertEqual(result["status"], 200)
                    self.assertEqual(result["interim"], [100])
                    self.assertEqual(result["response"]["body_bytes"], body.size)
                    self.assertEqual(result["response"]["body_sha256"], result["body_sha256"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_report_never_passes_missing_or_failed_cleanup(self):
        for report, expected in (({"cleanup": "PASS", "scenarios": []}, "NOTRUN"),
                                 ({"cleanup": "PASS", "scenarios": [{"status": "NOTRUN"}]}, "NOTRUN"),
                                 ({"cleanup": "FAIL", "scenarios": [{"status": "PASS"}]}, "FAIL"),
                                 ({"cleanup": "PASS", "scenarios": [{"status": "FAIL"}]}, "FAIL")):
            self.assertEqual(gateway.final_status(report), expected)

    def test_manifest_isolated_and_loopback(self):
        manifest = gateway.compose_manifest("issue4-test", "nginx@sha256:test", "python@sha256:test", "/tmp/config")
        text = json.dumps(manifest)
        self.assertNotIn("./data", text)
        self.assertEqual(manifest["services"]["botapi"]["ports"], [])
        for service in manifest["services"].values():
            self.assertTrue(all(port.startswith("127.0.0.1::") for port in service["ports"]))
            self.assertEqual(service["labels"][gateway.LABEL], "issue4-test")

    def test_cleanup_only_exact_label_and_failure(self):
        with gateway.temporary_directory() as directory:
            report = {"project": "issue4-test"}
            runner = gateway.Runner(None, report, directory)
            runner.docker_available = True
            with patch.object(gateway, "command", side_effect=["container-id", "", "network-id", "", "volume-id", ""]) as cmd:
                runner.cleanup()
                self.assertEqual(report["cleanup"], "PASS")
                for call in cmd.call_args_list[::2]:
                    self.assertIn(f"label={gateway.LABEL}=issue4-test", call.args[0])
            with patch.object(gateway, "command", side_effect=RuntimeError("denied")):
                runner.cleanup()
                self.assertEqual(report["cleanup"], "FAIL")

    def test_size_inventory_and_incomplete_report(self):
        cases = gateway.size_cases(gateway.LIMIT)
        self.assertEqual(len(cases), 6)
        self.assertEqual({c[2] for c in cases}, {gateway.LIMIT - 1, gateway.LIMIT, gateway.LIMIT + 1})
        self.assertIn("file-2000m", gateway.inventory("full"))
        self.assertEqual(gateway.final_status({"cleanup": "PASS", "expected": ["one", "two"],
                                             "scenarios": [{"name": "one", "status": "PASS"}]}), "FAIL")

    def test_large_source_is_not_loaded_in_memory(self):
        with gateway.temporary_directory() as directory:
            body = gateway.Body(Path(directory) / "source", 1024 * 1024, gateway.LIMIT + 1)
            self.assertEqual(body.size, gateway.LIMIT + 1)
            chunks = iter(body)
            next(chunks)
            self.assertLessEqual(len(next(chunks)), gateway.CHUNK)
            chunks.close()

    def test_inventory_all_is_complete_and_unique(self):
        names = gateway.inventory("all")
        self.assertEqual(len(names), len(set(names)))
        for profile in ("fast", "full", "slow", "storage"):
            self.assertGreater(len(gateway.inventory(profile)), 0)
            self.assertTrue(set(gateway.inventory(profile)).issubset(names))
        for framing in ("length", "chunked"):
            self.assertIn("send70-" + framing, names)
            self.assertIn("storage-crash-" + framing, names)
        self.assertIn("disk-full", names)

    def test_idle_client_accepts_eof_only_with_access_408(self):
        from types import SimpleNamespace
        runner = SimpleNamespace(directory=Path('.'), port=80, gateway="synthetic", receipts=lambda: {})
        with patch.object(gateway, "Body"), patch.object(gateway, "request", return_value={"status": None, "elapsed": 2.1, "started": 0}), \
                patch.object(gateway, "command", return_value='"POST /bot<redacted>/sendDocument/client2-test HTTP/1.1" 408 0'):
            self.assertTrue(gateway.idle_client(runner, "client2-test", False)["access_408"])
        with patch.object(gateway, "Body"), patch.object(gateway, "request", return_value={"status": None, "elapsed": 2.1, "started": 0}), \
                patch.object(gateway, "command", return_value=''):
            with self.assertRaises(AssertionError):
                gateway.idle_client(runner, "client2-test", False)

    def test_snapshot_counts_deleted_open_files(self):
        report = {"project": "issue4-test"}
        runner = gateway.Runner(None, report, ".")
        sample = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/test 10000 10 9990 1% /var/cache/nginx/client_temp\nfile:123:100:8\nfd:123:100:8\nfd:124:200:16"
        with patch.object(runner, "compose", return_value=sample):
            self.assertEqual(runner.snapshot(), {"free": 9990 * 1024, "files": 1, "fds": 2, "fds_skipped": 0, "bytes": 300, "blocks": 24 * 512})

    def test_snapshot_counts_skipped_descriptors(self):
        runner = gateway.Runner(None, {"project": "issue4-test"}, ".")
        with patch.object(runner, "compose", return_value="/dev/test 100 10 90 10% /temp\nfdskip\nfdskip"):
            self.assertEqual(runner.snapshot()["fds_skipped"], 2)

    def test_await_clean_rejects_unobservable_descriptors(self):
        runner = gateway.Runner(None, {"project": "issue4-test"}, ".")
        with patch.object(runner, "snapshot", return_value={"free": 100, "files": 0, "fds": 0, "blocks": 0, "fds_skipped": 1}):
            with self.assertRaises(gateway.NotRun):
                runner.await_clean({"free": 0})

    def test_await_clean_requires_all_empty_and_observable(self):
        runner = gateway.Runner(None, {"project": "issue4-test"}, ".")
        clean = {"free": 100, "files": 0, "fds": 0, "blocks": 0, "fds_skipped": 0}
        for key in ("files", "fds", "blocks"):
            with self.subTest(key=key), patch.object(runner, "snapshot", side_effect=[dict(clean, **{key: 1}), clean]), patch.object(gateway.time, "sleep"):
                self.assertEqual(runner.await_clean({"free": 0}), clean)

    def test_worker_fd_probe_reports_unavailable(self):
        runner = gateway.Runner(None, {"project": "issue4-test"}, ".")
        with patch.object(runner, "compose", side_effect=RuntimeError("denied")):
            with self.assertRaisesRegex(gateway.NotRun, "worker fd observation unavailable"):
                runner.fd_observation_probe()

    def test_manifest_grants_observation_only_to_gateway(self):
        services = gateway.compose_manifest("issue4-test", "nginx", "python", "/tmp/config")["services"]
        self.assertEqual(services["gateway"]["cap_add"], ["SYS_PTRACE"])
        self.assertNotIn("cap_add", services["botapi"])

    def test_async_error_and_capacity_notrun(self):
        def fail():
            raise ValueError("synthetic")
        with self.assertRaises(ValueError):
            gateway.AsyncCall(fail).finish()
        from types import SimpleNamespace
        runner = SimpleNamespace(directory=".", compose=lambda *a: "Filesystem x y available z mount\n/dev/test 10 9 1 90% /temp")
        with patch.object(gateway.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaises(gateway.NotRun):
                gateway.capacity(runner)

    def test_unavailable_docker_report_without_daemon_calls(self):
        class Unavailable:
            def __init__(self, args, report, directory):
                self.report = report
            def start(self):
                raise gateway.NotRun("synthetic missing daemon")
            def cleanup(self):
                self.report["cleanup"] = "PASS"
        with gateway.temporary_directory() as directory:
            target = Path(directory) / "report.json"
            with patch.object(gateway, "Runner", Unavailable):
                status = gateway.main(["--profile", "all", "--revision", "synthetic", "--report", str(target)])
            report = json.loads(target.read_text())
            self.assertEqual(status, 2)
            self.assertEqual(report["status"], "NOTRUN")
            self.assertEqual(len(report["scenarios"]), len(gateway.inventory("all")))
            self.assertTrue(all(row["status"] == "NOTRUN" for row in report["scenarios"]))

    def test_early_413_does_not_send_huge_body(self):
        class Reject(Handler):
            def handle_expect_100(self):
                self.send_error(413)
                return False
        server = ThreadingHTTPServer(("127.0.0.1", 0), Reject)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with gateway.temporary_directory() as directory:
                body = gateway.Body(Path(directory) / "source", 1024, gateway.LIMIT + 1)
                for chunked in (False, True):
                    result = gateway.request("127.0.0.1", server.server_port, body, "early", chunked=chunked)
                    self.assertEqual((result["status"], result["sent"]), (413, 0))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_workflow_has_clean_export_and_external_cleanup(self):
        workflow = (gateway.ROOT / ".github/workflows/gateway-upload-acceptance.yml").read_text(encoding="utf-8")
        for required in ("git archive HEAD", "ubuntu-24.04", "actions/checkout@v7", "node-version: '24'",
                         "contents: read", "cancel-in-progress: false", "--profile all", "2700", "if: always()",
                         gateway.LABEL, "external_cleanup", "if-no-files-found: error"):
            self.assertIn(required, workflow)

    def test_quick_alias_and_current_nginx_contract(self):
        self.assertEqual(gateway.inventory("quick"), gateway.inventory("fast"))
        config = (gateway.ROOT / "nginx.conf").read_text(encoding="utf-8")
        limit = max(map(int, gateway.re.findall(r"client_max_body_size\s+(\d+)m;", config))) * 1024 ** 2
        self.assertEqual(gateway.LIMIT, limit)
        self.assertEqual(gateway.NGINX_IMAGE, "nginx:1.28.0-alpine3.21")

    def test_checkpoint_redacts_receipts_and_embedded_errors(self):
        from types import SimpleNamespace
        with gateway.temporary_directory() as directory:
            target = Path(directory) / "report.json"
            report = {"project": "issue4-test", "cleanup": "PASS", "scenarios": [],
                      "receipt": {"uri": "/bot12345:synthetic/getMe?fixture=1"},
                      "error": "failure for /bot12345:synthetic/getMe?fixture=1"}
            runner = gateway.Runner(SimpleNamespace(report=target), report, directory)
            runner.checkpoint()
            saved = target.read_text(encoding="utf-8")
            self.assertNotIn("12345:synthetic", saved)
            self.assertNotIn("fixture=1", saved)
            self.assertIn("<redacted>", saved)
            self.assertIn("fixture=1", report["receipt"]["uri"])

    def test_slow_controls_change_one_timeout_at_a_time(self):
        from types import SimpleNamespace
        overrides = []
        runner = SimpleNamespace(configure=lambda **values: overrides.append(values),
                                 case=lambda *args: None, control=lambda *args, **kwargs: None)
        gateway.run_slow(runner)
        controls = [values for values in overrides if values]
        self.assertEqual(controls, [{"client_body_timeout": "2s"}, {"proxy_read_timeout": "2s"},
                                    {"proxy_send_timeout": "2s"}] * 2)

    def test_upstream_503_keeps_complete_receipt(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.state = State()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with gateway.temporary_directory() as directory:
                body = gateway.Body(Path(directory) / "source", 103, total=2048, extra_file=True)
                for chunked in (False, True):
                    case = "upstream503-" + str(chunked)
                    server.state.controls[case] = {"status": 503}
                    result = gateway.request("127.0.0.1", server.server_port, body, case, chunked=chunked)
                    self.assertEqual(result["status"], 503)
                    receipt = gateway.json_http(server.server_port, "/__receipts")[case]
                    self.assertTrue(receipt["body_received"])
                    self.assertEqual(receipt["body_sha256"], result["body_sha256"])
                    self.assertIn('filename="extra.bin"', receipt["parts"][2]["headers"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_certificate_multipart_preserves_method_and_public_file(self):
        from types import SimpleNamespace
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.state = State()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with gateway.temporary_directory() as directory:
                directory = Path(directory)
                def synthetic_openssl(args, timeout):
                    self.assertEqual(args[:2], ["openssl", "req"])
                    Path(args[args.index("-out") + 1]).write_bytes(b"-----BEGIN CERTIFICATE-----\nsynthetic\n-----END CERTIFICATE-----\n")
                    Path(args[args.index("-keyout") + 1]).write_text("synthetic disposable key")
                runner = SimpleNamespace(directory=directory, port=server.server_port,
                                         receipts=lambda: gateway.json_http(server.server_port, "/__receipts"))
                with patch.object(gateway, "command", side_effect=synthetic_openssl):
                    result = gateway.certificate_upload(runner)
                self.assertEqual(result["client"]["status"], 200)
                self.assertFalse((directory / "synthetic-key.pem").exists())
                self.assertIn("/setWebhook?", result["receipt"]["uri"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
