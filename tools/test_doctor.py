import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

import doctor
from doctor_checks import check, report, render_text, redact
from doctor_runtime import Runner, RunError, Budget, Http, endpoint, http_worker


def assert_contract_schema(value, schema):
    """Exercise the report's structural/type subset with stdlib only."""
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        assert type(value) in [types[n] for n in names], (value, schema)
    if "const" in schema:
        assert value == schema["const"] and type(value) is type(schema["const"])
    if "enum" in schema:
        assert any(type(value) is type(item) and value == item for item in schema["enum"]), (value, schema)
    if isinstance(value, dict):
        assert set(schema.get("required", [])) <= value.keys()
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        if extra is False:
            assert value.keys() <= properties.keys(), value.keys() - properties.keys()
        for key, item in value.items():
            if key in properties:
                assert_contract_schema(item, properties[key])
            elif isinstance(extra, dict):
                assert_contract_schema(item, extra)
    if isinstance(value, list):
        assert schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", float("inf"))
        if schema.get("uniqueItems"):
            assert len({json.dumps(item, sort_keys=True) for item in value}) == len(value)
        for item in value:
            assert_contract_schema(item, schema.get("items", {}))
    if isinstance(value, str):
        assert len(value) <= schema.get("maxLength", float("inf"))
    if type(value) in (int, float):
        assert schema.get("minimum", -float("inf")) <= value <= schema.get("maximum", float("inf"))


class FakeRunner:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.budget = Budget()
    def run(self, argv):
        if not self.responses:
            raise RunError("unavailable")
        return self.responses.pop(0)


class DoctorTests(unittest.TestCase):
    def test_log_reports_verdict_schema_privacy_and_transport(self):
        from urllib.parse import quote, urlsplit
        from doctor_mock import StackRunner, FakeHttp
        from doctor_runtime import collect
        from check_doctor import assert_commands
        token = "123456789:synthetic_Doctor_token_canary_0123456789"
        encoded = quote(token, safe="")
        private_log = "/private-log/" + token + "/" + encoded + "/server.log"
        relative = "relative-" + encoded + ".log"
        cases = [
            ("safe", {"log_argv": private_log}, 0, "state_mount_isolated"),
            ("unsafe", {"log_argv": private_log, "share_log": True}, 1, "state_root_exposed"),
            ("env-only", {"log_env": private_log, "share_log": True}, 1, "state_root_exposed"),
            ("equal", {"log_argv": private_log, "log_env": private_log, "share_log": True}, 1, "state_root_exposed"),
            ("unsafe-argv", {"log_argv": private_log, "log_env": "/isolated/server.log", "share_log": True}, 1, "state_root_exposed"),
            ("unsafe-env", {"log_argv": "/isolated/server.log", "log_env": private_log, "share_log": True}, 1, "state_root_exposed"),
            ("relative", {"log_argv": relative}, 3, "state_isolation_unverified"),
            ("divergence", {"log_argv": private_log, "log_env": relative}, 3, "state_isolation_unverified"),
            ("metadata-error", {"log_argv": private_log, "log_metadata": {private_log: RunError(encoded)}}, 3, "state_isolation_unverified"),
            ("fail-and-unknown", {"log_argv": private_log, "share_log": True, "log_metadata": {private_log: RunError(token)}}, 1, "state_root_exposed"),
            ("process-unavailable", {"log_argv": private_log, "process_error": True}, 3, "state_isolation_unverified"),
            ("missing-setting", {"missing": True}, 1, "missing_setting"),
            ("stopped-gateway", {"log_argv": private_log, "stopped": True}, 1, "service_stopped"),
        ]
        schema = json.loads(pathlib.Path(doctor.__file__).with_name("doctor.schema.json").read_text(encoding="utf-8"))
        for scenario, role in (("official-to-self", "target"), ("self-to-official", "source")):
            for name, options, expected, reason in cases:
                for fmt in ("text", "json"):
                    with self.subTest(scenario=scenario, case=name, format=fmt):
                        runner = StackRunner(**options)
                        http = FakeHttp([(404, "application/json", b'{"ok":false,"error_code":404}')] * 2)
                        def collector(args, runner, http, checks, images):
                            # Inject parsed operator declarations; exercise the real collector stages.
                            args.migration_data = dict(schema_version=1, workflow_prepared=True, file_access="not_used",
                                delivery_action="polling", drop_pending_updates=False, source_backup_prepared=True,
                                source_backlog_policy="drain")
                            args.input_secure = True
                            collect(args, runner, http, checks, images)
                        out, err = io.StringIO(), io.StringIO()
                        with patch("doctor_runtime.sys.platform", "linux"), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                            code = doctor.main(["--scenario", scenario, "--format", fmt], runner=runner, http=http, collector=collector)
                        self.assertEqual(expected, code, out.getvalue())
                        for canary in (token, encoded, private_log, relative):
                            self.assertNotIn(canary, out.getvalue() + err.getvalue())
                        self.assertEqual("", err.getvalue())
                        self.assertIn(reason, out.getvalue())
                        verdict = {0: "READY", 1: "BLOCKED", 3: "UNKNOWN"}[expected]
                        if fmt == "json":
                            result = json.loads(out.getvalue())
                            assert_contract_schema(result, schema)
                            self.assertEqual((expected, verdict), (result["exit_code"], result["readiness"]["verdict"]))
                            self.assertEqual([role], result["scope"]["contexts"])
                            if reason == "state_root_exposed":
                                findings = {c["check_id"]: c for c in result["checks"]}
                                for check_id in ("state_exposure", "state_mount_accessible"):
                                    self.assertEqual("FAIL", findings[role + "." + check_id]["status"])
                        else:
                            self.assertIn("Migration preflight: " + verdict, out.getvalue())
                            self.assertIn("Exit code: " + str(expected), out.getvalue())
                        assert_commands(runner.calls)
                        for url in http.calls:
                            parsed = urlsplit(url)
                            self.assertEqual("http", parsed.scheme)
                            self.assertIn(parsed.netloc, {"172.19.0.2:8081", "127.0.0.1:18080"})
                            self.assertEqual(("/", "", ""), (parsed.path, parsed.query, parsed.fragment))

    def test_log_report_http_failure_and_invalid_invocation(self):
        from doctor_mock import StackRunner, FakeHttp
        from doctor_runtime import collect
        from check_doctor import assert_commands
        runner = StackRunner(log_argv="/private-log/server.log")
        http = FakeHttp([RunError("synthetic private response")] * 2)
        def collector(args, runner, http, checks, images):
            args.migration_data = dict(schema_version=1, workflow_prepared=True, file_access="not_used",
                delivery_action="polling", drop_pending_updates=False)
            args.input_secure = True
            collect(args, runner, http, checks, images)
        out, err = io.StringIO(), io.StringIO()
        with patch("doctor_runtime.sys.platform", "linux"), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doctor.main(["--scenario", "official-to-self", "--format", "json"], runner=runner, http=http, collector=collector)
        self.assertEqual(1, code)
        self.assertEqual("BLOCKED", json.loads(out.getvalue())["readiness"]["verdict"])
        self.assertNotIn("synthetic private response", out.getvalue() + err.getvalue())
        assert_commands(runner.calls)
        for fmt in ("text", "json"):
            runner = StackRunner(log_argv="/private-log/server.log")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = doctor.main(["--scenario", "official-to-self", "--format", fmt, "--log=synthetic-private-canary"], runner=runner)
            self.assertEqual(2, code)
            self.assertFalse(runner.calls)
            self.assertNotIn("synthetic-private-canary", out.getvalue() + err.getvalue())

    def test_shipped_sources_are_utf8_without_bom_and_lf(self):
        root = pathlib.Path(__file__).resolve().parent
        paths = [root / name for name in (
            "doctor.py", "doctor_checks.py", "doctor_runtime.py", "doctor_mock.py",
            "check_doctor.py", "doctor.schema.json", "doctor-input.schema.json")]
        paths += list(root.glob("test_doctor*.py")) + [root / "test_check_doctor.py"]
        paths += [p for p in (root / "doctor_fixtures").iterdir() if p.is_file()]
        paths += [root.parent / ".github/workflows/doctor.yml"]
        for path in paths:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r", raw)
                raw.decode("utf-8")

    def test_v1_contract_and_error_priority(self):
        result = report("official-to-self", [check("migration.plan", "unknown", "missing", "Missing")])
        self.assertEqual(3, result["exit_code"])
        self.assertIn("infrastructure", result)
        self.assertNotIn("installation", result)
        self.assertNotIn("executor_support", result)
        self.assertIn("executor_support", result["migration"])
        self.assertEqual("migration.plan", result["checks"][0]["check_id"])
        self.assertEqual("UNKNOWN", result["checks"][0]["status"])
        self.assertEqual(2, report(None, [], error=True)["exit_code"])

    def test_text_json_parity_and_injection(self):
        seen = []
        def collect(args, runner, http, checks, images):
            seen.append((runner, http))
            checks.append(check("ready", "unknown", "missing", "Missing evidence."))
        for fmt in ("text", "json"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = doctor.main(["--scenario", "official-to-self", "--format", fmt],
                                   runner="runner", http="http", collector=collect)
            self.assertEqual(3, code)
            self.assertIn("UNKNOWN", output.getvalue())
            if fmt == "json":
                self.assertEqual(3, json.loads(output.getvalue())["exit_code"])
        self.assertEqual([("runner", "http")] * 2, seen)

    def test_shared_deadline(self):
        now = [0]
        budget = Budget(5, 6, lambda: now[0])
        self.assertEqual(5, budget.remaining())
        now[0] = 4
        self.assertEqual(2, budget.remaining())
        now[0] = 6
        with self.assertRaises(RunError):
            budget.remaining()

    def test_http_failure_does_not_expose_output(self):
        runner = FakeRunner([(1, b"private response payload")])
        with self.assertRaises(RunError) as caught:
            Http(runner).get("http://127.0.0.1:18080/")
        self.assertNotIn("private", str(caught.exception))

    def test_unknown_smoke_and_retained_findings(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = doctor.main(["--scenario", "official-to-self", "--format", "json"], runner=FakeRunner())
        result = json.loads(output.getvalue())
        self.assertEqual(3, code)
        self.assertEqual("UNKNOWN", result["readiness"]["verdict"])
        self.assertTrue(result["migration"]["pending_actions"])

    def test_schema_top_level_contract(self):
        from pathlib import Path
        schema = json.loads(doctor.__loader__.get_data(str(Path(doctor.__file__).with_name("doctor.schema.json"))).decode("utf-8-sig"))
        result = report("official-to-self", [check("a", "unknown", "missing", "Missing")])
        self.assertEqual(set(schema["required"]), set(result))
        self.assertEqual(set(schema["properties"]), set(result))
        assert_contract_schema(result, schema)

    def test_endpoint_rejection(self):
        for url in ("http://user:pass@localhost/", "https://api.telegram.org/", "http://localhost/botprivate/",
                    "http://localhost/%2f", "http://localhost/../", "http://localhost/?secret=x", "http://localhost/\r\n"):
            with self.assertRaises(ValueError):
                endpoint(url)
        for path in ("/stats", "/getMe", "/file/"):
            with self.assertRaises(ValueError):
                Http(FakeRunner()).get("http://127.0.0.1" + path)
            with self.assertRaises(ValueError):
                http_worker("http://127.0.0.1" + path, 1)

    def test_masking(self):
        self.assertNotIn("private", redact("private %70rivate", ("private", "%70rivate")))
        self.assertEqual("[redacted]", redact("123456:abcdefghijklmnopqrstuvwxyz"))

    def test_worker_body_limit_and_redirect(self):
        class Response:
            status = 302
            def getheader(self, key, default):
                return "application/json"
            def read1(self, size):
                return b"x" * size
        class Connection:
            sock = None
            def __init__(self, *a, **kw):
                pass
            def request(self, *a, **kw):
                self.request_args = a
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch("http.client.HTTPConnection", Connection), self.assertRaises(RunError):
            http_worker("http://localhost/", 1)

    def test_aggregation(self):
        for statuses, code in [(["pass"], 0), (["unknown"], 3), (["unknown", "fail"], 1)]:
            result = report("official-to-self", [check(str(i), s, "test", "test") for i, s in enumerate(statuses)])
            self.assertEqual(code, result["exit_code"])
            self.assertIn(result["readiness"]["verdict"], render_text(result))
        self.assertEqual(2, report(None, [], error=True)["exit_code"])
        self.assertEqual(0, report(None, [check("x", "unknown", "x", "x", required=False)])["exit_code"])

    def test_skip_is_only_allowed_for_optional_checks(self):
        with self.assertRaises(ValueError):
            check("required", "not_applicable", "not_applicable", "Not applicable")
        optional = check("optional", "not_applicable", "not_applicable", "Not applicable", required=False)
        self.assertEqual("SKIP", report("official-to-self", [optional])["checks"][0]["status"])

    def test_evidence_allowlist(self):
        c = check("a", "pass", "ok", "ok", evidence={"secret": "secret", "count": 2, "available_bytes": "secret"})
        self.assertEqual({"count": 2}, c["evidence"])

    def test_capacity_options_require_positive_integers(self):
        for option in ("--min-free-bytes", "--min-free-inodes"):
            for value in ("1.5", "0", "-1", "nan", "inf"):
                with self.subTest(option=option, value=value):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = doctor.main(["--scenario", "official-to-self", "--format=json", option, value])
                    self.assertEqual(2, code)
                    self.assertEqual(2, json.loads(output.getvalue())["exit_code"])
            args = doctor.parser().parse_args(["--scenario", "official-to-self", option, "42"])
            self.assertEqual(42, getattr(args, option[2:].replace("-", "_")))

    def test_invalid_json_redacts(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()) as err:
            code = doctor.main(["--format", "json", "--scenario", "sensitive-value"])
        self.assertEqual(2, code)
        self.assertEqual(2, json.loads(output.getvalue())["exit_code"])
        self.assertNotIn("sensitive-value", output.getvalue() + err.getvalue())

    def test_internal_error_redacts(self):
        def broken(args, runner, http, checks, images):
            checks.append(check("earlier", "pass", "ok", "Observed"))
            raise RuntimeError("private")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(3, doctor.main(["--scenario", "official-to-self", "--format=json"], collector=broken))
        result = json.loads(output.getvalue())
        self.assertEqual(["earlier", "internal_error"], [c["check_id"] for c in result["checks"]])
        self.assertNotIn("private", output.getvalue())
        def blocked(args, runner, http, checks, images):
            checks.append(check("earlier", "fail", "blocked", "Blocked"))
            raise RuntimeError("private")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, doctor.main(["--scenario", "official-to-self"], collector=blocked))

    def test_runner_limit_and_timeout(self):
        with self.assertRaises(RunError):
            Runner(max_output=32).run([sys.executable, "-c", "print('x'*1000)"])
        with self.assertRaises(RunError):
            Runner(timeout=0.1).run([sys.executable, "-c", "import time; time.sleep(1)"])
        code, output = Runner().run([sys.executable, "-c", "print('ok')"])
        self.assertEqual((0, b"ok\n"), (code, output.replace(b"\r\n", b"\n")))


if __name__ == "__main__":
    unittest.main()
