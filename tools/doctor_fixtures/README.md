# Doctor synthetic integration

Run explicitly with `python3 tools/check_doctor.py`. Discover never starts Docker.
The harness owns a unique Compose project, temporary input and volumes. It pulls
versioned Python/Alpine and nginx/Alpine bases, resolves and records their actual
registry digests before building, and passes those immutable identities to Compose.
Set `DOCTOR_PYTHON_IMAGE` and `DOCTOR_NGINX_IMAGE` to approved `name@sha256:...`
identities to reproduce a run. No registry login or publication is needed.

This fixture uses Python stdlib as a synthetic Bot API, with explicit image label
`io.tg-selfhost.doctor-fixture=synthetic`, UID/GID 101:101, and real nginx. Doctor
recognizes its interpreter process only for this labeled fixture and records the
synthetic limitation. A fixture success never certifies the real Telegram binary.
The healthy gateway mounts the repository's actual `nginx.conf`, including its
redaction map. The safe fixture is illustrative; it does not replace shipped config.

Linux local Engine and bridge access are required for READY. Desktop/Windows can
exercise mandatory failures but its direct bridge evidence stays UNKNOWN. The
harness changes only its synthetic containers/volumes, checks sentinels, captures
doctor commands and HTTP requests, and removes its project on errors/signals.
It does not access real bots, production paths or other migration tools.

The CLI-log matrix passes explicit `--dir`, `--temp-dir`, `--http-port`, `--local`
and `--log` arguments through the existing entrypoint. The stub stays argv-agnostic:
doctor observes the real `/proc/1/cmdline` of this labeled synthetic process.
The harness prepares a log sentinel in its separate `logs` volume, outside state.
`cli-log-unsafe` mounts it read-only into nginx with a temporary alias under a
different URI and requires BLOCKED/1 with both `state_mount_accessible` and
`state_root_exposed`. `cli-log-safe` uses the same argv without that gateway mount
and requires READY/0 on a supported Linux Engine (UNKNOWN/3 on Desktop/Windows).
`cli-log-divergence` adds a different, relative `TELEGRAM_LOG_FILE` alongside the
absolute argv log, so the additional protected env path requires UNKNOWN/3.
`cli-log-relative` uses relative argv `--log` and also requires UNKNOWN/3. Different
absolute env/argv paths are not inherently failures: both must be checked.

Each case compares state/log sentinel hashes and private input/config files before
and after doctor, checks probe cleanup, and audits root-only local HTTP and the exec
allowlist. Doctor never reads the synthetic log contents or requests its URL.
The base model declares the log volume so cleanup removes it with the random project
on success, failure or interruption. Unit tests verify these case definitions without
Docker; only the explicit integration command starts containers.
