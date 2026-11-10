---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

The build key covers the resolved revisions/digests and the recipe, entrypoint,
patch and image tests. If the corresponding published build exists, compilation
is skipped. If registry inspection cannot confirm it, the pipeline rebuilds.

For a new build it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Compiles the entire server.
3. Runs `--version`, checks the header string in the binary and validates entrypoint syntax.
4. Publishes `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>` and promotes `latest`.

Failed checks leave the previously published `latest` in place. Pull requests do
not publish. A binary string check is not a live webhook-delivery test.

The workflow needs to be on the default branch before the schedule/publication
can work. GHCR writes use `GITHUB_TOKEN` with `packages: write`. Configure package
visibility or client authentication after the first publication.

## Update an installation

Registry publication does not restart your VPS. Select a tested tag/digest with
`BOTAPI_IMAGE` and the matching `OBSERVER_IMAGE` in `.env`, then:

```sh
docker compose stop observer botapi
# Make a consistent backup of ./data and private configuration here.
docker compose pull botapi observer gateway
docker compose up -d --force-recreate botapi observer gateway
docker compose logs --tail=100 botapi
```

For a locally built installation, use the build override consistently:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop observer botapi
# Back up ./data and private configuration before replacing the binary.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi observer
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --force-recreate botapi observer gateway
```

Preserve `./data`, ownership `101:101`, the API endpoint and local-mode settings.
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
