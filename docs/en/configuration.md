---
title: Configuration
translation: /docs/ru/configuration.html
---

# Configuration

## Docker Compose file secrets

Compose 2.24.4 or newer supports the optional secrets overlay. Store API ID and
hash in separate host files outside the checkout, readable by the container
entrypoint and restricted to their owner (0400 or 0600). Local Compose file
secrets are bind mounts and retain host filesystem permissions; they are not an
encrypted secret store. Set `TELEGRAM_API_ID_SECRET_PATH` and
`TELEGRAM_API_HASH_SECRET_PATH` to those paths, then run:

```sh
docker compose -f docker-compose.yml -f docker-compose.secrets.yml up -d
```

For a local build insert `-f docker-compose.build.yml` before the secrets file.
The overlay removes inline credentials from the effective container environment.
Credential files must be nonempty regular files readable by the server user;
directories and FIFOs are rejected without reading them. `docker compose config`
checks the merged structure; the entrypoint checks credentials at startup.

The gateway and optional downloads service wait for Bot API HTTP readiness.
This does not test bot authorization or guarantee recovery after an unhealthy status.
Bot API has a 120-second stop grace period; measure shutdown with your own data
and override it if needed before taking a stopped backup.
The existing environment-only configuration remains available.

## Doctor configuration checks

Doctor delegates interpolation and merging to `docker compose config --format json`.
Repeat `-f`, `--env-file` and `--profile` in the intended order; `-p` and
`--project-directory` select the project. Environment, implicit `.env` and Docker
context retain Docker's semantics. Containers are selected by Compose labels.
Missing/stopped services and proven drift block readiness; ambiguous replicas,
custom entrypoints and unavailable evidence remain UNKNOWN. Credentials are
checked for presence, conflicts and readable mounted files, without printing them.

Doctor checks work/temp filesystems inside the server namespace under its observed
UID/GID and supplementary groups. Work requires persistence; temp may use the
container layer. It creates and removes one exclusive small probe per existing
directory, with a container-side timeout. `--no-write-probe` suppresses all doctor
writes and leaves write readiness UNKNOWN. Cleanup failure blocks readiness.
The default reserve is 1 GiB and 1024 inodes per filesystem, configurable with
`--min-free-bytes` and `--min-free-inodes`. Shared work/temp filesystems are counted
once. This policy does not guarantee capacity for future Telegram traffic.
Thresholds must be positive integers. Mount metadata is checked for enabled
quotas; without per-identity quota accounting that evidence remains UNKNOWN.
The exclusive write uses an open descriptor in the verified directory, and
cleanup removes only that probe after checking its identity.
Probe UID, GID and supplementary groups must match the observed server identity;
a successful root write cannot satisfy this check. Existing canonical directories
are required; doctor does not create roots, change ownership or change modes.

Doctor blocks any override which aliases the private state root or mounts its
backing into an HTTP component, including read-only mounts. The shipped nginx
configuration proxies requests and its fixed logging maps are supported.
Doctor does not repair nginx or Compose.
Isolation checks parse supported nginx blocks/includes and compare mount backings.
Dynamic handlers, unresolved includes and unverified media symlinks remain UNKNOWN.
No binlog, real bot directory, statistics endpoint or state file is fetched.
Read-only mounts, disabled directory listings and loopback publication do not
prevent known-file HTTP reads. Unsupported remote file workflows use the boundary
in issue #5; doctor does not certify or execute neighboring migration helpers.
## Helper access

The operator startup file allowlists full API endpoints. The loopback helper
serves fixed routes/assets and accepts no arbitrary Docker command/container.
One-time bootstrap creates an HttpOnly SameSite=Strict cookie and CSRF token.
Exact Host/Origin checks reject external/null/file origins. Limits: 256 KiB body,
ten-second HTTP lifetime, sixteen connections and one background migration.
Access/body logs are disabled. The helper is never exposed through nginx.

## Private migration authority

Use one `MIGRATION_STATE_DIR` per operator/host on a private Linux filesystem
outside the checkout, Bot API mounts and webroots (directory 0700, files 0600).
All interfaces share its per-bot lock and unfinished-operation reservation.
Windows and Windows-mounted WSL state are unsupported. Nested private artifacts
are rejected by the documentation checker.

Readiness is a fresh token-free protocol probe plus private deployment evidence
with a five-minute TTL. Bind the image ID, runtime UID/GID, credentials readiness,
persistent work mount and writable separate temp path. A local-build image need
not have a RepoDigest; temp storage need not be persistent. `_FILE` credentials
are supported. Managed Docker diagnostics perform explicit tiny write probes as
the runtime user; they are not read-only. The HTTP helper cannot select containers.
Managed readiness observes the server at PID 1 and verifies the probe's UID,
GID and normalized supplementary groups before reading secret files or writing.
Identity mismatch or process drift blocks evidence. The external v1 evidence
retains UID/GID and does not separately attest the group set.
Local webhook mode must match deployment evidence: HTTP/private IP/any port is
allowed in local mode; cloud requires HTTPS, a supported port and public IPv4.
Unsupported profiles fail before source mutations. Transport has bounded DNS,
connect/read/total time and body size, no redirects, inherited proxy or retries.

## Addresses and storage

| Setting | Value |
| --- | --- |
| Gateway port on the host | `18080` |
| Internal Bot API endpoint | `http://botapi:8081` |
| Persistent state on the host | `./data` |
| Gateway upload spool | Project-scoped `gateway_client_temp` volume at `/var/cache/nginx/client_temp` |
| State directory inside the container | `/var/lib/telegram-bot-api` |
| Default server user/group IDs | `101:101` |
| Local mode | Enabled by Compose |

By default the container starts as root only to initialize new or empty state and
temp roots, then runs the server as `101:101`. Non-empty roots and their contents
are not re-owned or recursively repaired. Alternatively, Docker `--user UID:GID`
or Compose `user: "UID:GID"` runs directly as that identity; prepare both roots
for it in advance. Paths must be dedicated absolute paths without symlink
components. Startup checks access as the server user. New private roots are
`0700` and the server uses umask `0027`; existing modes are unchanged. Secret
files supplied with `_FILE` must be readable by the final server identity. Log
file access is checked by the server. Explicit entrypoint arguments such as
`--version` bypass normal startup and run as the container user.

The Bot API endpoint receives method calls. The webhook URL belongs to your
application and receives updates sent by the server. They are different addresses.

## Compose environment

The optional `docker-compose.nonroot.yml` requires `BOTAPI_UID`, `BOTAPI_GID`,
`BOTAPI_STATE_SOURCE` and `BOTAPI_TEMP_SOURCE`; these select Compose identity
and prepared bind sources, not runtime remapping. See [Getting started](getting-started.md).

`TELEGRAM_FILES_DIR` optionally selects a separate upstream `--files-dir`; when
empty, the upstream working-directory default is retained. The work, HTTP temp
and media roots must be separate absolute paths without symlink components.
Changing this setting does not move existing files or cached paths. The media
override requires the non-root overlay and a prepared `BOTAPI_MEDIA_SOURCE`.

| Variable in `.env` | Purpose |
| --- | --- |
| `API_ID` | Required application API ID |
| `API_HASH` | Required application API hash |
| `GATEWAY_BIND` | Gateway host address; defaults to `127.0.0.1` |
| `BOTAPI_IMAGE` | Local tag fallback for config; use a qualified immutable ref for deployment |
| `OBSERVER_IMAGE` | Local tag fallback for config; use a qualified immutable ref for deployment |
| `GATEWAY_IMAGE` | Local tag fallback for config; use a qualified immutable ref for deployment |

Use refs from a qualified release receipt for deployment. Generated `.env.build`
supplies local build inputs. Without refs, base `up` fails pulling the gateway
fallback when that local image is absent.

For a tested build, set:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi@sha256:<qualified-botapi-digest>
OBSERVER_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi-observer@sha256:<qualified-observer-digest>
GATEWAY_IMAGE=nginx@sha256:<qualified-gateway-digest>
```

The local build override uses
`tg-selfhost-botapi:local`, independently of `BOTAPI_IMAGE`.

## Migration helper environment

The host helper imports the documented migration settings from trusted `.env`/`ENV_FILE`, including `OFFICIAL_BOT_URL`. See complete-profile inputs below; these are separate from container settings.

## Container environment

These variables configure the image's entrypoint. Compose currently maps
`API_ID/API_HASH` into `TELEGRAM_API_ID/TELEGRAM_API_HASH`.

| Variable | Purpose / default |
| --- | --- |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Required credentials |
| `TELEGRAM_API_ID_FILE`, `TELEGRAM_API_HASH_FILE` | Read the corresponding credential from a mounted file |
| `TELEGRAM_WORK_DIR` | State directory; set by the image |
| `TELEGRAM_TEMP_DIR` | Temporary directory; set by the image |
| `TELEGRAM_HTTP_PORT` | Compose requires internal port `8081`; the release verifier rejects other values. Standalone entrypoint supports other ports. |
| `TELEGRAM_LOCAL` | Local mode; Compose sets `true` |
| `TELEGRAM_STAT` | Statistics endpoint on port `8082`; disabled by default |
| `TELEGRAM_LOG_FILE`, `TELEGRAM_VERBOSITY` | Log destination and verbosity |
| `TELEGRAM_FILTER` | Bot user-ID filter |
| `TELEGRAM_MAX_CONNECTIONS`, `TELEGRAM_MAX_WEBHOOK_CONNECTIONS` | Connection limits |
| `TELEGRAM_PROXY` | Outgoing webhook HTTP proxy |
| `TELEGRAM_HTTP_IP_ADDRESS` | Bot API listen address; loopback makes it unreachable from the gateway container. |

Boolean flags accept `true/false` or `1/0`. Do not set both a credential and its
`_FILE` variant. File-based credentials require mounting the files and changing
the service's environment mapping; simply adding `_FILE` to `.env` is insufficient.

Keep the statistics endpoint internal: upstream output may contain bot tokens.
The gateway currently forwards to port `8081`; changing the container's port also
requires updating nginx.

## Webhook User-Agent

The build applies `patches/webhook-user-agent.patch` to the official server.
Outgoing updates include `User-Agent: WebhookDelivery/1.0`. The neutral name avoids
recipient-side crawler filters that reject User-Agents containing `bot`. Incoming nginx
headers or a header on `setWebhook` do not configure this outgoing header.

## Files in local mode

Split storage is opt-in: add `-f docker-compose.nonroot.yml` and then
`-f docker-compose.files.yml` after the base Compose file. Bot API alone writes
`BOTAPI_MEDIA_SOURCE` at `/var/lib/telegram-bot-api-files` via
`TELEGRAM_FILES_DIR` / `--files-dir`. Without it the legacy combined layout stays
private. State, absolute private temp, logs and credential files must not overlap
media. Relative logs, noncanonical paths and symlink ancestors are rejected.
New directories use umask `0027`; the configured non-root UID/GID owns the media.
Existing cache permissions are never changed recursively.

`--help` / `--version` remain credential-free. Explicit server CLI arguments are
not supplemented from environment variables: split CLI requires long-form
`--files-dir`, `--dir`, `--temp-dir`, matching any configured directory/log env
values. Duplicate directory flags fail. Use the supported non-root overlay for identity
setup; arbitrary Compose `user:` overrides are not supported.
The short `-f` files-directory option is rejected; use validated long-form flags.

`getFile` can return an absolute container-local path. A bot application needs a
matching shared volume/path to read that file directly. Do not turn an arbitrary
absolute path into an HTTP download URL.

For direct reads use the [scoped reader example](https://github.com/ichinya/tg-selfhost-botapi/blob/main/examples/files/README.md).
Only one existing bot subtree is mounted read-only at the identical absolute
path. The Linux/amd64 opener uses openat2 with no symlinks or mount crossings,
rejects hardlinks and nonregular files, and streams from the checked FD. Nested
mounts and a compromised trusted writer/host are outside this deployment contract.
The shared stdlib getFile client (`tools/file_contract.py`) bounds upstream JSON
to 64 KiB / 30 seconds and never follows redirects or environment proxies.

The previously documented `X-Telegram-Bot-Token` download scheme is not implemented.
Remote downloads use the opt-in `docker-compose.downloads.yml` after base+files.
One handler serves one bot: `POST /v1/files/download`, JSON only `file_id`, separate
Bearer credential from `DOWNLOAD_AUTH_TOKEN_FILE`, bot token from
`DOWNLOAD_BOT_TOKEN_FILE`. Only the configured subtree is mounted RO. Loopback
HTTP 18082 must sit behind the TLS frontend in the
[example](https://github.com/ichinya/tg-selfhost-botapi/blob/main/examples/files/README.md).
No registry, alias URL or client-supplied path/token is accepted. Requests and
upstream responses are bounded; streaming uses at most 64 KiB blocks, four slots,
30s socket timeout and a 600s total deadline (`DOWNLOAD_MAX_DURATION`). See the
example for statuses, setup, limits and auth rotation.
Path/URL-like `file_id` values are rejected before upstream I/O. The supplied
remote client requires one Content-Length and fails on an incomplete response;
discard its partial output after any nonzero exit.

## Current limitations

Doctor observes `--files-dir` from the running argv (fallback: work directory),
compares media/private backings and checks scoped read-only consumer mounts.
Shared filesystems contribute capacity once. It does not certify download auth
or application mapping: those remain UNKNOWN until independently checked with
`tools/check_file_contract.py`. A supplied JSON receipt cannot grant READY.

- nginx returns 404 for `/file` and `/file/` requests; it does not serve the state directory.
- File-capable Bot API methods have a `2048m` (2,147,483,648 bytes) body limit, including
  multipart fields and all attachments; larger requests receive HTTP 413. Request
  buffering is on and uses the separate disk-backed spool before forwarding.
  Upload body and upstream send idle timeouts are 300 seconds, upstream read is
  600 seconds, and upstream connect is 5 seconds. These are not total deadlines.
  Upstream describes local-mode uploads up to 2000 MB per file; the gateway limit
  applies to the entire body, so several attachments share it. The 2048 MiB body
  budget leaves 48 MiB beyond 2000 MiB for multipart overhead. Method, image,
  client and external ingress limits still apply; this does not guarantee a
  successful Telegram upload. The pinned upstream has its own approximately
  500-second idle limit; nginx cannot extend it.

  Buffering adds disk I/O and delays forwarding until the body is received. For
  N concurrent uploads budget up to N × 2 GiB plus reserve for nginx alone: N=2
  means approximately 4 GiB plus reserve. Add Bot API temp/work/cache needs on
  the same filesystem. The volume reserves no space or quota, and Doctor's 1 GiB
  default reserve does not qualify a large upload. Check free bytes and inodes,
  including the Docker Desktop disk image. Spool may contain sensitive uploads;
  restrict access. The gateway admits at most two uploads per source address and
  four in total: reserve at least 8 GiB plus operational headroom. Upload starts
  are limited to 2/s per address (burst 4) and 10/s overall (burst 20); excess
  requests receive 429. Source addresses must be preserved by the ingress; nginx
  does not trust forwarded addresses. GET, HEAD and POST are allowed, but GET/HEAD
  bodies are rejected. Other methods receive 403.

  Ordinary RPC bodies are limited to 1 MiB, with 15-second body/send and 30-second
  read idle timeouts. `getUpdates` has a separate 600-second read timeout. Public
  port 80 rejects transfer-encoded requests with 411 before reading the body;
  send uploads with Content-Length. Internal port 82 accepts chunked uploads and
  is not published by Compose: expose it only to trusted clients. These idle
  timeouts are not absolute deadlines: a slow Content-Length upload can still
  hold a slot indefinitely. For untrusted access use an ingress that enforces an
  absolute request deadline or minimum rate, and admission before reading bodies.
- The gateway binds to localhost by default. Set `GATEWAY_BIND=0.0.0.0` in `.env`
  only if remote clients, such as a webhook receiver, must reach it; protect external
  access with HTTPS and appropriate network controls.
- Access logs contain fixed method/route labels and numeric status/bytes/timing.
  Request-bearing error logs are discarded through `/dev/null`; detailed nginx
  request errors are unavailable. External proxy logs need a separate policy.

[Getting started](getting-started.md) · [Maintenance](maintenance.md)

## Complete webhook profile inputs

Before source mutations, the helper resolves `WEBHOOK_SECRET_MODE=provided|none`, `WEBHOOK_IP_MODE=dns|pinned`, `WEBHOOK_CERTIFICATE_MODE=provided|none`, `WEBHOOK_ALLOWED_UPDATES` (JSON array of strings), `WEBHOOK_MAX_CONNECTIONS` and `WEBHOOK_TARGET_LOCAL=true|false`. Unknown secret/IP and unavailable custom certificates stop preflight. `fixed` is an alias for pinned canonical IPv4. Source `ip_address` does not reveal pinning intent. Explicit inputs override source; omitted optional updates become the documented `[]` default. `[]` excludes chat_member, message_reaction and message_reaction_count; it is not every update type. Null or invalid values fail. Per-bot max_connections is 1–100; up to 100000 requires explicit local-mode capability (`TELEGRAM_LOCAL`/`--local`), independently of server `TELEGRAM_MAX_WEBHOOK_CONNECTIONS`. A self-host URL does not establish this capability.

Use `WEBHOOK_SECRET_TOKEN` or `WEBHOOK_SECRET_TOKEN_FILE`, exactly one for provided mode; none asserts an intentionally unprotected webhook. Secret files allow one final LF/CRLF; inline secrets are never trimmed. Use `WEBHOOK_CERTIFICATE_FILE` for a public PEM, never a private key. Protected files (including `BOT_TOKEN_FILE`) must be outside checkout/webroot, with operator-only access. Values from the process override trusted `ENV_FILE` (default: helper directory `.env`), including explicitly empty values; value/file pairs are selected at one tier. Positional URLs remain highest priority. Polling has no webhook profile.

Full profile transport is enabled: urlencoded without a certificate, entirely multipart with a certificate. Secret/scalar files are private snapshots; no token/secret/URL is placed in curl argv or shareable diagnostics. The helper disables tracing, uses curl -q without redirects, guards HTTP/ok/result and never retries a mutation. Public PEM requires Bash 4+, jq, curl, realpath and openssl X.509 validation; no private key is accepted. Temporary files use umask 077 and are removed on exit/signals.

## Host-side migration timeouts

The root `migrate_off_to_self.sh` helper accepts `MIGRATION_CONNECT_TIMEOUT`
(default 5 seconds, integer 1..60) and `MIGRATION_REQUEST_DEADLINE` (default
30 seconds, integer 1..300). The connect timeout must not exceed the deadline.
The deadline applies to each request; the token-free probe is capped at 10
seconds. Process settings take precedence over the trusted environment file;
only an unset setting uses its default. Unlike the endpoint settings, an
explicitly empty timeout is invalid. These settings are not passed to containers.

### Gateway logs

The base Compose mounts `nginx-main.conf` read-only for every profile. Access logs
contain only fixed method/route labels, numeric status/bytes and timing. Unknown
methods use OTHER and unknown paths use other. Request errors are discarded via
`error_log /dev/null`, including inherited contexts. Diagnose status and timing
counters; detailed nginx request errors are unavailable. External proxy logs need
an independent policy. Doctor accepts only the exact fixed-label maps and treats
custom logging as UNKNOWN.

### Native Bot API diagnostics

Our own build includes privacy policy `issue17-v1`: Query logs use counts, webhook
log messages omit private state, and the log sink projects every native/TDLib event
to a fixed severity label before file and memory storage. Detailed native log
messages are unavailable. Supported file/memory verbosity is 0..3; higher startup
values are rejected and runtime verbosity escalation is clamped. Crash diagnostics
omit actor tags and debugger locals; core dumps are disabled by the entrypoint.
This guarantee requires the qualified own image/digest, not an arbitrary upstream
image selected by BOTAPI_IMAGE. Private webhook persistence and outgoing secret
headers keep their original bytes. Version output remains available.

## Safe statistics

`TELEGRAM_STAT` defaults to false. When enabled, raw statistics bind only to
127.0.0.1:8082 in the Bot API namespace. Never publish or proxy this port.
The observer accepts the reviewed tab-separated manager format and returns only
numeric observations. Queue coverage is always sampled: omitted pending fields
mean unknown, and the observed sum is a lower bound, never a global total.
Malformed, duplicate, oversized, Closing or incompatible responses are unavailable.

## Observer deployment and isolation

Before Compose up, prepare inputs on the Linux host:

```sh
install -d -m 0700 .observability
install -d -m 0755 .observability/runtime .observability/migration
sudo install -d -o 101 -g 101 -m 0700 .observability/registry .observability/credentials
python3 tools/image_inputs.py --build-env .env.build
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

The observer shares only Bot API's network namespace. It runs as 101:101 with a
read-only root, dropped capabilities and no Docker socket, state/temp or private
migration dossier mount. Empty directories work without bot credentials. Host
management is `http://127.0.0.1:18081`; only three exact management routes are
proxied, GET/HEAD only, without query/body/Authorization. API listener 18080
blocks these routes. Both APIs use delayed Docker DNS resolution so nginx can
start while a target is absent; management upstream errors become a fixed 503.
Management 4xx responses generated by nginx can use its standard HTML error pages.
API ports 8082/8090 are reserved. A custom API port also needs an nginx override
and doctor validation. Raw stats remain loopback-only. Observer 8090 is trusted
Compose-network access, never a public monitoring ingress.

Doctor understands the supported route contexts and network owner; unsupported
variables, extra management routes, public management bindings, raw stats proxying,
state/socket mounts or wrong namespace owners fail or remain unknown. Doctor is
preflight and never substitutes for continuous health or actual delivery evidence.
The base is pinned Alpine; APK Python/curl/jq package repositories remain mutable.
Immutable image pairs capture the resulting build; byte-reproducibility is not promised.

The published observer uses a digest-pinned Python base resolved by CI. The local
fallback uses pinned Alpine plus APK Python; set OBSERVER_BASE to an approved
Python image digest to reproduce the release base. Host producer supervision,
registry/credential permissions and ownership/rotation are described in
[maintenance](maintenance.md). A section's ready state describes its observation
source; inspect migration outcomes separately from process readiness.

## Saved build inputs

`image-inputs.lock.json` is an unqualified, dated source/base discovery snapshot.
Replay is offline: `python3 tools/image_inputs.py --build-env .env.build --json-file /private/resolved.json`.
Use `docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --build`.
Keep generated inputs private. The observer uses the same Alpine base in local builds and CI;
optional downloads uses the saved Python base. Discovery is explicit (`--save-discovery /private/candidate.json`);
it retains the selected server revision until a reviewed source update. PR builds replay the committed snapshot.
The build key excludes deployment digests and documentation; qualification has its own key.
The local build overlay and downloads explicitly select `linux/amd64`; emulation
does not qualify a native ARM64 release.
Historical base digests require fresh registry/platform/support checks in CI before release selection.

The test-only sender artifact is retained by digest alongside each qualified runtime;
reuse pulls it without recompiling. A missing paired test artifact blocks reuse until evidence is restored.
After committing a packaging change, use `--capture-wrapper /private/source-inputs.json`
then replay that file with `--inputs-file` to bind the actual wrapper commit.
