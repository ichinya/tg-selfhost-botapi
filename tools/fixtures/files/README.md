# Synthetic state isolation fixture

Run `python tools/check_file_contract.py --state-isolation-only`. The checker builds
the mock and creates unique Compose volumes and network, then removes only that
project. It uses the repository nginx configuration and synthetic markers only.
Docker and Compose are required; unavailable Docker is reported as NOTRUN.

Full mode: `python tools/check_file_contract.py --botapi-image <exact-candidate>
--downloads-image <exact-candidate> --report file-report.json`. Both images must
already exist locally. No registry latest lookup or production storage is used.
It stages an allowlist of source bytes into a private build context, records their
hashes and the exact image IDs, then uses only disposable named volumes/networks.
The extra Dockerfile.full image supplies openssl for a one-day fixture certificate.
Linux/amd64, openat2 and Docker volume subpaths are mandatory. The sole privileged
helper tests a same-device nested bind in its own namespace and unmounts it.
Full mode verifies local bytes/permissions/RO, TLS downloads including a sparse
16 MiB file, foreign/unsafe paths, no-store/error/auth counters and log privacy,
plus actual Bot API startup under 101:101 with network none. Startup is not a
successful Telegram authorization or real getFile. Missing runtime evidence is
NOTRUN/failure, never PASS. Source/unit results and production remain separate.

nginx is resolved to an immutable digest before fixture creation (optional
`FILE_NGINX_IMAGE=nginx@sha256:<approved-digest>`). The report records that digest.
State mode also inspects runtime gateway mounts and audits that no legacy file
request reached upstream. Full mode compares packaged sources against the
candidate, executes the Linux opener/protocol suites without skips and tests the
shipped client over verified TLS, including a truncated-response peer.
