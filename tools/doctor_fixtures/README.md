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
Monitoring fixture includes an observer in the Bot API netns and separate loopback management binding. It is synthetic and does not verify a Telegram binary or delivery.
