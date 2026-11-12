---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Changing the server identity

Stop the writer and its restart automation before changing IDs. Make a consistent
backup that preserves numeric ownership and modes. Verify the dedicated absolute
paths, symlinks and other mounts; prepare an offline copy for the new UID/GID and
inspect nested binlog and session files, not just the root. Run a storage smoke
test, then start one writer. Keep the old copy with its original IDs and a
compatible image for rollback. Do not recursively change permissions on a live or
shared database. Existing cached paths are not migrated automatically.

Prepare both state and HTTP temp for the effective server identity. Bind mounts,
named volumes and tmpfs each have their own ownership and permissions; ownership
inside the image does not fix mounted storage. New files use the effective UID;
without filesystem inheritance their GID is the primary GID, while setgid or ACL
rules can alter inheritance. Umask `0027` limits new modes but does not add group
read permissions or change existing files. Keep migration dossiers owner-only.
Docker supplementary groups are retained in direct non-root launches. A different
UID reading media needs the scoped read-only subtree described in Getting started.

## Split storage

Split storage requires a maintenance window: stop clients and writers, back up
private state and configuration consistently, then enable the files override.
It creates a new media cache; it does not move old downloads or rewrite stored
absolute paths. Keep legacy storage private and re-run getFile for saved file IDs.
Runtime identity and real TDLib file modes require qualification of the exact
image; source/unit checks alone do not establish production permissions.


Doctor checks split media persistence and private backing separation without
downloading real files. Optional handlers and consumer mapping remain UNKNOWN;
use the independent synthetic file gate and inspect the deployed mapping.

## Migration acceptance

Use the required Linux/Node 24 mock gate documented in CONTRIBUTING. It covers
response loss before/after effects, per-bot locking, crashes around intent and
receipt, interface plan parity, helper access and UI response loss. The volume
gate operates only on exact fixture IDs/labels and preserves production data.
CI checks that required files are tracked and that no private artifacts enter
the rendered site. Platform skips are not acceptance. The old curl-specific
request assertions are retained as reference; executable adapter tests now
exercise the same loopback protocol/journal as the canonical CLI. Issue #9's
missing delivery-action fixture is a separate declared workspace baseline.

Restarting the helper requires a new session code and private runtime inputs.
Keep the same journal/key. Browser disconnect does not cancel the background
job. Read status and its job result, then resupply credentials before resume.
An operation locator is not authorization.

## Recovering the migration journal

Back up the whole private authority **together with `binding.key`** while idle.
Restore both with their owner and private modes. Missing keys, token rotation,
corrupt or unsupported state block continuation. Interrupted durable intents
become UNKNOWN. Restore the original authority and reconcile the same operation;
starting an empty state root cannot establish whether a remote effect occurred.

After a UI timeout read the same operation's offline status first. If only the
browser lost the response, durable receipts still apply. If the Bot API response
was lost, reconcile UNKNOWN with a trusted provider receipt bound to the exact
operation/digest/attempt/endpoints/token and observation time. Without evidence,
keep it blocked. A changed token/deployment/profile requires investigation and
review, preserving the original journal; never erase confirmed history.

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

The build key covers the resolved revisions/digests and the recipe, entrypoint,
patch and image tests. If the corresponding published build exists, compilation
is skipped; the candidate is pulled by digest and qualified again. If registry
inspection cannot confirm it, the pipeline rebuilds. Acceptance scripts, fixtures,
both storage overlays and their tests are part of the build key.
The Bot API build key covers the resolved revisions/digests and file-contract
recipe/tests/configs. Downloads has its own key including the immutable Python
base. If a Bot API build exists, compilation may be skipped, but the exact reused
image and the downloads candidate must pass the current file gate again.
Unconfirmed registry inspection rebuilds; it never establishes a passing gate.

For a new build it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Compiles the entire server.
3. Runs `--version`, checks the header string in the binary and validates entrypoint syntax.
4. Checks the selected source revision and TDLib submodule for download modes
   `0640/0750`, internal media temp paths and rename semantics.
5. Qualifies the exact image ID with the non-root storage matrix and the existing
   migration volume gate.
6. Builds the downloads image, runs synthetic local/TLS/negative checks and
   network-none actual Bot API startup for the exact image pair, recording IDs and
   source hashes. It also checks rendered Pages/private exclusions.
7. Publishes tested `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>` and
   `ghcr.io/ichinya/tg-selfhost-botapi-downloads:build-<downloads-key>`, then promotes
   their `latest` tags without rebuilding the tested pair.
   Reused builds also pass the qualification gates before promotion.

The standalone `files.yml` workflow runs full unit discovery on a clean checkout,
Compose combinations, state isolation, exact-pair integration and docs checks.
Unavailable local runtime checks are `verification deferred to CI/gates`; CI must
pass them before image publication. This does not deploy or verify a VPS.

Failed checks leave the previously published `latest` in place. Pull requests do
not publish. A binary string check is not a live webhook-delivery test.

The workflow needs to be on the default branch before the schedule/publication
can work. GHCR writes use `GITHUB_TOKEN` with `packages: write`. Configure package
visibility or client authentication after the first publication.

## Non-root candidate qualification

On a local rootful Linux Docker Engine with a POSIX filesystem, Python 3.11+
and current Compose v2, run against an explicitly built candidate:

```sh
python3 tools/check_nonroot_compose.py --deadline 120
python3 tools/check_nonroot.py --image <candidate> --deadline 1200
python3 tools/check_migration_volumes.py --require-docker --image <candidate> --receipt /tmp/migration-volume-gate.json
```

The explicit runner uses random labelled resources, network isolation, synthetic
credentials, bounded calls and ownership-checked cleanup. It covers root bootstrap
to `101:101`, explicit `101:101`, `1000:1000` and `1000:2000` (without a passwd
entry), supplementary groups, PID 1 and token-free HTTP, migration evidence,
fresh/prepared bind and named volumes, restart/recreate, preserved canaries,
denied/read-only state and temp, foreign ownership, group access and an unreadable
binlog actually opened by the server. Compose checks use production files and
reject missing inputs, backing aliases and `base+files` without the non-root layer.

The media fixture checks inode/GID/modes across an internal temp-to-final rename,
scoped read-only access by another UID, POSIX write denial independently of the
read-only mount, and stranger denial. It rejects a download temp on another mount.
This synthetic fixture demonstrates the permission recipe; source assertions are
checked against the selected revision in CI. Neither proves a Telegram download.
Unit tests run without Docker; real-image acceptance, CI and production are separate
observations. Unavailable checks are NOTRUN: verification deferred to CI/gates.
Docker Desktop, rootless/user namespaces and network filesystems require separate
qualification. Never run this harness against production mounts.

## Update an installation

### Enable split storage / roll back

1. Stop clients, downloads, Bot API writers and any supervisors that restart them.
   Make a consistent backup of the private state, image identity, Compose/env,
   secret files and, for an existing split installation, media separately.
2. In a maintenance window enable the non-root and `docker-compose.files.yml` overlays, retaining the exact
   qualified image/config. Never copy state/binlogs into media or edit TDLib DB
   paths by hand. The default transition starts a new media cache.
   Prepare the new media source for the configured UID/GID as described in Getting started;
   Compose refuses a missing root.
3. Re-run getFile for saved file IDs. Verify that each returned path lies in the
   new media bot subtree, verify bytes/digest, ownership and mount mapping before
   enabling consumers. If upstream returns an old private path, fail closed and
   investigate; do not grant access to private state. Old cache/path continuity is
   not guaranteed. A cold cache move preserving paths needs separate validation
   for the selected upstream version.
4. Rollback requires stopping new writers and restoring a mutually compatible
   image, configuration, private state and old layout from the consistent backup.
   Restoring an image alone is insufficient. Keep any split media snapshots in
   sync with state when moving between servers.

Do not recursively chmod/chown the cache or grant world access. Check actual
TDLib modes and the configured writer UID/GID; give the reader that identity or a specifically
validated read/traverse ACL. Each handler/reader gets one RO subtree, no parent,
sibling, private temp/log/secret mounts or nested mounts. The local API and writer
are trusted; mutually untrusted operators need separate instances/storage.

Rotation replaces the protected Bearer file and restarts downloads. Confirm the
old credential gets 401 and the new one retrieves synthetic bytes. Cache eviction,
30s I/O timeout and the total deadline can interrupt transfers; no Range/resume
or retention SLA is promised. Never paste token-bearing paths into reports.

Registry publication does not restart your VPS. Select a tested tag/digest with
`BOTAPI_IMAGE` and matching `OBSERVER_IMAGE` in `.env`. Every update command must use exactly the same Compose
files, in the same order, as the installation. Choose the matching `COMPOSE_FILES`:

```sh
# base
COMPOSE_FILES='-f docker-compose.yml'
# base + build
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.build.yml'
# base + nonroot
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml'
# base + nonroot + files
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml'
# base + nonroot + build
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.build.yml'
# base + nonroot + files + build
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml -f docker-compose.build.yml'
```

Select only one line above. Omitting nonroot/files overrides changes the server
identity back to `101:101`, reconnects state to `./data` and drops the media mount.
For a registry installation:

```sh
docker compose $COMPOSE_FILES stop observer botapi
# Back up the actual state source and private configuration consistently.
docker compose $COMPOSE_FILES pull botapi observer gateway
docker compose $COMPOSE_FILES up -d --force-recreate botapi observer gateway
docker compose $COMPOSE_FILES logs --tail=100 botapi
```

For a local build, replace `pull` with `build` using the same selected files.
Preserve the actual state source (`$BOTAPI_STATE_SOURCE` for nonroot, `./data`
for the base model), ownership for the selected server identity (default `101:101`),
the API endpoint and local-mode settings.
Do not run two Bot API processes against one data directory. Restoring an old
image may also require a compatible state backup; image rollback alone is not
a guarantee.

After an update, check service logs and send a test message to a bot already
assigned to the server. Confirm the actual webhook URL, delivery status and
User-Agent in the receiving service's logs.

## Diagnostics

```sh
docker compose ps
docker compose logs --tail=100 botapi gateway
docker compose exec botapi telegram-bot-api --version
```

Remove tokens, API hashes, webhook secrets and sensitive URLs before sharing
logs. Separate infrastructure reachability from bot authorization and delivery.

## Documentation and contributions

Documentation lives in `docs/en` and `docs/ru`. Update both languages for
behavioral changes. The short root README links to these guides.

The Pages site uses Jekyll from the existing `main /` publishing source.
`_config.yml` supplies the project base path and navigation; `_layouts/default.html`
is the shared layout. Markdown links are rewritten for Pages by
`jekyll-relative-links`, while remaining usable on GitHub.

The original `tg_selfhost_botapi_migrator.html` URL remains available. Docs changes
are built in PRs without deployment; merging to `main` publishes through the
existing Pages integration.

[Contribution guide](../../CONTRIBUTING.md) ·
[Current work](https://github.com/ichinya/tg-selfhost-botapi/issues/19)

### Doctor preflight

`python3 tools/doctor.py --scenario official-to-self --format json` provides a
versioned diagnostic report. Use Python 3.11 or newer. JSON and text share exit
codes: 0 READY, 1 BLOCKED, 2 invalid invocation/input, 3 UNKNOWN (including internal collection errors). READY covers
migration prerequisites, not authorization or delivery. Missing evidence remains
UNKNOWN. Subprocesses and token-free HTTP share a deadline (60 seconds by default,
5 seconds per operation). HTTP has no proxy, redirects or retries, verifies TLS,
and reads at most 16 KiB. Reports omit raw outputs and redact credential patterns.

Process evidence comes from `/proc` in the selected container, including effective
UID/GID/groups. Root probes require a 404 JSON response with `ok:false` and integer
`error_code:404`; a generic 404 is insufficient. Direct bridge probing is supported
on a local Linux engine. Docker Desktop, remote engines, external proxies and
ambiguous bindings leave the affected checks UNKNOWN. No bot or cloud method is
called. Actual image config IDs, registry digests and binary versions are separate
fields; a local image without registry digests is reported honestly without pull.
Stopped, paused, restarting, dead or unhealthy containers block readiness;
pending health remains UNKNOWN. An unavailable endpoint is BLOCKED at a supported
observation point; an unavailable observation point remains UNKNOWN.
Exposure findings use parsed nginx includes plus independent mount isolation.
A random 404 is not evidence of isolation. A state alias or accessible state mount
blocks readiness; the shipped proxy and logging map are supported. Doctor does not reload nginx.

### Doctor regression checks

Run `python3 -m unittest discover -s tools -p 'test_doctor*.py' -v` and
`python3 -m unittest discover -s tools -p 'test_check_doctor.py' -v` for pure tests.
The explicit `python3 tools/check_doctor.py` command creates and removes only its
random synthetic Compose project. It checks real nginx, volumes, runtime UID,
root-only HTTP requests and probe cleanup. The harness may pull/build its test
images; doctor itself only inspects the selected installation. Base version tags
are resolved to immutable registry digests at harness start and recorded in its
result; approved digests can be supplied via `DOCTOR_PYTHON_IMAGE` and
`DOCTOR_NGINX_IMAGE`. Reports distinguish synthetic integration, real-image smoke,
CI and production. A skipped gate is NOTRUN, never PASS.
Pure regressions also cover self-to-self selected-subtree capacity, shared-state
rejection, compatibility uncertainty and credential sentinels in both renderers.
The doctor workflow runs the repository unit suite and fixture shell syntax check
before the separate synthetic Docker gate.

### Doctor operator reference

Select the same ordered Compose inputs used for deployment:

```sh
python3 tools/doctor.py -f docker-compose.yml -f docker-compose.build.yml \
  --env-file /private/installation.env --project-directory /private/stack \
  -p installation --scenario official-to-self \
  --migration-input /private/decisions.json --format json
```

Profiles use repeatable `--profile`. For self-to-self add a separate ordered
`--source-file` list and the corresponding `--source-env-file`, `--source-profile`,
`--source-project-directory`, `--source-project-name`; use
`--source-gateway-url` only for a mapped source binding. The main context is the
target, except in self-to-official where it is the local source.

| Option / result | Meaning |
| --- | --- |
| `--gateway-url` | Optional selected published endpoint; no credentials, query, fragment or bot path |
| `--timeout`, `--deadline` | Positive seconds; defaults 5 and 60 |
| `--no-write-probe` | No doctor writes; write evidence UNKNOWN |
| `--min-free-bytes`, `--min-free-inodes` | Positive integer reserve thresholds; defaults 1073741824 and 1024 |
| `--format text` / `json` | Same decision and exit; JSON is one stdout document |
| 0 / READY | All required preflight evidence passes |
| 1 / BLOCKED | At least one required condition fails |
| 3 / UNKNOWN | Required evidence is incomplete and no required condition fails |
| 2 / UNKNOWN | Invalid invocation or private input |

Report schema: `tools/doctor.schema.json`. Input schema:
`tools/doctor-input.schema.json`. Keep real inputs and reports private, outside
VCS, docs and the webroot. Do not paste tokens or API hashes into CLI arguments.
Wildcard published addresses become loopback; multiple bindings require an exact
explicit selection. Opaque reverse proxies and deployment prefixes currently
remain `endpoint_mapping_unverified`; they are not probed. No cloud HTTP request,
getMe, logOut, close, webhook change or migration is performed. Re-run diagnosis
when containers, mounts or configuration change; READY does not certify future
state, Telegram sessions or the Bash/browser executor.

JSON v1 uses `infrastructure`, `migration.executor_support`, and checks with `check_id` and `PASS|FAIL|UNKNOWN|SKIP`. Internal errors retain earlier findings; required FAIL takes precedence over UNKNOWN. Empty or skipped required evidence cannot establish readiness.

Exit 2 also covers an invalid Compose configuration or missing Compose JSON
capability. Missing Docker/daemon access yields UNKNOWN/3. Version, process,
configuration and storage execs have a container-side deadline as well as the
shared host budget. Unsupported timeout utilities leave evidence UNKNOWN.

Empty registry metadata uses `local_build` only for a selected Compose build;
otherwise it uses `registry_digest_unavailable`. No registry request is made.
`runtime_changed` invalidates dependent evidence when container identity, restart
count, effective Compose model or the on-disk nginx snapshot changes.
For `quota_accounting_unverified`, verify the service identity's actual quota
headroom separately. `unsafe_input_permissions` is BLOCKED/1; unreadable or
malformed private input is exit 2, and unverified platform privacy is UNKNOWN/3.

Postflight performs two target reads separated by two seconds within a ten-second observation deadline. It compares exact URL, update sets, connections, certificate presence and fixed IP. DNS IP is observational. Pending trend and historical/new delivery/synchronization errors are reported separately using counters only. An empty queue does not prove delivery. Secret and certificate bytes cannot be verified by WebhookInfo. New errors, missing counters or mismatched readable settings stop acceptance; mutations are never retried.

## Independent webhook receipt and sender gate

Use a dedicated test bot/application. With the expected secret in protected environment (or WEBHOOK_SECRET_TOKEN_FILE outside checkout/webroot), run:

~~~sh
python3 tools/webhook_profile_receiver.py --expected-update-id 701 --seconds 60
~~~

This receiver listens on loopback only; publish it through your controlled TLS test reverse proxy for a real test-bot delivery. The receiver's loopback_port is chosen at startup. A manual synthetic POST checks only receiver acceptance: missing/wrong/duplicate secret headers return 403, unrelated update_id returns 409. Receipts contain only update_id, time, secret_matched and count. Keep receipts outside webroot and correlate the expected update_id with a new test-bot event; WebhookInfo and an unrelated receipt never confirm delivery. A public certificate may be uploaded; its test private key stays outside exports/repository.

The explicit source gate checks pinned BOT_API_REVISION and the real WebhookActor conditional header code, after applying tracked patches/webhook-user-agent.patch:

~~~sh
python3 tools/check_issue7_sender.py --source /path/to/pinned/telegram-bot-api
~~~

CI fetches that exact revision, never master. Source assertions are not runtime delivery. An isolated C++ sender harness is NOTRUN unless independently built against the same source; a live test-bot update with a correlated receipt is a third, deployment-specific check. No real Telegram credentials are required for receiver unit tests.

## Profile qualification gates

Use `timeout 420 python3 -m unittest tools.test_webhook_profile_contract tools.test_webhook_profile_ui tools.test_webhook_profile_transport tools.test_webhook_profile_receiver -v` with `PYTHONPATH=.:tools`, Node 24+, Bash 4+, curl, jq and openssl, as a non-root POSIX runner. The 22 shared fixtures execute the shipped inline resolver and Bash jq program; actual HTTP tests parse URL-encoded and multipart bodies, run helper/export, reject mismatched readback and exercise receiver receipts. Privacy canaries cover output, clipboard, public state, reflected API errors and curl argv. The scoped workflow runs the same suite and tracked #10 regressions, with a separate pinned-source sender job. Existing untracked issue7 drafts and Node 20 workflows are not dependencies.

Image/default upstream logger qualification, multipart through shipped nginx, a C++ sender harness, Jekyll rendered checks and real Telegram delivery remain explicit external gates. Unavailable execution is NOTRUN: verification deferred to CI/gates. Own builds use issue17-v1 fixed log projection before file/memory storage; qualify the exact image before deployment.

### Private migration evidence

The root helper keeps schema version 1 intent/receipt/summary evidence under
`logs/migration` beside the script, with directories 0700 and files 0600. Keep
this outside public hosting; the publication checker rejects `logs`. Retention
continues until deliberate manual deletion after reconciliation. Never attach
raw capture or the dossier to public issues. A crash can retain private raw;
normal capture removes it only after successful sanitization. The summary marks
possible retention when finalization fails.

An active/stale lock, unfinished intent, UNKNOWN authenticated attempt or partial
migration blocks the next run before HTTP. Stop and inspect independent evidence;
there is no automatic unlock, retry or resume. Schema v1 is an input contract for
an explicit future #2 adapter, not that issue's final durable journal. See
[outcomes and private diagnostics](migration.md#outcomes-and-private-diagnostics).

For manual recovery, stop every helper, reconcile all attempts with independent
evidence, and decide the safe next procedure. Archive the complete dossier in an
owner-only location outside `logs/migration` before removing reconciled run
directories and a stale lock. Keep the archive until resolution. A lock must
never be removed merely to retry an unknown request. An unfinished token-free
probe without a surviving lock does not block; authenticated unfinished attempts do.

## Operational status schema v1

The observer exposes independent `process`, `migration`, `webhook`, `queue`,
`storage` and `image` observations. Each has a fixed source, state, reason,
UTC `observed_at` and age in seconds. Unknown counts are null, never implied zero.
Process readiness does not establish migration completion or webhook delivery.
The public JSON schema is `tools/observability/status.schema.json`; unknown fields,
invalid integers, future timestamps and oversized documents are rejected.

## Host runtime producer

Storage and image identity come from a trusted Python 3 host CLI, not the HTTP
observer. With the same project name/files as deployment, run:

```sh
python3 tools/observe_runtime.py --project-directory "$PWD" --file docker-compose.yml --file docker-compose.build.yml --watch
```

Prepare `.observability/runtime` as an owned 0755 directory. Atomic 0644 status.json
is mounted read-only; output contains no paths, environment or raw inspect fields.
The producer selects exactly one Bot API, reads PID 1 flags and effective UID/GID,
gets filesystem metadata for actual work/temp, binary version and actual image
metadata, then rechecks container identity. Custom unsupported images fail closed.
Filesystem IDs let you recognize work/temp on the same filesystem: do not sum them.
Available inodes can be null; capacity is not a quota or write-readiness check.
Local builds may have no registry digest. Binary version, source revision, build
key, image ID and digest are distinct. Without a successful producer they are
unknown; after 90 seconds the snapshot is stale. Health remains independent.

For supervision, install an operator-owned systemd service with `Type=simple`,
`WorkingDirectory=/opt/tg-selfhost-botapi`, `ExecStart=/usr/bin/python3 /opt/tg-selfhost-botapi/tools/observe_runtime.py --project-directory /opt/tg-selfhost-botapi --file docker-compose.yml --file docker-compose.build.yml --watch`,
`Restart=on-failure`, `RestartSec=5`, `UMask=0077`; run as the trusted Docker-capable
host account and enable with `systemctl enable --now botapi-observation.service`.
Alternatively use a oneshot service with the same command without --watch and a
timer `OnBootSec=30`, `OnUnitActiveSec=30`. Docker access grants host privileges;
never mount its socket in observer. A manual oneshot needs regular renewal.

## Candidate-pair acceptance

The build key covers every observer Python module, JSON schema, health helper and
Docker/Compose/nginx recipe. CI resolves a digest-pinned Python observer base,
loads both exact candidates and checks their shared build-key labels. Reuse still
requires a fresh pair qualification; a missing image is built and the complete
pair is tested before publication. PRs never publish. `build-<key>` and
`observer-build-<key>` are immutable deployment inputs; latest aliases are promoted
only after gates and their promotion is not atomic.

Run the isolated gate explicitly with `python3 tools/check_observability.py
--botapi-image botapi-candidate:check --observer-image observer-candidate:check`.
It creates a random internal Docker network, uses synthetic inputs, tests mock
privacy and actual root/manager/helper behavior, and removes its own containers.
`python3 tools/check_stats_source.py <upstream-checkout>` checks the reviewed source
fragments of the exact candidate revision. A changed format requires review.
Actual image build/smoke, POSIX producer/file gates, CI/Jekyll/Kuma and production
have not been executed in this Windows implementation pass: verification deferred
to CI/gates. Mock tests do not establish privacy of an actual Bot API logging
configuration. Keep authenticated polling disabled until that deployment's
synthetic token privacy gate has passed at its supported verbosity.

## Opt-in webhook diagnostics

Polling is disabled with an empty OBSERVER_REGISTRY. To enable it, first run the
host runtime producer and copy its current `.image.instance` into a private
`registry.json` under `.observability/registry` (file mode 0600, owner 101:101):

```json
{"schema_version":1,"enabled":true,"instance":"<64 hex characters from the fresh runtime snapshot>","allow_unobserved_migration":false,"bots":[{"alias":"public_label","credential_file":"bot.json"}]}
```

Store `{"token":"<BOT_TOKEN>"}` in `.observability/credentials/bot.json`, mode 0600,
owner 101:101, then set `OBSERVER_REGISTRY=/inputs/registry/registry.json`.
Aliases are public `[A-Za-z0-9][A-Za-z0-9_-]{0,31}` labels; never use a secret as a
label. The target is fixed to the local Bot API bind/port. No cloud fallback or
autodiscovery exists. Stats never provide credentials. With a migration producer,
set `OBSERVER_MIGRATION_DIR=/inputs/migration`: only fresh, confirmed finished
operations allow polling. Without a producer, `allow_unobserved_migration=true`
is a separate explicit ownership opt-in and requires pausing before every move.
Disable `enabled`, wait at least 60 seconds for in-flight bounded requests to
finish, and pause before migration. It is not a cross-host lock. Recreate changes
the instance; old confirmation stops working. Refresh host metadata, reconcile
migration, then explicitly update instance and enable. Replace private files
atomically for rotation; mount directories so rename is visible.
After observer restart, the worker stays closed until the first later runtime snapshot.

The worker polls only getWebhookInfo, every 60 seconds, at most four concurrently,
with a 2-second request deadline and no immediate retries (including 429). Public
results contain mode, registered pending count, historical error time/category
and synchronization error time; no URL/IP/header/raw error text. Delivery remains
not_observed. Run the synthetic actual-image logging privacy gate before enabling.

## Uptime Kuma

Create two HTTP(s) GET monitors against your private management ingress:

- `Bot API liveness`: `http://127.0.0.1:18081/health/live`.
- `Bot API infrastructure readiness (HTTP handler / manager if enabled)`:
  `http://127.0.0.1:18081/health/ready`.

For both: accepted status **200 only**, timeout **5 seconds**, heartbeat interval
**60 seconds**, retries **2**, redirects **off**. No bot token or webhook secret.
A remote Kuma must use a protected HTTPS ingress, VPN or tunnel with its own access
control. In a Kuma container, 127.0.0.1 means Kuma itself: configure and verify its
reachable private management ingress hostname/port. Never use raw 8082 or publish
8090. HTTP 200 `/status` does not mean every component is UP; optional JSON checks
must inspect the relevant section and freshness under schema_version 1.

Expected interpretations: process ready + migration unknown is valid; historical
webhook error is not current DOWN; growing sampled backlog is a lower-bound trend;
stats disabled yields unknown queue, not zero; stale runtime means disk/image
unknown for current decisions. Polling mode does not establish a live consumer.
No URL, zero pending count, absent error or migration completion confirms delivery.
Only an independently authorized update and recipient evidence can do that.

Acceptance on an isolated deployment: record the Kuma version and configured
private endpoints/settings; observe UP, stop Bot API and observe DOWN, recreate
the complete pair and gateway and observe UP. Separately stop observer to
distinguish its failure. This manual Kuma acceptance is NOTRUN in this pass.

## Updating and rollback of the pair

Pin BOTAPI_IMAGE to `build-<key>` and OBSERVER_IMAGE to `observer-build-<same-key>`
or their exact digests. Keep the same project and Compose overrides throughout:

```sh
docker compose pull botapi observer gateway
docker compose up -d --force-recreate botapi observer gateway
```

For local builds use both `-f docker-compose.yml -f docker-compose.build.yml` on
build/up. Recreate observer whenever its namespace owner changes; recreate gateway
to refresh routing. Rollback selects the previous compatible pair and follows the
same procedure, with a compatible state backup when needed. A botapi-only
--no-deps update is incomplete. Docker unhealthy is a signal, not automatic restart
or recovery. Recheck health, source freshness and ownership after every replacement.

## Isolated mock walkthrough

Use Linux/WSL and the following loopback-only fixture. It cannot send requests
to Telegram. Each scenario starts fresh fixture servers and private state; this
is not a recovery recipe for a real bot. Set `MIGRATION_FIXTURE_DIRECTION` to
one of the four direction names before starting. Complete within the evidence
TTL (five minutes), otherwise restart the fixture for a new isolated scenario.

```sh
umask 077
PYTHONPATH=tools python3 - <<'PY'
import json, os, tempfile
from pathlib import Path
from migration_mock import Bot, TOKEN, deployment
from migration_helper import Application, Server, write_bootstrap
root = Path(tempfile.mkdtemp(prefix="botapi-fixture-"))
source, target = Bot("source"), Bot("target")
direction = os.environ.get("MIGRATION_FIXTURE_DIRECTION", "cloud_to_local")
endpoint = source.endpoint if direction == "webhook_only" else target.endpoint
evidence = root / "deployment.json"
record = deployment(endpoint)
record["local_mode"] = direction != "local_to_cloud"
evidence.write_text(json.dumps(record))
evidence.chmod(0o600)
app = Application({"state_dir": str(root / "state"), "allowed_endpoints": [source.endpoint, target.endpoint],
                   "evidence_file": str(evidence), "trust_file": None, "fixture": True})
server = Server(app, 8765)
pairing = root / "pairing-code"
write_bootstrap(pairing, server.bootstrap, [root / "state"])
print("Synthetic fixture only:", server.origin, "private pairing file:", pairing, flush=True)
print("Synthetic source/target ready; private inputs withheld", flush=True)
print("Retained fixture authority:", root, flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close(); app.close(); target.close(); source.close()
PY
```

1. Read the one-time code privately from the pairing file. Enter the printed fixture endpoints/
   synthetic token, matching direction/mode, explicit polling and quiescence JSON
   `"fixture"`. Local → Cloud also selects queue acknowledgement and cooldown 0.
2. Plan, review the digest, then Apply. Confirm source detach precedes target
   authorization. The migration remains partial until endpoint/start checkpoints.
3. Enter `"fixture"` for endpoint-change and application-start receipts, then
   Resume. Keep delivery as NOTRUN until a separate receiver receipt is imported.
4. For Local → Local, execution first blocks after close. A fixture transfer
   receipt needs exact operation_id/digest/close_attempt/source_fingerprint/
   target_fingerprint, target_deployment equal to the plan deployment fingerprint,
   matching 64-hex source_manifest/target_manifest, a 64-hex source_deployment,
   uid/gid 1000, current observed_at and true source_closed/no_writers/layout_valid.
   This tests the attestation boundary, not a real TDLib directory transfer.
5. Reload the browser and read status. Repeated Resume does not increase confirmed
   mutation counters. Automated fault tests separately inject lost responses.

Provision real providers in a private `MIGRATION_TRUST_FILE` with shape
`{"providers":{"audit":{"key_hex":"<private-64-hex-key>","kinds":["quiescence","effect","endpoint_change","application_start","state_transfer","delivery"],"fixture":false}}}`.
A signed envelope has provider/payload/signature. Signature is HMAC-SHA256 of
canonical sorted compact ASCII JSON payload using that independent key. Common
payload fields: version 1, kind, operation_id, digest, source_fingerprint,
target_fingerprint, token_fingerprint and observed_at. Quiescence additionally
requires no_writers=true; endpoint/start require endpoint_fingerprint. Provider
implementations must verify the external facts before signing. No provider is
trusted by default, and fixture providers cannot attest real operations.
`public-manifest.json` is the only shareable helper diagnostics file. Never archive the private dossier recursively; failed cleanup requires private reconciliation.
Gateway diagnostics use fixed access status/timing records. Request-bearing nginx error logs are discarded; external proxies require separate verification.
Native privacy acceptance requires the exact own build/digest, source-linked driver and actual binary checks. Policy issue17-v1 replaces native log text with fixed severity labels before file/memory storage. The source driver is not end-to-end webhook delivery evidence.

### Issue #17 exact-candidate gates

Run `python3 tools/issue17_security_gate.py --unit` in a clean committed checkout.
Use `--runtime` for disposable Compose/entrypoint/gateway tests and `--image
botapi-candidate:check --expected-build-key BUILD_KEY` for the exact native image.
The image workflow requalifies reused immutable tags before promotion. A missing
policy label, driver, positive HTTP/log control or required runner blocks success.
Only sanitized manifests are uploaded. Linux permissions, full clean discovery,
Docker/native image and Pages builds are separate checks. If unavailable locally,
record NOTRUN: verification deferred to CI/gates; synthetic tests never deploy or
contact a real Telegram bot. An external deployment needs separate authorization.
