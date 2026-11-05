"""Fail-closed Linux/POSIX acceptance for a loaded production candidate.

Only synthetic credentials and run-owned storage are used, with network=none.
ENTRYPOINT_FIXTURE/GROUP_FILESYSTEM simulate filesystem operations; REAL_BINARY
starts the production entrypoint without command arguments.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
STATE = "/var/lib/telegram-bot-api"
TEMP = "/tmp/telegram-bot-api"
ENV = {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "synthetic-placeholder",
       "TELEGRAM_LOCAL": "true", "TELEGRAM_WORK_DIR": STATE, "TELEGRAM_TEMP_DIR": TEMP}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def http_ready(exit_code, output):
    # BusyBox wget returns 1 for a token-free 404; never hide its exit in a pipe.
    return exit_code in (0, 1) and re.search(r"HTTP/1\.[01] (?:200|400|404)\b", output) is not None


def validate_botapi(service, test_root, name, image):
    require(service.get("container_name") == name, "unsafe Compose container_name")
    require(service.get("restart") == "no", "Compose restart must be disabled")
    require(service.get("network_mode") == "none", "Compose egress must be disabled")
    require(service.get("image") == image and service.get("user") == "1000:2000",
            "Compose changed candidate or custom GID")
    require(not service.get("ports"), "Compose must not publish ports")
    require(not service.get("command") and not service.get("entrypoint"),
            "Compose must start the production service defaults")
    environment = service.get("environment", {})
    require(all(environment.get(k) == v for k, v in ENV.items()
                if k not in ("TELEGRAM_WORK_DIR", "TELEGRAM_TEMP_DIR")), "non-synthetic Compose credentials")
    require(environment.get("TELEGRAM_WORK_DIR", STATE) == STATE and
            environment.get("TELEGRAM_TEMP_DIR", TEMP) == TEMP, "Compose storage env changed")
    mounts = service.get("volumes", [])
    require(len(mounts) == 2 and {v["target"] for v in mounts} == {STATE, TEMP},
            "unexpected Compose storage")
    for mount in mounts:
        source = Path(mount["source"]).resolve()
        require(source.is_relative_to(test_root.resolve()) and source != test_root.resolve(),
                "Compose mount escapes disposable root")
        require(mount["type"] == "bind" and mount.get("bind", {}).get("create_host_path") is False,
                "Compose must require prepared bind sources")
    state, temp = (Path(next(v["source"] for v in mounts if v["target"] == target)).resolve()
                   for target in (STATE, TEMP))
    require(not state.is_relative_to(temp) and not temp.is_relative_to(state),
            "state and temp must be separate trees")


class Matrix:
    def __init__(self, image):
        self.image = image
        self.prefix = "issue21-" + uuid.uuid4().hex[:12]
        self.containers = []
        self.volumes = []
        self.directory = None
        self.serial = 0

    def docker(self, *args, check=True, timeout=30, **kwargs):
        result = subprocess.run(["docker", *map(str, args)], capture_output=True,
                                text=True, timeout=timeout, **kwargs)
        if check and result.returncode:
            raise RuntimeError(f"docker {args[0]} child exit={result.returncode}: "
                               f"{result.stdout[-2000:]}{result.stderr[-2000:]}")
        return result

    def name(self):
        self.serial += 1
        name = f"{self.prefix}-{self.serial}"
        self.containers.append(name)  # Register before starting, including timeout paths.
        return name

    @staticmethod
    def mount(source, target, readonly=False, kind="bind"):
        return ["--mount", f"type={kind},source={source},target={target}" +
                (",readonly" if readonly else "")]

    def run(self, mounts, script, user="0:0", check=True, groups=()):
        return self.docker("run", "--rm", "--name", self.name(), "--network", "none",
                           "--user", user, *[item for group in groups for item in ("--group-add", group)],
                           "--entrypoint", "sh", *mounts,
                           self.image, "-ec", script, check=check)

    def exec(self, name, script, user="0:0", check=True):
        return self.docker("exec", "--user", user, name, "sh", "-ec", script, check=check)

    def prepare(self, mounts, uid, gid):
        self.run(mounts, f"chown {uid}:{gid} {STATE} {TEMP}; chmod 700 {STATE} {TEMP}; "
                 f"touch {STATE}/.issue21-prepared {TEMP}/.issue21-prepared")
        self.run(mounts, f'for dir in {STATE} {TEMP}; do '
                 f'test "$(stat -c %u:%g:%a "$dir")" = {uid}:{gid}:700 || '
                 '{ echo "Preparation failed on remount: $dir" >&2; exit 1; }; done')

    def start(self, mounts, user=None, environment=None):
        name = self.name()
        env = {**ENV, **(environment or {})}
        flags = [item for k, v in env.items() if v is not None for item in ("-e", f"{k}={v}")]
        self.docker("run", "-d", "--name", name, "--network", "none",
                    *(["--user", user] if user is not None else []), *mounts, *flags, self.image)
        return name

    def ready(self, name, uid, gid):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = json.loads(self.docker("inspect", name).stdout)[0]["State"]
            if not state["Running"]:
                logs = self.docker("logs", name)
                raise RuntimeError(f"server child exit={state['ExitCode']}: " +
                                   (logs.stdout + logs.stderr)[-2000:])
            result = self.docker("exec", "--user", f"{uid}:{gid}", name, "wget", "-T", "2",
                                 "-S", "-O", "/dev/null", "http://127.0.0.1:8081/", check=False)
            if http_ready(result.returncode, result.stdout + result.stderr):
                print(f"REAL_BINARY HTTP child exit={result.returncode}; server running", flush=True)
                return
            time.sleep(0.5)
        raise RuntimeError(f"readiness timeout; last HTTP child exit={result.returncode}")

    def verify_server(self, name, uid, gid):
        self.ready(name, uid, gid)
        status = self.exec(name, "cat /proc/1/status").stdout
        fields = {k: v.split() for k, v in (line.split(":", 1) for line in status.splitlines() if ":" in line)}
        require(fields["Uid"] == [str(uid)] * 4 and fields["Gid"] == [str(gid)] * 4,
                f"unexpected final server identity, expected {uid}:{gid}")
        self.exec(name, f"test -f {STATE}/tqueue.binlog; "
                  f"test $(stat -c %u:%g {STATE}/tqueue.binlog) = {uid}:{gid}; "
                  f"umask 0027; for dir in {STATE} {TEMP}; do "
                  'printf issue21 > "$dir/probe"; '
                  f'test $(stat -c %u:%g:%a "$dir/probe") = {uid}:{gid}:640; '
                  'mv "$dir/probe" "$dir/renamed-probe"; '
                  'test "$(cat "$dir/renamed-probe")" = issue21; rm "$dir/renamed-probe"; done',
                  user=f"{uid}:{gid}")

    def positive(self, mounts, uid, gid, user, label):
        name = self.start(mounts, user)
        self.verify_server(name, uid, gid)
        self.exec(name, f"echo restart-canary > {STATE}/restart-canary", f"{uid}:{gid}")
        self.docker("restart", "-t", "5", name)
        self.verify_server(name, uid, gid)
        self.exec(name, f'test "$(cat {STATE}/restart-canary)" = restart-canary', f"{uid}:{gid}")
        self.docker("rm", "-f", name)
        print(f"REAL_BINARY {label}, restart, effective writes: PASS", flush=True)

    def negative(self, mounts, path, environment=None):
        name = self.start(mounts, "1000:1000", environment)
        code = self.docker("wait", name, timeout=20).stdout.strip()
        output = self.docker("logs", name)
        logs = output.stdout + output.stderr
        require(code.isdigit() and int(code) != 0 and path in logs,
                f"expected failure naming {path}; server child exit={code}: {logs[-1500:]}")
        require("synthetic-secret-value" not in logs, "secret contents leaked")
        self.docker("rm", name)
        print(f"REAL_BINARY negative {path}, server child exit={code}: PASS", flush=True)

    def snapshot(self, mounts, paths, directories=()):
        # Fixed synthetic paths only; none come from an operator or bot.
        return self.run(mounts, "stat -c '%n %u:%g:%a' " + " ".join([*paths, *directories]) +
                        "; sha256sum " + " ".join(paths)).stdout

    def named_volumes(self):
        for uid, gid, user in ((101, 101, None), (101, 101, "101:101"),
                               (101, 101, "telegram-bot-api:telegram-bot-api"),
                               (1000, 1000, "1000:1000"), (1000, 2000, "1000:2000")):
            mounts = []
            for target in (STATE, TEMP):
                volume = f"{self.prefix}-volume-{len(self.volumes)}"
                self.volumes.append(volume)
                self.docker("volume", "create", volume)
                mounts += self.mount(volume, target, kind="volume")
            if user is not None:
                self.prepare(mounts, uid, gid)
            self.positive(mounts, uid, gid, user, f"named {user or 'root-bootstrap'}")
            if user is None:
                self.run(mounts, f"mkdir {STATE}/nested; echo legacy > {STATE}/nested/canary; "
                         f"chown 1234:1234 {STATE}/nested/canary; chmod 600 {STATE}/nested/canary; "
                         f"echo existing > {TEMP}/canary; chown 101:101 {TEMP}/canary")
                paths = [f"{STATE}/nested/canary", f"{TEMP}/canary"]
                before = self.snapshot(mounts, paths)
                self.positive(mounts, uid, gid, None, "existing root-bootstrap volumes")
                require(before == self.snapshot(mounts, paths), "root bootstrap modified nested canaries")

    def bind_pair(self, label):
        case = self.directory / label
        case.mkdir()
        case.chmod(0o755)  # Container helpers bind this parent; private children stay 0700.
        for name in ("data", "temp"):
            (case / name).mkdir()
        return case, self.mount(case / "data", STATE) + self.mount(case / "temp", TEMP)

    def binds_and_negatives(self):
        for gid in (1000, 2000):
            case, mounts = self.bind_pair(f"bind-{gid}")
            self.prepare(mounts, 1000, gid)
            before = self.run(mounts, f"stat -c %u:%g:%a {STATE} {TEMP}").stdout
            require(before.splitlines() == [f"1000:{gid}:700"] * 2, "bind preparation failed")
            self.run(mounts, "awk -F: '$3 == 1000 {found=1} END {exit found ? 1 : 0}' /etc/passwd")
            self.positive(mounts, 1000, gid, f"1000:{gid}", f"bind 1000:{gid} without passwd")
            require(before == self.run(mounts, f"stat -c %u:%g:%a {STATE} {TEMP}").stdout,
                    "non-root changed bind root ownership/mode")

        case, mounts = self.bind_pair("negative")
        self.prepare(mounts, 1000, 1000)
        self.run(mounts, f"mkdir {STATE}/blocked; chown 101:101 {STATE}/blocked; "
                 f"chmod 700 {STATE}/blocked; echo synthetic-secret-value > {STATE}/secret; "
                 f"chown 101:101 {STATE}/secret; chmod 600 {STATE}/secret")
        paths = [f"{STATE}/secret"]
        directories = [STATE, TEMP, f"{STATE}/blocked"]
        before = self.snapshot(mounts, paths, directories)
        for target in (STATE, TEMP):
            ro = self.mount(case / "data", STATE, target == STATE) + self.mount(case / "temp", TEMP, target == TEMP)
            self.negative(ro, target)
            for mode in ("500", "600"):
                self.run(mounts, f"chmod {mode} {target}")
                self.negative(mounts, target)
                self.run(mounts, f"chmod 700 {target}")
        self.negative(mounts, f"{STATE}/blocked/child", {"TELEGRAM_WORK_DIR": f"{STATE}/blocked/child"})
        self.negative(mounts, f"{STATE}/secret", {"TELEGRAM_API_HASH": None,
                      "TELEGRAM_API_HASH_FILE": f"{STATE}/secret"})
        self.negative(mounts, f"{STATE}/blocked/server.log", {"TELEGRAM_LOG_FILE": f"{STATE}/blocked/server.log"})
        require(before == self.snapshot(mounts, paths, directories), "negative case repaired private canary")
        self.run(mounts, f"chown 0:0 {TEMP}; chmod 700 {TEMP}")
        self.negative(mounts, TEMP)
        self.prepare(mounts, 1000, 1000)

        # Unlike the unrelated ci_safety/scenarios_entrypoint.py WIP, startup is
        # allowed with a stray nested 101:0600 file. A separate access probe fails;
        # the server need not open arbitrary files and does not audit/repair them.
        self.run(mounts, f"mkdir {STATE}/nested; echo legacy > {STATE}/nested/canary; "
                 f"chown 101:101 {STATE}/nested/canary; chmod 600 {STATE}/nested/canary")
        legacy = [f"{STATE}/nested/canary"]
        before = self.snapshot(mounts, legacy)
        require(self.run(mounts, f"cat {legacy[0]}", "1000:1000", check=False).returncode != 0,
                "private legacy canary readable")
        self.positive(mounts, 1000, 1000, "1000:1000", "legacy nested canary")
        require(before == self.snapshot(mounts, legacy), "nested canary was repaired")
        # Only this stopped, run-owned test tree is adapted offline.
        self.run(mounts, f"chown 1000:1000 {legacy[0]}")
        self.run(mounts, f'test "$(cat {legacy[0]})" = legacy', "1000:1000")
        self.positive(mounts, 1000, 1000, "1000:1000", "offline legacy adaptation")
        child = self.start(mounts, "1000:1000", {"TELEGRAM_WORK_DIR": f"{STATE}/new state",
                                                "TELEGRAM_TEMP_DIR": f"{TEMP}/new temp"})
        self.ready(child, 1000, 1000)
        result = self.exec(child, f"stat -c %u:%g:%a '{STATE}/new state' '{TEMP}/new temp'", "1000:1000")
        require(result.stdout.splitlines() == ["1000:1000:750"] * 2, "child mkdir modes/identity")
        self.docker("rm", "-f", child)
        missing = case / "missing-source"
        result = self.docker("run", "--rm", "--name", self.name(), "--network", "none",
                             *self.mount(missing, TEMP), self.image, "--version", check=False)
        require(result.returncode != 0 and str(missing) in result.stderr and not missing.exists(),
                "missing bind source did not fail at the requested path")
        for user in ("issue21-no-such-user", "-1000:2000"):
            result = self.docker("run", "--rm", "--name", self.name(), "--network", "none",
                                 f"--user={user}", self.image, "--version", check=False)
            require(result.returncode != 0, "Docker accepted an invalid identity")

    def fixture(self):
        probe = self.directory / "entrypoint-probe.sh"
        shutil.copyfile(ROOT / "tools/fixtures/issue21/entrypoint-probe.sh", probe)
        probe.chmod(0o755)
        for uid, gid in ((0, 0), (101, 101), (1000, 2000)):
            _, mounts = self.bind_pair(f"fixture-{uid}")
            self.prepare(mounts, uid, gid)
            flags = [item for k, v in ENV.items() for item in ("-e", f"{k}={v}")]
            result = self.docker("run", "--rm", "--name", self.name(), "--network", "none",
                                 "--user", f"{uid}:{gid}", *mounts,
                                 *self.mount(probe, "/usr/local/bin/telegram-bot-api", True),
                                 *flags, self.image)
            output = result.stdout
            require(f"identity={uid}:{gid}" in output and output.count(f"{uid}:{gid}:640") == 2,
                    "ENTRYPOINT_FIXTURE unexpected identity or ownership")
            require(("arg=--username=telegram-bot-api" in output) == (uid == 0) and
                    ("arg=--groupname=telegram-bot-api" in output) == (uid == 0),
                    "ENTRYPOINT_FIXTURE privilege flags mismatch")
            require(f"arg=--dir={STATE}" in output and f"arg=--temp-dir={TEMP}" in output,
                    "ENTRYPOINT_FIXTURE storage flags mismatch")
            print(f"ENTRYPOINT_FIXTURE {uid}:{gid} flags and filesystem: PASS", flush=True)

    def compose(self, directory, files, environment, *args, check=True):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("COMPOSE_", "BOTAPI_", "API_", "ISSUE21_"))}
        env.update(environment)
        flags = [item for path in files for item in ("-f", str(path))]
        return self.docker("compose", "--env-file", os.devnull, "--project-directory", directory,
                           "-p", self.prefix, *flags, *args, env=env, cwd=directory, check=check, timeout=60)

    @staticmethod
    def service_file(directory, service, model):
        # Execute exactly the validated merged service, excluding unused gateway
        # and its default network. No checkout container or network is touched.
        path = directory / f"execute-{service}.json"
        path.write_text(json.dumps({"services": {service: model}}), encoding="utf-8")
        return [path]

    def compose_matrix(self):
        case, mounts = self.bind_pair("compose")
        self.prepare(mounts, 1000, 2000)
        checkout = case / "checkout"
        checkout.mkdir()
        for filename in ("docker-compose.yml", "docker-compose.build.yml", "docker-compose.nonroot.yml"):
            shutil.copyfile(ROOT / filename, checkout / filename)
        environment = {"API_ID": "12345", "API_HASH": ENV["TELEGRAM_API_HASH"],
                       "BOTAPI_IMAGE": self.image, "BOTAPI_UID": "1000", "BOTAPI_GID": "2000",
                       "BOTAPI_TEMP_SOURCE": str(case / "temp")}
        base = [checkout / "docker-compose.yml"]
        build = checkout / "docker-compose.build.yml"
        nonroot = checkout / "docker-compose.nonroot.yml"
        for files in (base, [*base, build], [*base, nonroot], [*base, build, nonroot]):
            self.compose(checkout, files, environment, "config", "--quiet")
        for key in ("BOTAPI_UID", "BOTAPI_GID", "BOTAPI_TEMP_SOURCE"):
            for empty in (False, True):
                env = {k: v for k, v in environment.items() if k != key}
                if empty:
                    env[key] = ""
                result = self.compose(checkout, [*base, nonroot], env, "config", "--quiet", check=False)
                require(result.returncode != 0 and key in result.stderr, f"missing/empty {key} was accepted")
        for use_build in (False, True):
            name = self.name()
            override = checkout / "isolated.json"
            override.write_text(json.dumps({"services": {"botapi": {
                "image": self.image, "container_name": name, "restart": "no", "network_mode": "none",
                "volumes": [{"type": "bind", "source": str(case / "data"), "target": STATE,
                             "bind": {"create_host_path": False}}]}}}), encoding="utf-8")
            files = [*base, *([build] if use_build else []), nonroot, override]
            model = json.loads(self.compose(checkout, files, environment, "config", "--format", "json").stdout)
            validate_botapi(model["services"]["botapi"], case, name, self.image)
            execution = self.service_file(checkout, "botapi", model["services"]["botapi"])
            before = self.run(mounts, f"stat -c %u:%g:%a {TEMP}").stdout
            require(before.strip() == "1000:2000:700", "Compose disk temp not prepared")
            self.compose(checkout, execution, environment, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "botapi")
            self.verify_server(name, 1000, 2000)
            self.docker("rm", "-f", name)
            require(before == self.run(mounts, f"stat -c %u:%g:%a {TEMP}").stdout,
                    "Compose changed disk temp owner/mode")
            missing = case / "missing-compose-temp"
            env = {**environment, "BOTAPI_TEMP_SOURCE": str(missing)}
            model = json.loads(self.compose(checkout, files, env, "config", "--format", "json").stdout)
            validate_botapi(model["services"]["botapi"], case, name, self.image)
            execution = self.service_file(checkout, "botapi", model["services"]["botapi"])
            result = self.compose(checkout, execution, env, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "botapi", check=False)
            require(result.returncode != 0 and str(missing) in result.stderr and not missing.exists(),
                    "Compose missing temp source did not fail at the requested path")
            self.docker("rm", "-f", name, check=False)
            print(f"REAL_BINARY Compose build={use_build}, disk temp and missing source: PASS", flush=True)

    def reader(self):
        case, mounts = self.bind_pair("reader")
        self.prepare(mounts, 1000, 2000)
        # Synthetic stand-in for one approved media leaf in the candidate layout.
        # One /work mount lets the writer exercise a true same-filesystem rename
        # from private temp and verify inode/GID preservation at both ends.
        work = self.mount(case, "/work")
        media = case / "data/synthetic-bot/documents"
        self.run(work, "mkdir -p /work/data/synthetic-bot/documents /work/data/other-bot; "
                 "chown 1000:2000 /work/data/synthetic-bot /work/data/synthetic-bot/documents; "
                 "chmod 700 /work/data/synthetic-bot /work/data/other-bot; "
                 "chmod 750 /work/data/synthetic-bot/documents; "
                 "echo private > /work/data/private-canary; echo other > /work/data/other-bot/canary; "
                 "chmod 600 /work/data/private-canary /work/data/other-bot/canary")
        self.run(work, "umask 0027; leaf=/work/data/synthetic-bot/documents; "
                 "printf issue21-reader > /work/temp/staged; "
                 "test $(stat -c %g /work/temp/staged) = 2000; "
                 "inode=$(stat -c %i /work/temp/staged); mv /work/temp/staged \"$leaf/renamed.txt\"; "
                 "test $(stat -c %i \"$leaf/renamed.txt\") = \"$inode\"; "
                 "printf issue21-reader > \"$leaf/allowed.txt\"; "
                 "printf private > \"$leaf/private.txt\"; chmod 600 \"$leaf/private.txt\"; "
                 "test $(stat -c %u:%g:%a \"$leaf/allowed.txt\") = 1000:2000:640; "
                 "test $(stat -c %u:%g:%a \"$leaf/renamed.txt\") = 1000:2000:640; "
                 "test $(stat -c %u:%g:%a /work/data) = 1000:2000:700; "
                 "test $(stat -c %u:%g:%a /work/temp) = 1000:2000:700", "1000:2000")

        checkout = case / "checkout"
        fixtures = checkout / "tools/fixtures/issue21"
        fixtures.mkdir(parents=True)
        shutil.copyfile(ROOT / "docker-compose.yml", checkout / "docker-compose.yml")
        for filename in ("docker-compose.reader.yml", "reader-probe.sh"):
            shutil.copyfile(ROOT / "tools/fixtures/issue21" / filename, fixtures / filename)
        name = self.name()
        override = checkout / "reader-name.json"
        override.write_text(json.dumps({"services": {"reader": {"container_name": name}}}), encoding="utf-8")
        files = [checkout / "docker-compose.yml", fixtures / "docker-compose.reader.yml", override]
        environment = {"API_ID": "12345", "API_HASH": ENV["TELEGRAM_API_HASH"],
                       "BOTAPI_IMAGE": self.image, "ISSUE21_MEDIA_PATH": str(media)}
        missing = {k: v for k, v in environment.items() if k != "ISSUE21_MEDIA_PATH"}
        require(self.compose(checkout, files, missing, "config", "--quiet", check=False).returncode != 0,
                "reader accepted an unspecified media path")
        model = json.loads(self.compose(checkout, files, environment, "config", "--format", "json").stdout)
        reader = model["services"]["reader"]
        require(reader["image"] == self.image and reader["user"] == "3000:3000" and
                reader["group_add"] == ["2000"] and reader["network_mode"] == "none",
                "reader identity or isolation mismatch")
        bindings = reader["volumes"]
        require(len(bindings) == 2 and {v["target"] for v in bindings} == {str(media), "/reader-probe.sh"},
                "reader mounts private storage")
        for binding in bindings:
            require(binding["type"] == "bind" and binding.get("read_only") is True and
                    binding.get("bind", {}).get("create_host_path") is False and
                    Path(binding["source"]).resolve().is_relative_to(case), "unsafe reader bind")
        execution = self.service_file(checkout, "reader", reader)
        self.compose(checkout, execution, environment, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "reader")
        child_exit = self.docker("wait", name).stdout.strip()
        logs = self.docker("logs", name)
        require(child_exit == "0", f"reader child exit={child_exit}: {logs.stdout}{logs.stderr}")
        actual = json.loads(self.docker("inspect", name).stdout)[0]
        require(actual["HostConfig"]["GroupAdd"] == ["2000"] and
                len(actual["Mounts"]) == 2 and all(not m["RW"] for m in actual["Mounts"]),
                "actual reader mounts or groups differ from model")
        require("reader uid=3000 gid=3000" in logs.stdout, "reader did not verify final process identity")
        self.docker("rm", name)

        leaf = self.mount(media, "/media", True)
        denied = self.run(leaf, "cat /media/allowed.txt", "3000:3000", check=False)
        require(denied.returncode != 0 and "Permission denied" in denied.stderr,
                "read-only mount without shared group unexpectedly readable")
        # Independently test POSIX modes with a writable mount and shared group.
        before = self.snapshot(self.mount(media, "/media"), ["/media/allowed.txt", "/media/renamed.txt", "/media/private.txt"])
        self.run(self.mount(media, "/media"),
                 'test "$(cat /media/allowed.txt)" = issue21-reader; '
                 'if cat /media/private.txt >/dev/null 2>&1; then exit 1; fi; '
                 'if sh -c "printf altered >> /media/allowed.txt" 2>/dev/null; then exit 1; fi; '
                 'if touch /media/forbidden 2>/dev/null; then exit 1; fi; '
                 'if rm /media/allowed.txt 2>/dev/null; then exit 1; fi',
                 "3000:3000", groups=("2000",))
        require(before == self.snapshot(self.mount(media, "/media"),
                                       ["/media/allowed.txt", "/media/renamed.txt", "/media/private.txt"]),
                "reader changed media contents or modes")
        print("GROUP_FILESYSTEM create/rename, reader 3000+2000, ro and POSIX, stranger, private 0600: PASS", flush=True)

    def close(self):
        errors = []
        for name in self.containers:
            try:
                result = self.docker("rm", "-f", name, check=False)
                if result.returncode and "No such container" not in result.stderr:
                    errors.append(result.stderr)
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append(str(error))
        for volume in self.volumes:
            try:
                result = self.docker("volume", "rm", volume, check=False)
                if result.returncode:
                    errors.append(result.stderr)
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append(str(error))
        if self.directory is not None:
            # Only a canonical generated /tmp root, after removing all containers.
            path = self.directory.resolve()
            require(path.parent == Path("/tmp") and path.name.startswith(self.prefix), "unsafe cleanup root")
            try:
                result = self.docker("run", "--rm", "--name", f"{self.prefix}-cleanup", "--network", "none",
                                     "--entrypoint", "sh", *self.mount(path, "/case"), self.image, "-ec",
                                     "rm -rf /case/* /case/.[!.]* /case/..?*", check=False)
                if result.returncode:
                    errors.append(result.stderr)
                else:
                    path.rmdir()
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append(str(error))
            finally:
                self.docker("rm", "-f", f"{self.prefix}-cleanup", check=False)
        if errors:
            raise RuntimeError("run-owned cleanup failed: " + "; ".join(errors))

    def check_platform(self):
        require(platform.system() == "Linux", "mandatory qualification needs Linux with POSIX bind mounts")
        info = json.loads(self.docker("info", "--format", "{{json .}}").stdout)
        require(info["OSType"] == "linux" and info["Architecture"] in ("x86_64", "amd64"),
                "mandatory qualification platform is linux/amd64")
        require(not any("rootless" in x or "userns" in x for x in info.get("SecurityOptions", [])),
                "rootless/userns-remap are not qualified by this matrix")
        details = json.loads(self.docker("image", "inspect", self.image).stdout)[0]
        print("CANDIDATE " + json.dumps({"id": details["Id"], "digests": details.get("RepoDigests", []),
                                         "labels": details["Config"].get("Labels", {})}, sort_keys=True), flush=True)
        require(details["Architecture"] == "amd64", "candidate must be amd64")
        self.image_id = details["Id"]
        self.directory = Path(tempfile.mkdtemp(prefix=self.prefix + "-", dir="/tmp")).resolve()
        require(not self.directory.is_relative_to(ROOT), "test storage must be outside checkout")

    def verify_image(self):
        require(json.loads(self.docker("image", "inspect", self.image).stdout)[0]["Id"] == self.image_id,
                "candidate tag changed during qualification")

    def execute(self):
        try:
            self.check_platform()
            self.named_volumes()
            self.binds_and_negatives()
            self.fixture()
            self.compose_matrix()
            self.reader()
            self.verify_image()
        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="loaded production candidate, not a diagnostic image")
    args = parser.parse_args()
    Matrix(args.image).execute()
    print("RUNTIME_PERMISSIONS runner exit=0: PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        print(f"RUNTIME_PERMISSIONS runner exit=1: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
