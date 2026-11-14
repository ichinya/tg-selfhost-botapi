---
title: Migration
translation: /docs/ru/migration.html
---

# Migration

Use the complete reviewed checkout on Linux/WSL with Python 3.11+. The public [migration entry](../../tg_selfhost_botapi_migrator.html) opens instructions for the same-origin loopback helper. It accepts no credentials. The Bash entry is `migrate_off_to_self.sh`; Python owns all sequencing, private state and recovery. A shell downloaded alone fails before network use.

## Private inputs and authority

Prepare an operator-owned directory outside the checkout, Bot API state/media/temp and webroot. Directory mode is 0700; token, profile, helper config, bootstrap and provider configuration files use 0600. Secrets are file contents or environment values, never positional arguments. No implicit cwd dotenv is executed. An explicit `--env-file` is parsed as data; expansion and duplicate keys are rejected. CLI > process environment > selected file.

```sh
export MIGRATION_STATE_DIR=/private/migration-state
export BOT_TOKEN_FILE=/private/bot-token
export OLD_BOT_URL=https://api.telegram.org
export SELF_BOT_URL=http://127.0.0.1:18080
export MIGRATION_ACTION=polling
export MIGRATION_EVIDENCE_FILE=/private/deployment.json
export MIGRATION_TRUST_FILE=/private/trust.json
python3 tools/migration_cli.py plan --operation example
python3 tools/migration_cli.py status --operation example
python3 tools/migration_cli.py export --operation example
```

Planning reserves the operation and checks token-free infrastructure readiness. Without a signed quiescence receipt it does not observe the source bot. Review the returned digest; then collect a fresh independent quiescence receipt and explicitly apply:

```sh
python3 tools/migration_cli.py apply --operation example --confirm-digest "$REVIEWED_DIGEST" --quiescence-file /private/quiescence.json
python3 tools/migration_cli.py status --operation example
python3 tools/migration_cli.py resume --operation example --quiescence-file /private/quiescence.json --endpoint-change-file /private/endpoint.json --application-start-file /private/start.json
```

Endpoint/start receipts are collected after the relevant checkpoints, never pre-signed. For local-to-local also supply `--state-transfer-file` after confirmed close and stopped transfer. For changed inputs make a new plan; only untouched plans may be explicitly superseded. Status/export are offline saved-state operations; `status --refresh` is an explicit phase-aware network observation.

## Directions and actions

| Direction | Required sequence |
| --- | --- |
| cloud_to_local | target readiness; quiesce/snapshot; source deleteWebhook(false), logOut; target authorization/configuration; endpoint change; controlled start |
| local_to_local | deleteWebhook(false), close; stopped bot-subtree transfer receipt; target authorization/configuration; endpoint/start |
| local_to_cloud | queue limitation acknowledgement, cloud target and cooldown evidence; detach, then target after not-before |
| webhook_only | same source/target; configuration/readback only; no detach/state transfer |

Set `--direction` explicitly. local_to_cloud requires `--target-local-mode false --queue-limitation-ack`; cooldown must be independently verified. close/logOut can be refused by upstream timing rules. A per-bot state transfer is different from media mapping; do not copy shared binlogs into another active server. Preserve both safe file contracts described in [configuration](configuration.html).

Actions are preserve, set and polling. Empty URL never selects polling. set requires a URL; polling configures target deleteWebhook and verifies empty URL. Drop defaults false; source delete always uses false. Explicit drop belongs only to target_configure and cannot be retried blindly after UNKNOWN. Full and URL-only profiles have different guarantees.

## Helper

Private helper JSON contains state_dir, allowed_endpoints, evidence_file, trust_file and fixture=false; optional forbidden_state_roots excludes local mount/webroot paths. The evidence_file uses the existing deployment schema and must be refreshed by a trusted operator. Provision provider keys independently of the journal binding key.

```sh
python3 tools/migration_helper.py --config /private/helper.json --bootstrap-file /private/bootstrap.txt
```

Open the printed http://127.0.0.1 loopback origin and enter the one-time bootstrap code from the private file. Host/Origin/session/CSRF checks remain mandatory; Pages never requests loopback access and wildcard CORS is not enabled. Keep only operation/digest in browser session storage. After a lost response or reload, read status of the existing operation. Outcomes for service readiness, migration, configuration and delivery are displayed independently.

## Failures and bounded transport

The canonical stdlib Client defaults to 5s connect, 10s read, 20s total with a bounded body. Redirects, proxy inheritance and automatic retries are disabled. Typed HTTP/API/retry metadata is saved without raw descriptions. A confirmed 429 yields WAITING/not_before (exit 3); ambiguous mutation results yield UNKNOWN/BLOCKED. Intent is durable before send. Resume never repeats uncertain logOut/close/drop based on time or empty webhook. Independent server/transport audit is required. Delivery uses a separate trusted receiver/consumer receipt after controlled start.

Historical raw-curl diagnostics under logs/migration are unverified legacy inputs (intent.json, receipt.json, summary.json, transport-error.txt). They cannot be imported as successful engine state. They remain private and are excluded from Pages. Raw retention, if enabled for historical tools, needs a bounded private retention policy; generated Bash now only refers to canonical operations. Old MIGRATION_CONNECT_TIMEOUT/MIGRATION_REQUEST_DEADLINE settings (1..60 / 1..300) describe that retired raw-curl path, not current engine configuration.

### Sealed export
Export uses the existing operation, digest and `MIGRATION_STATE_DIR`; it never emits an independent curl protocol. Input changes require a new plan. Secrets belong in private runtime inputs; never copy tokens or certificate contents into an export. Legacy browser execution is replaced by the helper entry in this release.

### Explicit full webhook input
Choose preserve/set/polling explicitly. A full private profile has all fields: mode, url, secret_token, certificate_pem, ip_address, allowed_updates, max_connections. Use JSON null for intentionally absent secret/certificate/pinned IP; missing fields mean unknown and are rejected. Empty updates and an explicit connection limit are deliberate choices. Certificate contents are sent as multipart InputFile. URL-only is a limited scope.
Full preserve additionally requires a fresh signed quiescence receipt from an independent configuration auditor with original_config_verified=true and the exact plan profile_fingerprint. Readback cannot prove the old secret. Without that audit, full preserve blocks before detach; use the existing trusted provider boundary. Configuration readback and actual secret/header delivery are separate results.

### Recovery authority
Keep the private journal outside state/media/webroot. The canonical engine reserves a per-bot operation before bot-bearing observations, records intent before mutation and preserves UNKNOWN after ambiguous transport. Resume never repeats unknown logOut/close/drop. Independent audit evidence is required; elapsed time or empty webhook is insufficient. Target authorization waits for confirmed detach and, for local-to-local, a verified stopped bot-subtree transfer. Readiness, migration, configuration and delivery remain separate outcomes. Private evidence reads reject special files and concurrent replacement.

### Bash entry and legacy recovery
Use the complete reviewed checkout with Python 3.11+ on Linux/WSL. `bash migrate_off_to_self.sh plan|apply|status|resume|reconcile|export` delegates to tools/migration_cli.py. Explicit `--operation`, MIGRATION_STATE_DIR and action are required; old SELF_BOT_URL/TELEGRAM_BOT_URL and WEBHOOK_URL/WEB_HOOK aliases are read as data. Ambiguous positional tokens are rejected before network use. A separately downloaded shell fails before doing work if runtime dependencies are missing.
Old wp_migration_main journals are historical, unverified input. Stop application writers, inspect the last confirmed effect independently and reconcile manually before planning; do not rerun logOut to discover what happened.

### Published migrator URL
The existing tg_selfhost_botapi_migrator.html URL is a static bilingual entry. It does not accept tokens or call Bot API/localhost. Run the helper from the same checkout; open its loopback URL as a separate page. The helper serves the complete four-direction, three-action UI on one origin with private bootstrap, session and CSRF checks. After a lost response, read status of the same operation before resuming. Form edits invalidate digest confirmation. Public URL compatibility does not preserve legacy standalone execution.

### Bounded Compose checkpoints
`python3 tools/migration_compose_provider.py --config /private/provider.json --state-dir /private/migration-state --operation example --kind quiescence` reads only explicitly allowlisted full container IDs. Private config selects provider/key_hex, fixture, project, containers (service/image IDs), application, endpoint, endpoint_variable and target_fingerprint. Provision the same independent key in TrustedReceipts for permitted kinds. Collect each receipt at its actual phase; do not pre-sign a whole migration. Endpoint change requires a stopped application with matching effective environment; controlled start checks generation time against target verification and endpoint change.
The allowlist must include every writer. The collector cannot discover unknown external writers, attest an old secret, prove lost logOut/close, move state or certify delivery. Those boundaries remain BLOCKED without their independent auditors. Never mount the Docker socket into the browser, gateway or helper.

### Final acceptance status
The shipped root entry and regenerated adapters now use the canonical authority. CI/POSIX, image, native ARM64, browser/rendered-site, full upload, cold restore, VPS and real Telegram gates are NOTRUN in this execution. Retain operation/digest and exact image identities with each future receipt. No existing production bot has been migrated or verified by these offline checks.

Historical diagnostic labels CONFIRMED_REJECTION and NOT_SENT describe the retired raw-curl projection. The canonical engine keeps typed failed/waiting/unknown outcomes. getWebhookInfo can verify observable profile fields but cannot retrieve secret_token.
