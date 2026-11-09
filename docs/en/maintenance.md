---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

The build key covers the resolved source/base/platform identities, qualification
policy and all build/verification bytes. One saved snapshot is shared by all jobs.
Existing tags require retained trusted proof and new native qualification. Only a
confirmed registry 404 permits a fresh build; auth/network errors stop release.

For a new build it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Compiles the entire server.
3. On each native CPU, checks ELF/config/version, normal entrypoint/gateway and the
   production webhook sender with a wrong-UA negative control.
4. Transfers the exact runtime/sender archives to one publisher, checks the full
   two-platform index, then assigns `build-<K>` and `latest` from its digest.

Failures before promotion leave the previous `latest` intact. A lost write
response is UNKNOWN until registry readback reconciles it. Pull requests do not
publish. Component sender qualification does not establish Telegram delivery.

The workflow needs to be on the default branch before the schedule/publication
can work. GHCR writes use `GITHUB_TOKEN` with `packages: write`. Configure package
visibility or client authentication after the first publication.

## Update an installation

Registry publication does not restart your VPS. Select a tested tag/digest with
`BOTAPI_IMAGE` in `.env`, then:

```sh
docker compose stop botapi
# Make a consistent backup of ./data and private configuration here.
docker compose pull botapi
docker compose up -d --no-deps botapi
docker compose logs --tail=100 botapi
```

For a locally built installation, use the build override consistently:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop botapi
# Back up ./data and private configuration before replacing the binary.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
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


## Multi-platform inputs

The image input snapshot records exactly `linux/amd64` and `linux/arm64`, the source revision, Alpine index and platform children, recipe bytes and qualification policy. Save it with `python3 tools/image_inputs.py --output snapshot.json`; validate saved inputs with `--input snapshot.json --snapshot-hash <hash>`. JSON is transferred as an artifact, while CLI outputs remain scalar key=value. Cache reuse is distinct from release qualification. These inputs alone do not prove a released ARM64 image.

`tools/multiarch_verify.py` validates ELF64 little-endian machine IDs 62/183, the exact User-Agent marker, source/base/K/policy labels, and remote child/config digest binding. A release index must contain exactly the two runnable platforms; extra children and attestations are rejected. Config ID, archive SHA256, child digest and index digest are separate identities. Offline fixture success does not establish native execution.

Native qualification checks host and daemon CPU, version and ELF, then normal entrypoint ownership and exact direct/gateway `404` JSON (`ok:false`, `error_code:404`, `description:Not Found`) on an internal network. The sender-test target shares the runtime production objects: its loopback receiver requires one exact User-Agent, nonce POST and queue acknowledgement, followed by a failing wrong-UA control. Synthetic credentials and temporary resources are used. Sender images are retained by digest for reuse. Component qualification is separate from Telegram end-to-end delivery.

The image workflow prepares one snapshot and requires two independent native jobs: `ubuntu-24.04` for linux/amd64 and `ubuntu-24.04-arm` for linux/arm64. Each fresh runtime is built cold with two build jobs and a 180-minute budget; QEMU is not a release fallback. Matrix jobs have read-only package access. Runner availability and the first successful ARM64 release still require CI evidence.

Only the publisher has registry write permission. It validates both native receipts and archives, loads the exact runtime and sender images, rechecks ELF/config identities, pushes unique candidate refs and checks the full index before release tags. `build-<K>` is a complete immutable index; `latest` is updated once from that index digest. Existing K requires retained successful default-branch Actions compilation evidence plus new native runtime/sender checks; missing proof, auth errors or timeouts stop release. Lost write responses require readback reconciliation. Qualification receipts are retained for 90 days, archives for two days; the sender image is retained by registry digest for reuse. Current default-branch HEAD is checked before writes. A GHCR release does not deploy a VPS.

Offline acceptance: 51 scoped tests (including fault injection and patch regression), both synthetic Compose configurations and `git diff --check` passed locally. Receipts retain source revision, patch hash, clean submodule identities and rootfs; raw descriptor sizes are checked. Native cold/warm builds, registry integration/reuse/promotion, fresh Jekyll and post-merge release readback are NOTRUN: `verification deferred to CI/gates` (release readback: `verification deferred to CI/post-merge`). Local Docker build-check was denied access to its external buildx lock and was not retried.
