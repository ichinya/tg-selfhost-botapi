---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

Before selecting a release, run the scoped checks from CONTRIBUTING and
`python3 tools/check_compose_models.py`. The latter checks merged layouts and
local component identity without a Docker daemon. Image, registry, POSIX, Pages,
security and live checks require their recorded gates; unavailable checks remain
`verification deferred to CI/gates` and cannot authorize release selection.

`tools/smoke_image.py` rehearses both base and explicit non-root split-media layouts
on isolated resources. Each layout must restore the complete archived tree with
numeric ownership and modes and reject an unhealthy candidate before starting the
gateway. The split case archives state and media from the same clean stop. These
synthetic receipts do not establish production database compatibility or live delivery.

Local release verification includes every enabled component: observer uses the
saved base, refresh ID and shared build key; downloads uses its saved Python base
and downloads key. File harnesses mount both shipped nginx configs and an isolated
spool volume. A failed or unavailable harness never qualifies an image.

The Compose stop budget is `120s`; measure graceful shutdown on representative
state and extend it when required. SIGKILL, OOM or an unobserved stop cannot
authorize a consistent backup, even if the container is now stopped.

The image build requires the CMake version and the server's `parameters->version_`
to agree with the saved `BOT_API_VERSION`. Qualification also checks the runtime
privacy-policy label, source/gitlinks and binary hashes; a label alone is not evidence.

## Gateway upload storage and changes

The project-scoped `gateway_client_temp` volume stores buffered request bodies;
it is separate from Bot API state and may contain sensitive uploads. Check free
space and inodes on each backing filesystem, including the Docker Desktop disk
image, and verify that the nginx worker can write there. Size for concurrent
requests as described in [configuration](configuration.md); the volume does
not reserve capacity. Back up Bot API state independently of this spool.

Validate both the Compose model and nginx configuration before applying a change.
Adding the mount requires recreating the gateway and interrupts active uploads:

```sh
docker compose config --quiet
docker compose run --rm --no-deps gateway nginx -t
docker compose up -d --no-deps --force-recreate gateway
docker compose exec gateway nginx -T
```

Inspect the loaded settings privately and check health with synthetic requests.
For rollback, restore the matching previous nginx and Compose files, validate
them and recreate the gateway again; preserve Bot API data. Never use `down -v`
on the working stack. Clean only the precisely identified spool volume when no
requests are active; do not delete live body files manually.

HTTP 411 means the public listener rejected transfer encoding; 429 means upload
rate or concurrency admission was exceeded. Verify the actual source addresses
seen by nginx, the dedicated spool budget and ingress deadlines before raising
limits. Slot limits do not guarantee fairness or a total upload deadline.
HTTP 413 can indicate a body or ingress limit; 408 indicates client body timeout;
504 can indicate upstream timeout. Also check client and external proxy limits,
disk space and inodes. nginx uses `error_log crit`, so ordinary error diagnostics
are suppressed; filter any diagnostic output before sharing it.


## Synthetic gateway upload acceptance

Run from the repository root with Python 3.11+, Docker Compose, Linux containers,
registry access and writable temporary storage. No Telegram credentials are used.

```sh
python3 tools/check_gateway_uploads.py --profile quick --revision candidate --report /tmp/issue4-quick.json
python3 tools/check_gateway_uploads.py --profile full --revision candidate --report /tmp/issue4-full.json
python3 tools/check_gateway_uploads.py --profile slow --revision candidate --report /tmp/issue4-slow.json
python3 tools/check_gateway_uploads.py --profile storage --revision candidate --report /tmp/issue4-storage.json
timeout 2700 python3 tools/check_gateway_uploads.py --profile all --revision candidate --report /tmp/issue4-all.json
```

Replace `candidate` with the tested commit SHA. `quick` (`fast` alias) covers
2/4 MiB uploads and scaled 8 MiB boundaries; it does not prove the real 2048 MiB
limit. `full` transfers real 2048 MiB ±1-byte bodies in both framings and a
2000 MiB file. Reserve at least 10 GiB free on input and Docker filesystems;
sequential scenarios may write much more in total. Both framings in these
transport profiles use the isolated trusted port 82;
public port 80 rejects chunked requests. WSL gateway unit tests also exercise
public admission against a local nginx when installed. `slow` tests actual pauses
over 60 seconds and separate 2-second timeout controls. `storage` checks worker
access, linked/open spool files, block reclamation, disconnect/crash recovery
and ENOSPC on a tiny disposable filesystem. `all` requires every profile.

Use WSL/Linux or CI for complete POSIX regression discovery. Keep the unit and
45-minute integration budgets separate. Reports are synthetic and apply to the
recorded revision, image IDs/digests and config hashes; keep them outside webroot.
NOTRUN, failed scenarios and cleanup failure leave acceptance open. For missing
local prerequisites record `verification deferred to CI/gates`. The mock verifies
gateway transport; real Bot API, Telegram and VPS acceptance remain separate.
See [contributor instructions](../../CONTRIBUTING.md) for clean candidate export,
scoped unit tests, image overrides and emergency cleanup ownership.

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

Before first enabling split storage, create a new empty host directory with
`sudo install -d -m 0770 -o 101 -g 101 ./media`: Compose rejects a missing
root directory. Do not apply this command recursively to an existing cache.

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

The workflow replays the saved snapshot for PR/push and discovers candidates on schedule/dispatch.
Fresh and reused immutable artifacts pass the same fail-closed bundle qualification.
See [qualified release bundle](#qualified-release-bundle) for receipt retention and selection.

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
2. In a maintenance window enable the `docker-compose.nonroot.yml` and `docker-compose.files.yml` overlays, retaining the exact
   qualified image/config and existing `BOTAPI_STATE_SOURCE`. Never copy state/binlogs into media or edit TDLib DB
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

Registry publication does not restart a VPS. Select the complete immutable bundle, preserve the exact
project/overlays and use the [cold backup and rollback runbook](#cold-backup-update-and-data-aware-rollback).

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
python3 tools/observe_runtime.py --project-directory "$PWD" --file docker-compose.yml --file docker-compose.observability.yml --watch
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
`WorkingDirectory=/opt/tg-selfhost-botapi`, `ExecStart=/usr/bin/python3 /opt/tg-selfhost-botapi/tools/observe_runtime.py --project-directory /opt/tg-selfhost-botapi --file docker-compose.yml --file docker-compose.observability.yml --watch`,
`Restart=on-failure`, `RestartSec=5`, `UMask=0077`; run as the trusted Docker-capable
host account and enable with `systemctl enable --now botapi-observation.service`.
Alternatively use a oneshot service with the same command without --watch and a
timer `OnBootSec=30`, `OnUnitActiveSec=30`. Docker access grants host privileges;
never mount its socket in observer. A manual oneshot needs regular renewal.

## Candidate-pair acceptance

The build key covers every observer Python module, JSON schema, health helper and
Docker/Compose/nginx recipe. CI replays the saved digest-pinned Alpine observer base,
loads both exact candidates and checks their shared build-key labels. Reuse still
requires a fresh pair qualification; a missing image is built and the complete
pair is tested before publication. PRs never publish. `build-<key>` and
`observer-build-<key>` are historical tag names; deployment now uses qualified component digests. No latest alias is promoted
only after gates and their promotion is not atomic.

Run the isolated gate explicitly with `python3 tools/check_observability.py
--botapi-image botapi-candidate:check --observer-image observer-candidate:check --nginx-image nginx:alpine@sha256:<qualified-gateway-digest>`.
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

Use the complete [cold backup, update and rollback procedure](#cold-backup-update-and-data-aware-rollback).
Include the observability overlay only when installed and retain the exact saved
project/files/env invocation. Recreate observer with its namespace owner and
restore state/media/config together when rollback requires the previous snapshot.

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


## Shell export regression gate

Run the issue #8 matrix on Linux/WSL as a non-root user with Bash 4+, Python
3.11+, Node 24+, jq, curl and openssl:

```sh
PYTHONPATH=.:tools python3 -m unittest discover -s tools -p 'test_issue8_shell_safety.py' -v
python3 tools/check_migration_checkout.py
python3 tools/check_migration_safety.py --require-posix
```

The suite uses synthetic `.invalid` inputs, an offline curl executable and a
separate loopback HTTP peer. Captures remain in private temporary directories.
The required gate fails on skips or missing runtimes. Windows skips and local
NOTRUN results mean verification deferred to CI/gates. After merge, check the
published root migrator URL and its byte equality separately; branch tests do
not establish deployment or real-bot delivery.

## Image identity and dependency evidence

Readiness accepts one bounded 404 JSON response from the root handler and never
authorizes a bot. Startup dependencies apply at creation time. Measure SIGTERM
shutdown on representative state; 120 seconds is an initial budget. SIGKILL,
OOM, a stop timeout or unobserved termination prevents a consistent-backup claim.

OCI `version` and `revision` identify the official server version and commit.
The build verifies the unpatched CMake version, checkout SHA and recursive gitlinks.
Wrapper and TDLib revisions are separate labels. Runtime evidence under
`/usr/share/tg-selfhost-botapi/` records the actual build/runtime package inventories,
refresh ID, patch/source identity, binary hash, link command and linked libraries.
The observer consumes the same APK refresh ID and records its own inventory.
This is a bounded #23 interface; full dependency refresh qualification remains a CI gate.
`apk --no-cache` alone does not invalidate Docker layers. Mutable package repositories
mean rebuilding an old key does not promise byte-identical output: retain the actual artifacts.

## Qualified release bundle

`image-release.lock.json` deliberately has `selected_release: null` until all gates
produce evidence. Discovery does not select or qualify a release. Runtime image
qualification, registry checks, Pages, native platform and restore checks are
**verification deferred to CI/gates** when unavailable locally. Code completion
does not establish a PASS. Native ARM64 and a controlled live Telegram smoke remain NOTRUN.

The existing workflow resolves once, builds or pulls Bot API/observer by immutable
digest, checks both through the same current qualification gates, and publishes
the inspected config without rebuilding. Registry auth/timeout/outage stops the
run; only an explicit manifest-not-found permits a new artifact. Downloads uses
its own recipe key. Every component is pulled back after publication and its
config/rootfs is compared; the Bot API binary, labels and inventories are checked again.
Partial publication never selects a release, and no latest alias is promoted.

`tools/qualify_release.py qualify --inputs /private/resolved.json --directory /private/evidence`
requires the native Linux test-only sender target, runtime/restore tests, APK
refresh tests, observer/downloads and gateway checks. The C++ adapter executes
production WebhookActor objects shared with the server; a nonce, one exact
User-Agent, queue acknowledgement and wrong-UA/error/timeout controls are required.
The adapter is absent from the final production image. Root readiness tests no bot.

After successful publication, archive the complete source snapshot, resolved inputs,
receipt and referenced evidence outside checkout/webroot for the rollback retention
period. Actions artifacts are a transfer mechanism, not the durable archive.
Explicit selection uses `tools/release_contract.py --inputs-file /private/source-inputs.json
--select-receipt /private/receipt.json --botapi-image <qualified-image@sha256:digest>`
(on one shell line). It verifies receipt identity, required gate records and component identities and exports
`selected.env`; deployment remains a separate operator action. Keep previous
images and evidence until restoration is rehearsed and a following release is accepted.

## Cold backup, update and data-aware rollback

Prepare the candidate and retain the previous immutable bundle and its complete
evidence **before** downtime. Preserve the installation's project name, project
directory, env files, profiles and ordered overlays. Every pull/config/stop/up
command must use that exact invocation. For example, in Bash:

```sh
umask 077
CHECKOUT=/srv/tg-selfhost-botapi
PRIVATE=/secure/botapi-update
# Use this installation's saved values; append its actual nonroot/files/downloads
# and secrets overlays in their original order. Do not include a build overlay.
OVERLAYS=(-f "$CHECKOUT/docker-compose.yml")
# Add the actual installed overlays to OVERLAYS, secrets last.
SERVICES=(botapi gateway)
# SERVICES+=(observer)  # only with docker-compose.observability.yml
# SERVICES+=(downloads) # only when installed
dc() {
  local selection=$1; shift
  docker compose -p saved-project --project-directory "$CHECKOUT" \
    --env-file "$PRIVATE/installation.env" --env-file "$selection" "${OVERLAYS[@]}" "$@"
}
dc "$PRIVATE/old.env" config --format json > "$PRIVATE/old-compose.json"
dc "$PRIVATE/new.env" pull "${SERVICES[@]}"
# Pull downloads as well when installed; never put bot tokens in argv.
```

`old.env` and `new.env` contain exact bundle refs from archived receipts. Save
private env/secrets/config, migration authority and `binding.key`, observer
registry/runtime inputs, image IDs and all source/qualification receipts.
Inventory actual container mounts and named volumes: base `./data` is only one
layout. Nonroot uses configured state/temp sources; files adds a separate media
root and per-bot downloads mounts. Record numeric UID/GID, modes and storage
mapping. Temp/cache is disposable only after proving it contains no durable
state; do not discard a work/temp directory that is actually shared.

Quiesce API clients, pollers, schedulers, migration jobs and external writers;
close ingress and wait for in-flight uploads/downloads. Stop gateway, optional
downloads, observer and finally Bot API with the saved invocation. Observe Docker
SIGTERM/die events and inspect exit/OOM state; measure elapsed shutdown against
`stop_grace_period`. SIGKILL, OOM, timeout or missing evidence means UNKNOWN,
not a consistent backup. Do not create a cold-backup claim after forced stop.

Only while every writer is stopped, take one snapshot of **all** durable roots
and private configuration, with one snapshot ID. Example for each actual root:

```sh
sudo tar --numeric-owner --acls --xattrs -cpf "$PRIVATE/state.tar" -C "$STATE_SOURCE" .
sha256sum "$PRIVATE/state.tar" > "$PRIVATE/state.tar.sha256"
sha256sum -c "$PRIVATE/state.tar.sha256"
```

Repeat for media and private journals/config/secrets; include hidden files,
`tqueue.binlog` and `webhooks_db.binlog` when present. Store archives outside
checkout/Pages/webroot. Check free space, archive readability, checksums and
numeric ownership. `tools/check_issue12_restore.py` validates a private manifest
with one snapshot ID, storage mapping, release/config hashes and checksums for
state/private plus media for nonroot-split. It rejects incomplete or mixed sets;
a synthetic manifest test is not proof of production database compatibility.
Do not tar a running database or combine snapshots from different times.

Start the new bundle using the same configuration, identity, local mode and
mounts. Use `--no-build`, recreate Bot API and observer together, wait for backend
health, then recreate gateway and any downloads. A botapi-only `--no-deps` update
leaves observer attached to the old network namespace and is insufficient.

```sh
dc "$PRIVATE/new.env" up -d --no-build --force-recreate --wait --wait-timeout 180 "${SERVICES[@]}"
# Recreate installed downloads with the same --no-build invocation.
```

Before ingress opens, compare running IDs/digests, OCI/source/binary version,
mounts/UID/GID, Docker health, token-free root directly and through gateway, private
management live/ready and fresh doctor deployment evidence. Re-run the controlled
test-bot/receiver smoke for availability, update delivery, one actual User-Agent
and acknowledgement. Root health does not establish Telegram authorization.
Never automatically alter a production webhook or erase migration history.

On failure, quiesce and stop again, retain the failed new state separately, and
restore the **previous bundle/config plus the entire pre-update snapshot** into
fresh prepared paths with original numeric ownership/modes. Verify checksums and
full tree contents before startup; do not overlay old files on a new database.
Recreate the previous complete service set and repeat identity/health/doctor and
controlled availability/UA smoke. An old image on new state is unsafe without
separate compatibility evidence. Forward recovery requires its own evidence.

Restore loses changes after the backup and cannot undo external Telegram
acknowledgements. Record RPO, downtime and measured shutdown/restore durations;
exactly-once, external-queue restoration and zero downtime are not promised.
Do not use drop-pending to repair a failed update. Rehearse both base and
nonroot+split-media layouts on separate disposable resources, including stale
evidence, insufficient space, interrupted stop/backup and mixed snapshots.
The supplied no-bot runtime rehearsal exercises a base snapshot; production and
split-layout rehearsal, representative timings and live bot smoke remain
**verification deferred to CI/gates** or a manual deployment gate until executed.
