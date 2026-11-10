---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The build-input resolver uses a UTC-day apk refresh window and the generation in
`tools/apk_policy.json`. Increase that generation in a commit for an urgent
refresh within the same day; do not decrease it. This is a build identity, not
a package snapshot or proof of reproducibility. The window changes at 00:00 UTC
and is captured once; crossing midnight during compilation never rewrites inputs.

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

The build key covers the resolved revisions/digests and the recipe, entrypoint,
patch, dependency policy, capture/validation tools and image tests. An existing
build is pulled by digest and qualified again before reuse. An ambiguous registry
response stops the run; only confirmed absence selects a new compilation.

For a new build it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Compiles the entire server.
3. Runs `--version`, checks the header string in the binary and validates entrypoint syntax.
4. Checks package/compile evidence and the warm-cache gate, saves artifacts,
   then publishes and verifies a unique candidate digest before assigning
   `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>` and promoting `latest`.

Failed checks leave the previously published `latest` in place. Pull requests do
not publish. A binary string check is not a live webhook-delivery test.

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
python3 tools/image_inputs.py --json-out .build-inputs.json --build-env-out .env.build
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml stop botapi
# Back up ./data and private configuration before replacing the binary.
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
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
  --env-file /private/installation.env --env-file /private/stack/.env.build --project-directory /private/stack \
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

### APK refresh identity

The build inputs use a UTC calendar-day refresh window and a generation from `tools/apk_policy.json`. Increase generation in a commit for an emergency refresh within the same day. The scheduled check runs at 23:37 UTC; a delayed or failed run delays the refresh. This policy includes ordinary package updates, not only security fixes. Matching build keys do not guarantee reproducible bytes: package repositories can change within a window. The resolver freezes one inputs snapshot per invocation; a new window changes the key even when source and base digest do not change. Both dependency stages consume this ID before installation.

### APK installation stages

Both independent targets `build-deps` and `runtime-deps` require `APK_REFRESH_ID`
before their installation RUN. Each upgrades all installed packages, then installs
the dependencies from the stable Alpine 3.22 branch with signatures enabled.
`apk --no-cache` does not disable Docker layer caching: the refresh argument
invalidates both installation layers. Raw installed database, world, repositories,
apk version, architecture, Alpine release and refresh ID are retained under
`/usr/share/tg-selfhost-botapi/build/` and `runtime/` in the final image.


### Binary and dependency evidence

Build evidence retains the actual source/submodule revisions, compiler/CMake/linker
versions and Release configuration, the final target link command and map,
pre-strip and installed post-strip SHA256, ELF NEEDED entries, and the hashes and
package ownership of static inputs and resolved dynamic libraries. Builder-only
Python/binutils are absent from runtime. Extract and validate without credentials:
`python3 tools/image_metadata.py --image IMAGE --inputs inputs.json --output receipt.json`.
Missing evidence, a different binary, refresh mismatch or unowned linked archives
reject qualification. The external receipt binds inventories to the image config;
the internal compile record does not include its own hash or a registry digest.


### Candidate qualification and reuse

CI resolves one frozen JSON snapshot. Registry authentication/network errors stop
the run; only confirmed manifest absence permits compilation. Reuse pulls by digest
and repeats metadata validation and smoke (`--version`, header string, entrypoint
syntax). PRs compile locally without registry writes. Unit, Compose, metadata,
smoke and the explicit cache regression must PASS before publication. Existing
build tags cannot be replaced by different content. A unique candidate is pushed
without recompilation, its registry config is checked, and artifacts are uploaded
before digest-based latest promotion and readback. Default-branch drift and newer
latest refresh identities reject stale reruns. Crossing UTC midnight preserves the
frozen inputs. Evidence artifacts retain for 30 days; in-image evidence lasts as
long as the image digest. Missing legacy evidence requires a new window/generation.


### Prepare every local rebuild

Generate `.env.build` and `.build-inputs.json` with the resolver immediately before
each local build; pass both env files as shown above. The file is not refreshed by
`up --build`. For an urgent update increase `generation` in `tools/apk_policy.json`,
commit it and resolve again. Config/doctor do not trigger network resolution.


### Signed warm-cache regression

CI explicitly runs `tools/check_apk_refresh.py` against the frozen inputs; unit
discovery never invokes Docker. The restored runner uses an isolated Dockerfile
copy (documented fallback) with unchanged production upgrade/add/capture RUNs,
preinstalling a signed synthetic v1 package before refresh. Repository URL,
source/base and context bytes remain fixed. A/A proves both cached installations;
after serving v2 the old-ID control stays v1 and the new generation upgrades both
branches. Dynamic and rebuilt static consumers must return v2. Separate negative
variants remove refresh from each installation and must expose stale evidence.
The scoped builder uses 2 CPUs/3 GiB and removes only its own resources. No cache
purge/cache bypass is used. Saved logs, inventory versions, hashes and receipts
are synthetic regression evidence; they establish no particular CVE/VPS status.


### Reproducibility and scanner triage

Mutable stable repositories can change during the same UTC window. The build key
identifies selected inputs and refresh policy; the registry digest identifies the
actual image. Matching keys do not promise bit-for-bit reproducibility. A failed
or delayed schedule delays updates, so the policy does not guarantee a fix within
24 hours. Gateway `nginx:alpine` has an independent dependency policy; this work
does not certify the entire stack or change state compatibility.

Investigate each scanner finding against the exact digest, package name/version/
Alpine revision/architecture, advisory and backport status, actual static/dynamic
linkage, scanner version and database timestamp. Record affected, fixed,
not-applicable or UNKNOWN with supporting evidence. A runtime package scan alone
cannot dismiss a statically linked vulnerability. A confirmed applicable finding
requires update/rebuild and all gates, or an explicitly justified exception;
unreviewed findings remain unresolved and block promotion. Scanner status is
NOTRUN unless a scan was performed; absent output is never a clean scan. No
universal scanner is introduced by #23.

For missing legacy evidence or a build-tag collision, increase generation and
resolve a new snapshot. Do not overwrite the existing build tag. An UNKNOWN latest
readback requires registry inspection; no automatic rollback is claimed. Registry
publication, synthetic regression, actual-image smoke and production are separate
outcomes. Dependency refresh does not require bot migration or token-bearing calls.
