"""Explicit Linux image acceptance. Never imported as a daemon-running unit test.

All resources are temporary, named and labelled with a per-run UUID. No token,
Telegram request, production Compose up/down, or global resource prune is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid


from check_nonroot_compose import (
    CheckError, Commands, LABEL, MEDIA, ROOT, TEMP, WORK, compose_matrix, identity,
    overlaps, require, validate_download_layout, validate_effective_mounts, validate_model, validate_reader_model,
)


class Acceptance:
    def __init__(self, image, commands=None):
        self.commands = commands or Commands()
        self.owner = uuid.uuid4().hex
        self.prefix = "botapi-nonroot-" + self.owner
        self.resources = []
        self.image = image
        self.counter = 0

    def name(self):
        self.counter += 1
        return f"{self.prefix}-{self.counter}"

    def inspect(self, kind, name, absent_ok=False):
        result = self.commands.run([kind, "inspect", name], check=False)
        if absent_ok and result.returncode != 0 and result.stdout.strip() == '[]':
            return None
        require(result.returncode == 0, 'resource_inspection_failed')
        return json.loads(result.stdout)[0]

    def cleanup(self):
        # A separate bounded cleanup budget is available after the test deadline.
        self.commands.until = time.monotonic() + 90
        failures = []
        for kind, name in reversed(self.resources):
            try:
                info = self.inspect(kind, name, absent_ok=True)
                if info is None:
                    continue
                labels = info.get("Labels", {}) if kind == "volume" else info["Config"].get("Labels", {})
                require(labels.get(LABEL) == self.owner, "cleanup_ownership_mismatch")
                args = [kind, "rm"] + (["-f"] if kind == "container" else []) + [name]
                self.commands.run(args, timeout=10)
            except (CheckError, KeyError, ValueError):
                failures.append(kind)
        require(not failures, "cleanup_failed")

    def volume(self):
        name = self.name()
        self.resources.append(("volume", name))
        self.commands.run(["volume", "create", "--label", f"{LABEL}={self.owner}", name])
        return ("volume", name)

    @staticmethod
    def mount(backing, target, readonly=False):
        kind, source = backing
        require("," not in str(source), "unsupported_mount_path")
        return ["--mount", f"type={kind},source={source},target={target}" + (",readonly" if readonly else "")]

    def container(self, mounts, user=None, script=None, environment=None, groups=()):
        name = self.name()
        args = ["container", "create", "--name", name, "--label", f"{LABEL}={self.owner}",
                "--network", "none", "--restart", "no"]
        if user:
            args += ["--user", user]
        for group in groups:
            args += ["--group-add", str(group)]
        for backing, target, readonly in mounts:
            args += self.mount(backing, target, readonly)
        for key, value in (environment or {}).items():
            args += ["--env", f"{key}={value}"]
        if script is not None:
            args += ["--entrypoint", "/bin/sh"]
        args += [self.image]
        if script is not None:
            args += ["-ec", script]
        self.resources.append(("container", name))
        self.commands.run(args)
        return name

    def helper(self, mounts, script, user="0:0", groups=(), success=True):
        name = self.container(mounts, user, script=script, groups=groups)
        result = self.commands.run(["container", "start", "-a", name], check=False)
        require((result.returncode == 0) == success, "filesystem_probe_unexpected_result")
        return result.stdout.strip()

    def prepare(self, state, temp, uid, gid):
        self.helper([(state, "/state", False), (temp, "/scratch", False)],
                    f"chown {uid}:{gid} /state /scratch; chmod 700 /state /scratch; "
                    "mkdir /state/nested; printf synthetic-canary > /state/nested/canary; "
                    f"chown {uid}:{gid} /state/nested /state/nested/canary; "
                    "chmod 700 /state/nested; chmod 600 /state/nested/canary; "
                    "printf synthetic-temp > /scratch/private-canary; "
                    f"chown {uid}:{gid} /scratch/private-canary; chmod 600 /scratch/private-canary")

    def snapshot(self, state):
        # Only known synthetic canaries; never enumerate production state.
        return self.helper([(state, "/state", True)],
                           "stat -c '%u:%g:%a' /state /state/nested /state/nested/canary; "
                           "sha256sum /state/nested/canary")

    def storage_snapshot(self, state, temp):
        return self.snapshot(state) + self.helper([(temp, "/scratch", True)],
            "stat -c '%u:%g:%a' /scratch /scratch/private-canary; sha256sum /scratch/private-canary")

    def server(self, state, temp, user=None, readonly=None, extra=None, groups=()):
        env = dict(TELEGRAM_API_ID="12345", TELEGRAM_API_HASH="0" * 32,
                   TELEGRAM_LOCAL="true", TELEGRAM_VERBOSITY="0")
        mounts = [(state, WORK, readonly == "state"), (temp, TEMP, readonly == "temp")]
        if extra:
            mounts.extend(extra)
            env["TELEGRAM_FILES_DIR"] = MEDIA
            uid, gid = identity(user)
            env.update(BOTAPI_MEDIA_REQUIRE_NONROOT="1", BOTAPI_MEDIA_EXPECTED_UID=str(uid), BOTAPI_MEDIA_EXPECTED_GID=str(gid))
        name = self.container(mounts, user, environment=env, groups=groups)
        validate_effective_mounts(self.inspect("container", name)["Mounts"])
        inodes = self.helper(mounts, "stat -c '%d:%i' " + " ".join(target for _, target, _ in mounts)).splitlines()
        require(len(inodes) == len(mounts) and len(inodes) == len(set(inodes)), "effective_backing_inode_alias")
        self.commands.run(["container", "start", name])
        return name

    def wait_ready(self, name, uid, gid, supplementary=()):
        until = time.monotonic() + 35
        while time.monotonic() < until:
            require(self.inspect("container", name)["State"]["Running"], "server_exited_before_ready")
            response = self.commands.run(["exec", name, "sh", "-c",
                "printf 'GET / HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n' | nc -w 2 127.0.0.1 8081"],
                timeout=5, check=False)
            parts = response.stdout.replace("\r\n", "\n").split("\n\n", 1)
            if len(parts) == 2 and re.match(r"HTTP/1\.[01] 404\b", parts[0]):
                require("content-type: application/json" in parts[0].lower(), "http_response_type")
                body = json.loads(parts[1])
                require(body.get("ok") is False and type(body.get("error_code")) is int
                        and body["error_code"] == 404, "http_response_contract")
                break
            time.sleep(0.2)
        else:
            raise CheckError("http_readiness_deadline")
        status = self.commands.run(["exec", name, "cat", "/proc/1/status"]).stdout
        for field, expected in (("Uid", uid), ("Gid", gid)):
            match = re.search(rf"^{field}:[\t ]+([0-9\t ]+)$", status, re.M)
            require(match is not None and set(map(int, match[1].split())) == {expected}, "server_identity_mismatch")
        groups = re.search(r"^Groups:[\t ]*(.*?)$", status, re.M)
        require(groups is not None, "server_groups_unobserved")
        require(set(map(int, groups[1].split())) | {gid} == set(supplementary) | {gid}, "unexpected_server_groups")
        comm = self.commands.run(["exec", name, "cat", "/proc/1/comm"]).stdout.strip()
        require(comm == "telegram-bot-ap", "server_is_not_pid_one")
        return status

    def evidence(self, name, uid, gid, mismatch=False):
        from migration_probe import DockerEvidence
        adapter = DockerEvidence(name, "http://127.0.0.1:8081", self.image, b"synthetic-nonroot-key" * 2)
        def run(*args):
            # Deliberately drop supplementary groups only in the negative probe.
            # PID 1 remains unchanged. The real adapter must reject before writes.
            if mismatch and args[0] == "exec" and args[-1] == 'id -u; id -g; id -G':
                args = ('exec', '--user', '0:0', name, 'su-exec', f'{uid}:{gid}', 'sh', '-c', args[-1])
            try:
                return self.commands.run(list(args), timeout=20).stdout
            except CheckError:
                raise ValueError('managed deployment inspection failed') from None
        adapter.run = run
        if mismatch:
            try:
                adapter()
            except ValueError as exc:
                require(str(exc) == 'supplementary_groups_mismatch', 'mismatch_probe_wrong_failure')
            else:
                raise CheckError('mismatched_probe_accepted')
        else:
            record = adapter()
            require(record['runtime_uid'] == uid and record['runtime_gid'] == gid
                    and record['write_verified'] is True and record['image_id'] == self.image,
                    'runtime_evidence_mismatch')

    def storage_probe(self, name, uid, gid):
        # Run with the observed primary identity; no supplementary groups are
        # added to these matrix cases. The sharing case checks groups separately.
        self.commands.run(["exec", "--user", f"{uid}:{gid}", name, "sh", "-ec",
            f"test \"$(id -u):$(id -g)\" = {uid}:{gid}; "
            f"for p in {WORK} {TEMP}; do "
            "probe=$p/.acceptance-probe; (set -C; printf check > \"$probe\"); "
            "test \"$(cat \"$probe\")\" = check; rm \"$probe\"; done"])
        self.commands.run(["exec", name, "sh", "-ec",
            f"test -s {WORK}/tqueue.binlog; test -s {WORK}/webhooks_db.binlog; "
            f"test \"$(stat -c %u:%g {WORK}/tqueue.binlog)\" = {uid}:{gid}; "
            f"test \"$(stat -c %u:%g {WORK}/webhooks_db.binlog)\" = {uid}:{gid}"])
        self.evidence(name, uid, gid)

    def stop(self, name):
        self.commands.run(["container", "stop", "--time", "10", name], timeout=20)
        state = self.inspect("container", name)["State"]
        require(not state["Running"] and state["ExitCode"] != 137, "sigterm_not_graceful")

    def quiesce(self, backings):
        sources = {str(source) for _, source in backings}
        for kind, name in self.resources:
            if kind != "container":
                continue
            info = self.inspect(kind, name)
            if info["State"]["Running"] and any(m["Source"] in sources for m in info.get("Mounts", [])):
                require(info["Config"].get("Labels", {}).get(LABEL) == self.owner, "quiesce_ownership_mismatch")
                self.stop(name)

    def expect_failure(self, name):
        until = time.monotonic() + 15
        while time.monotonic() < until:
            state = self.inspect("container", name)["State"]
            if not state["Running"]:
                require(state["ExitCode"] != 0, "failure_exited_zero")
                result = self.commands.run(["logs", name])
                logs = result.stdout + result.stderr
                require("0" * 32 not in logs, "credential_in_logs")
                return
            time.sleep(0.2)
        raise CheckError("expected_storage_failure_not_seen")

    def positive(self, state, temp, user, uid, gid, prepared=True):
        if prepared:
            self.prepare(state, temp, uid, gid)
            before = self.storage_snapshot(state, temp)
        name = self.server(state, temp, user)
        try:
            self.wait_ready(name, uid, gid)
            self.storage_probe(name, uid, gid)
        finally:
            self.stop(name)
        if prepared:
            require(self.storage_snapshot(state, temp) == before, "existing_canary_changed")
        # Restart the same container against its existing backing.
        self.commands.run(["container", "start", name])
        try:
            self.wait_ready(name, uid, gid)
            self.storage_probe(name, uid, gid)
        finally:
            self.stop(name)
        # Recreate, not a second simultaneous writer.
        name = self.server(state, temp, user)
        try:
            self.wait_ready(name, uid, gid)
            self.storage_probe(name, uid, gid)
        finally:
            self.stop(name)

    def matrix(self):
        for user, uid, gid in ((None, 101, 101), ("101:101", 101, 101),
                               ("1000:1000", 1000, 1000), ("1000:2000", 1000, 2000)):
            self.positive(self.volume(), self.volume(), user, uid, gid, prepared=user is not None)
            with tempfile.TemporaryDirectory(prefix="botapi-bind-") as directory:
                state, temp = Path(directory) / "state", Path(directory) / "temp"
                state.mkdir(); temp.mkdir()
                backings = (("bind", str(state)), ("bind", str(temp)))
                try:
                    self.positive(*backings, user, uid, gid, prepared=user is not None)
                finally:
                    self.quiesce(backings)
                    # Only our freshly allocated bind roots; restore host ownership
                    # so the unprivileged CI account can remove its temporary tree.
                    self.helper([(backings[0], "/state", False), (backings[1], "/scratch", False)],
                        "find /state /scratch -mindepth 1 -delete; "
                        f"chown {os.getuid()}:{os.getgid()} /state /scratch; chmod 700 /state /scratch")
        for role in ("state", "temp"):
            for mode, readonly in ((500, False), (400, False), (300, False), (700, True)):
                state, temp = self.volume(), self.volume()
                self.prepare(state, temp, 1000, 2000)
                before = self.storage_snapshot(state, temp)
                if not readonly:
                    backing = state if role == "state" else temp
                    self.helper([(backing, "/denied", False)], f"chmod {mode} /denied")
                    before = self.storage_snapshot(state, temp)
                name = self.server(state, temp, "1000:2000", role if readonly else None)
                self.expect_failure(name)
                require(self.storage_snapshot(state, temp) == before, "failure_changed_canary")
        # A nonempty foreign root is never silently repaired, including root bootstrap.
        for user in (None, "1000:2000"):
            state, temp = self.volume(), self.volume()
            self.prepare(state, temp, 2002 if user is None else 101, 3002 if user is None else 101)
            before = self.storage_snapshot(state, temp)
            self.expect_failure(self.server(state, temp, user))
            require(self.storage_snapshot(state, temp) == before, "foreign_root_repaired")
        # A different owner with sufficient group access is allowed.
        for user, uid, gid in ((None, 101, 101), ("1000:2000", 1000, 2000)):
            state, temp = self.volume(), self.volume()
            self.prepare(state, temp, 2002, gid)
            self.helper([(state, "/state", False), (temp, "/scratch", False)],
                        "chmod 770 /state /scratch")
            before = self.storage_snapshot(state, temp)
            name = self.server(state, temp, user)
            self.wait_ready(name, uid, gid)
            self.stop(name)
            require(self.storage_snapshot(state, temp) == before, "group_access_root_changed")
        # Corrupt permissions on a binlog the real server actually opens.
        state, temp = self.volume(), self.volume()
        self.prepare(state, temp, 1000, 2000)
        name = self.server(state, temp, "1000:2000")
        self.wait_ready(name, 1000, 2000); self.stop(name)
        self.helper([(state, "/state", False)], "chown 0:0 /state/tqueue.binlog; chmod 600 /state/tqueue.binlog")
        before = self.helper([(state, "/state", True)], "stat -c '%u:%g:%a' /state/tqueue.binlog; sha256sum /state/tqueue.binlog")
        self.expect_failure(self.server(state, temp, "1000:2000"))
        after = self.helper([(state, "/state", True)], "stat -c '%u:%g:%a' /state/tqueue.binlog; sha256sum /state/tqueue.binlog")
        require(before == after, "denied_binlog_changed")
        # A media alias would mix private state with download-temp. Reject it
        # before starting the server, even though mount destinations differ.
        state, temp = self.volume(), self.volume()
        try:
            self.server(state, temp, "1000:2000", extra=[(state, MEDIA, False)])
        except CheckError as exc:
            require(str(exc) == "effective_backing_alias", "alias_negative_wrong_failure")
        else:
            raise CheckError("media_backing_alias_accepted")
        with tempfile.TemporaryDirectory(prefix='botapi-missing-') as directory:
            missing = Path(directory) / 'absent'
            scratch = Path(directory) / 'temp'
            scratch.mkdir()
            try:
                self.container([(('bind', str(missing)), WORK, False), (('bind', str(scratch)), TEMP, False)], '1000:2000')
            except CheckError as exc:
                require(str(exc) == 'docker_operation_failed', 'missing_bind_wrong_failure')
            else:
                raise CheckError('missing_bind_created_container')
            require(not missing.exists(), 'missing_bind_was_created')
        print("PASS real-image identity, bind/volume, recreate, denied/RO and binlog matrix")

    def sharing(self):
        state, temp, media = self.volume(), self.volume(), self.volume()
        self.prepare(state, temp, 1000, 2000)
        self.helper([(media, "/media", False)], "chown 1000:2000 /media; chmod 700 /media")
        name = self.server(state, temp, "1000:2000", extra=[(media, MEDIA, False)])
        self.wait_ready(name, 1000, 2000)
        mounts = self.inspect('container', name)['Mounts']
        validate_download_layout(MEDIA + '/synthetic-bot/temp/sample', MEDIA + '/synthetic-bot/documents/sample', mounts)
        try:
            validate_download_layout(TEMP + '/sample', MEDIA + '/synthetic-bot/documents/sample', mounts)
        except CheckError as exc:
            require(str(exc) == 'download_cross_mount_layout', 'cross_mount_wrong_failure')
        else:
            raise CheckError('cross_mount_layout_accepted')
        probe = (ROOT / "tools/fixtures/nonroot/media-probe.sh").read_text(encoding="utf-8")
        # Candidate tools execute the synthetic write/rename with server identity.
        result = self.commands.run(["exec", "--user", "1000:2000", name, "sh", "-ec", probe])
        require(result.stdout.strip() == hashlib.sha256(b"synthetic-media\n").hexdigest(), "writer_hash_mismatch")
        self.stop(name)
        # A scoped subpath mount is provided by Compose (volume.subpath requires
        # a pre-existing directory). Never mount the whole bot root to a reader.
        compose = ROOT / "tools/fixtures/nonroot/compose.yml"
        env = {**os.environ, "NONROOT_IMAGE": self.image, "NONROOT_MEDIA_VOLUME": media[1],
               "NONROOT_OWNER": self.owner}
        project = self.name()
        base = ["compose", "--project-name", project, "-f", str(compose)]
        model = json.loads(self.commands.run([*base, "config", "--format", "json"], env=env).stdout)
        validate_reader_model(model, self.image, media[1])
        for role in ('reader', 'posix', 'stranger'):
            reader_name = self.name()
            self.resources.append(('container', reader_name))
            result = self.commands.run([*base, 'run', '--no-deps', '--name', reader_name, role], env=env, check=False)
            state = self.inspect('container', reader_name)['State']
            require(not state['Running'], 'reader_still_running')
            require((result.returncode == 0 and state['ExitCode'] == 0) if role != 'stranger'
                    else (result.returncode != 0 and state['ExitCode'] != 0), 'reader_access_contract')
        print("PASS synthetic media rename, scoped RO reader, supplementary group and stranger denial")

    def supplementary(self):
        state, temp = self.volume(), self.volume()
        self.prepare(state, temp, 1000, 2000)
        name = self.server(state, temp, '1000:2000', groups=(3000,))
        try:
            self.wait_ready(name, 1000, 2000, supplementary=(3000,))
            self.evidence(name, 1000, 2000)
            self.evidence(name, 1000, 2000, mismatch=True)
        finally:
            self.stop(name)
        print('PASS supplementary groups and controlled mismatched probe refusal')

    def run(self):
        try:
            info = self.inspect("image", self.image)
            self.image = info["Id"]  # Every subsequent action uses this immutable ID.
            revision = info.get("Config", {}).get("Labels", {}).get("io.tg-selfhost.bot-api-revision", "")
            require(bool(re.fullmatch(r"[0-9a-f]{40}", revision)), "source_revision_unqualified")
            print(f"candidate={self.image} source={revision}")
            self.matrix()
            self.supplementary()
            self.sharing()
        finally:
            self.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--deadline", type=int, default=1200)
    args = parser.parse_args()
    require(60 <= args.deadline <= 1800, "invalid_deadline")
    require(args.compose_only or args.image, "candidate_image_required")
    commands = Commands(args.deadline)
    compose_matrix(commands)
    if not args.compose_only:
        require(sys.platform == "linux", "linux_local_docker_required")
        info = json.loads(commands.run(["info", "--format", "{{json .}}"]).stdout)
        require(info.get("OSType") == "linux", "linux_engine_required")
        require('docker desktop' not in info.get('OperatingSystem', '').lower(), 'local_linux_engine_required')
        require(not any("rootless" in option or "userns" in option
                        for option in info.get("SecurityOptions", [])), "rootful_without_userns_required")
        Acceptance(args.image, commands).run()


if __name__ == "__main__":
    try:
        main()
    except (CheckError, KeyError, ValueError, OSError) as exc:
        # Codes only; never dump env, full model, inspect or process arguments.
        print(f"FAIL nonroot acceptance: {exc if isinstance(exc, CheckError) else type(exc).__name__}")
        raise SystemExit(1)
