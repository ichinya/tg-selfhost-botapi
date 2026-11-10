---
title: Migration
translation: /docs/ru/migration.html
---

# Migration

The retained HTML URL now loads a single ES module and uses the local helper.
It makes no direct Bot API or arbitrary webhook HEAD requests. Browser refresh
restores only the saved ID/digest and reads status. Form changes create a new
draft; old asynchronous responses cannot replace it. A lost apply response means
the UI does not know the outcome: read the same operation's durable status.

## Executor contract

The version 2 migration contract uses an immutable operation ID and digest,
keyed endpoint/token/profile commitments and a single target-only drop step.
Version 1 plans are rejected. Runtime secrets and URLs are supplied separately;
they are not part of the public plan. A confirmed step is historical evidence,
while a lost response remains UNKNOWN until permitted reconciliation proves it.

The shared registry describes Cloud → Local (delete without drop, logOut,
authorize, configure), Local → Local (delete, close, external state transfer,
authorize, configure), Local → Cloud (delete, logOut, cooldown, authorize,
configure) and Webhook only (configure). Each dependency must be confirmed.
Local → Cloud requires acknowledgement of weaker queue continuity. Full typed
profiles and explicit `url_only`/polling scope are bound to the sealed plan.

The executor reserves an operation before source observations. It never calls
the target with a bot token before a confirmed detach and, for Local → Local,
a verified transfer receipt. Transfer is external: retain the source backup;
bind matching manifest commitments, close attempt, deployments, UID/GID/layout
and absence of writers. Without a trusted provider the checkpoint stays BLOCKED.
`close` 429 is WAITING with `not_before`; it is not an automatic retry loop.
Cloud cooldown is an explicit input requiring evidence, not a guessed hostname.
After detach a target failure is PARTIAL. Readiness, migration, webhook settings
and delivery have separate outcomes; delivery starts as NOTRUN. A full preserve
profile without verifiable original private settings fails closed before detach.

`status` is offline. `status --refresh` and `resume` reconcile only observations
permitted by the current phase. UNKNOWN logOut/close never triggers bot-bearing
probes on either side. UNKNOWN drop or hidden secret/certificate configuration
requires independent evidence. Real checkpoints/effects/delivery require receipts
signed by an explicitly configured, independent audit provider; JSON fields or
an operator checkbox alone are insufficient. The first release supplies the HMAC
provider boundary, not a platform-specific audit collector. Fixture trust is
restricted to fixture operations. Historical confirmed receipts survive drift.

## Common CLI and export

Run Python 3.11+ on Linux/WSL. Supply `BOT_TOKEN` or `BOT_TOKEN_FILE`, explicit
`OLD_BOT_URL`, `SELF_BOT_URL`, `MIGRATION_ACTION` and private deployment evidence.
The new interface never infers polling/preserve from an empty webhook.
CLI flags override process environment, which overrides an explicit `--env-file`.
Env files are parsed as data with an allowlist; shell expansion is rejected.
The Bash filename remains compatible and forwards subcommands to the same CLI.
On `--option` calls positional token/target/webhook arguments are rejected
without echoing values.
Use process environment or an explicitly selected private input file.
Legacy invocation prints a sealed plan and requires a separate apply with its
digest. It never performs the old independent curl sequence.

```sh
python3 tools/migration_cli.py plan --operation move-01 --action polling
python3 tools/migration_cli.py status --operation move-01
python3 tools/migration_cli.py apply --operation move-01 --confirm-digest PLAN_DIGEST --quiescence-file "$QUIESCENCE_FILE"
python3 tools/migration_cli.py resume --operation move-01 --endpoint-change-file "$ENDPOINT_RECEIPT" --application-start-file "$START_RECEIPT"
python3 tools/migration_cli.py export --operation move-01
```

Exit codes: 0 handled (inspect payload outcome), 1 proven step failure,
2 UNKNOWN/BLOCKED/checkpoint required, 3 WAITING, 4 invalid input/state.
Export preserves ID/digest and references `MIGRATION_STATE_DIR`; it cannot create
a second authority. Keep profile/certificate inputs in a private `--profile-file`.

The root helper limits each request with `MIGRATION_CONNECT_TIMEOUT` and
`MIGRATION_REQUEST_DEADLINE`; see [configuration](configuration.md) for defaults,
limits and precedence. The token-free probe has a maximum deadline of 10 seconds.

A migration changes the Bot API endpoint used by your application and may also
change its webhook. Know the old endpoint before starting. Do not use cloud
`getMe` as a neutral discovery request: token-bearing calls can affect sessions.

Stop the application or background worker that keeps calling the old API.
Prepare the new service without authorizing this bot, back up state and record
the webhook profile. `getWebhookInfo` does not return the previous
`secret_token`; keep it in your own configuration.

## Choose a scenario

| Scenario | Approach |
| --- | --- |
| Same Bot API, different webhook | Change the webhook and verify the actual result; no server migration |
| Telegram cloud → local | Call cloud `logOut` before using the local API |
| Local → local | Follow the official state-transfer procedure below |
| Local → cloud | Log out on the old local server before switching; account for queued updates and cloud availability |

The authoritative procedure is the [official server README](https://github.com/tdlib/telegram-bot-api#moving-a-bot-to-a-local-server).
The cloud API documents [logOut](https://core.telegram.org/bots/api#logout) and
[close](https://core.telegram.org/bots/api#close). After leaving the cloud,
immediate return to the cloud is subject to Telegram's ten-minute restriction.

### Cloud → local

1. Confirm the target infrastructure is reachable and correctly configured.
2. Stop the application using the cloud endpoint.
3. Record the webhook profile and choose how to handle queued updates.
4. Call `logOut` on the cloud API, then switch the application's Bot API endpoint.
5. Set the complete webhook profile on the target, or explicitly choose polling.
6. Check actual webhook configuration, delivery errors and a test update before restarting normal traffic.

### Local → local with state transfer

The official procedure for moving a bot’s state is `deleteWebhook`, then `close` on
the old server, followed by moving the bot's state subdirectory (identified by its
user ID) to the new server's working directory. Resume requests on the new server
after the transfer. Handle a `retry_after` response from `close` before proceeding.

Use a consistent backup, preserve ownership and paths, and prevent simultaneous
use of the same state. `drop_pending_updates=false` alone does not transfer state
or guarantee continuity.

The shared `tqueue.binlog` and `webhooks_db.binlog` are outside per-bot directories. Moving one bot directory does not prove its local queue is preserved. Drain or explicitly account for backlog; merging shared binlogs into a running target with other bots is unsupported. `drop_pending_updates=false` is not a preservation guarantee.

### Local → cloud

Drain backlog or explicitly accept its loss, stop all old API clients, save the
profile, detach the webhook and obtain successful local `logOut` before any cloud
request. Local `logOut` can clear the update queue even if webhook deletion used
`drop_pending_updates=false`. The cloud cannot import local state. Once cloud
access is available, call cloud `getMe`, restore the profile or explicit polling,
and verify delivery. Stop on errors or unknown results.

This logout-first recipe is an inference from the upstream implementation and
the general moving rules, not a separate verbatim upstream local-to-cloud guide.
The cloud's ten-minute return restriction after cloud `logOut` and the local
`close` 429 window are different constraints. The browser supplies a manual plan
for this direction; it does not execute it.

## Adapter compatibility

Use `bash tools/migration_executor.sh plan/apply/status/resume/reconcile/export ...` with the
same flags as Python. There are no curl/jq requirements for migration itself.
The repository `.env` and `.env.example` are Compose configuration only.
Migration inputs belong in process environment or a separate private file
selected with `--env-file`; the executor path never reads `.env` automatically.
Environment values take precedence. An empty webhook requires an explicit action
even in legacy mode. Use `BOT_TOKEN` or `BOT_TOKEN_FILE`; positional credentials
are rejected on `--option` invocations. The separate root `migrate_off_to_self.sh` retains the
[standalone helper](#bash-helper) contract. The two runtimes have separate state and locks. Legacy mode prints the plan and
returns code 2 for separate digest confirmation; it does not auto-apply.

## Browser workflow

[The retained migrator URL](../../tg_selfhost_botapi_migrator.html) is an entry
screen on Pages. [Start the helper](getting-started.md#local-migration-ui), connect
with the private pairing-file code, choose direction/action/mode and submit Plan. Review the
ID/digest, profile scope, drop policy and ordered steps. Real plan preparation can
seal a reviewable plan without source observations; apply needs fresh signed
quiescence. Re-enter the reviewed digest and submit the required provider receipts.
After a timeout, use Status for the same operation before Resume. Refresh is an
explicit online action; browser refresh automatically reads only saved status.

The helper supports one operator on one host. UI, CLI and export share the same
private authority. Multiple independent state roots are outside this guarantee.
Native Windows/state on Windows-mounted WSL drives are unsupported. Managed
Docker diagnostics are explicit write probes. Unmanaged deployment evidence is
an operator-supplied attestation with TTL, not automatic verification.

For real `webhook_only` operations against the official cloud, required local deployment evidence is unavailable; execution therefore fails closed. Cloud readiness applies only to `local_to_cloud`.

## Evidence and limits

Local → Cloud uses token-free official-cloud readiness instead of local image/
mount evidence. Supply known `--cloud-not-before` and `--queue-limitation-ack`;
the signed quiescence receipt must also attest `cloud_not_before`,
`cloud_availability_verified: true` and `queue_limitation_ack: true`. Unknown
cooldown blocks authorization. Ten minutes passing does not prove a lost detach.

Typed `full` profiles support URL, secret_token, certificate_pem, allowed_updates,
max_connections and ip_address. Keep them in private JSON. Configuration success
and observable fields do not prove delivery or future secret/certificate state.
Full preserve without independent original-profile verification remains BLOCKED;
explicit full set is supported. URL-only requires acknowledgement. Source delete
always uses drop=false; explicit target drop has one durable attempt and cannot
be inferred from pending_update_count after a lost response. No exactly-once or
uninterrupted queue guarantee is claimed across the remote API boundary.

To preserve source polling, explicitly select action `preserve` with the private
profile `{"mode":"polling"}` (the UI has a matching scope option). After detach,
the executor deletes any old target webhook and requires an empty URL readback.
Webhook-only preserve is a verified no-op; combining it with drop is rejected
before API calls. The acceptance matrix includes all twelve direction/action
combinations plus four preserved-polling variants against loopback HTTP mocks.

See [recovery](maintenance.md#recovering-the-migration-journal),
[private configuration](configuration.md#private-migration-authority) and the
[offline fixture walkthrough](maintenance.md#isolated-mock-walkthrough).

## Bash helper

The current script supports **cloud → local**. It loads `.env` beside the script,
or the file selected by `ENV_FILE` (relative paths are relative to the caller's
working directory). An absent default file is allowed; an invalid explicit file
stops execution. This is trusted shell code, not a sandbox. Arguments take
precedence over process environment, then file values, then defaults. Within a
source, `SELF_BOT_URL` and `WEBHOOK_URL` take precedence over legacy
`TELEGRAM_BOT_URL` and `WEB_HOOK`; process aliases override file values.
Empty webhook values retain the legacy fallback described below. For example,
from another directory use `ENV_FILE="/path/to/settings.env" bash
/path/to/migrate_off_to_self.sh "$BOT_TOKEN"`.

Arguments are `BOT_TOKEN`, `SELF_BOT_URL`, then `WEBHOOK_URL`:

<!-- issue10-example:environment -->
```sh
export WEBHOOK_SECRET_MODE=none WEBHOOK_IP_MODE=dns WEBHOOK_MAX_CONNECTIONS=40
set -euo pipefail
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
SELF_BOT_URL="http://127.0.0.1:18080" \
WEBHOOK_URL="https://example.com/telegram/webhook" \
  bash ./migrate_off_to_self.sh "$BOT_TOKEN"
unset BOT_TOKEN
```

Alternatively pass all three positional arguments. Do not put the webhook URL in
argument 2: that argument is the Bot API endpoint.

<!-- issue10-example:positional -->
```sh
export WEBHOOK_SECRET_MODE=none WEBHOOK_IP_MODE=dns WEBHOOK_MAX_CONNECTIONS=40
set -euo pipefail
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
bash ./migrate_off_to_self.sh "$BOT_TOKEN" \
  "http://127.0.0.1:18080" "https://example.com/telegram/webhook"
unset BOT_TOKEN
```

Both forms use external API port **18080**; nginx forwards to `botapi:8081`.
The webhook URL is an application address. These commands do not start a polling
consumer. From another working directory, use an absolute helper path:

```sh
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
ENV_FILE="/path/to/settings.env" \
  bash /path/to/migrate_off_to_self.sh "$BOT_TOKEN"
unset BOT_TOKEN
```

`DROP_PENDING_UPDATES=true` discards pending updates. Its default is `false`.

### Current helper limitations

- The token-free target probe checks a characteristic error response, not the
  host's identity or bot readiness. Verify the endpoint before confirmation.
- Token-bearing calls start only after confirmation; the helper does not implement
  resume after an ambiguous `logOut` result. Do not blindly rerun after a lost response.
- An empty webhook argument reuses the old webhook when present. It does not
  explicitly request polling.
- The helper and browser resolve the complete desired profile before source mutations.
  Supply the previous secret and public certificate explicitly; WebhookInfo does not expose them.
- Tokens can appear in process arguments and external logs. The helper sanitizes
  its own console and diagnostic artifacts; crash leftovers remain private raw.

These are tracked in [#2](https://github.com/ichinya/tg-selfhost-botapi/issues/2),
[#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) and
[#9](https://github.com/ichinya/tg-selfhost-botapi/issues/9).
Use a test bot before relying on the helper for a working installation.

### Request time limits (root Bash helper)

`MIGRATION_CONNECT_TIMEOUT` defaults to 5 seconds (range 1..60);
`MIGRATION_REQUEST_DEADLINE` defaults to 30 seconds (range 1..300). Both accept
whole decimal seconds; connect must not exceed deadline. The deadline covers
one HTTP attempt, including its response body, excluding operator input. The
token-free probe uses min(deadline, 10) and caps connect to that value.

The trusted file loader supports both settings. Process values override file
values; only an unset setting uses its default. An explicitly empty value is an
error, unlike the legacy endpoint settings' empty-value fallback. Invalid values
stop before any HTTP request. These are host-side settings, absent from Compose
and the container environment. See [migration](migration.md).

### Outcomes and private diagnostics

The root Bash helper stores schema version 1 evidence in `logs/migration` beside
the script, independently of the caller's directory. Directories must be owned by
the user and have mode 0700; files are 0600 (`umask 077`). Unsafe existing paths
and symlinks stop execution before HTTP. Each run has a unique `run.*` directory:
`summary.json` links to `request-*.*/intent.json` written before every HTTP attempt
and `receipt.json` written afterwards. Receipts link separate full sanitized
`body.txt`, `transport-error.txt` and `http-status.txt` artifacts. HTTP status,
curl exit, parse/schema status, API fields, effective time limits, timestamps,
observations and outcome remain independent. Status 000 becomes null; a transport
failure can still preserve HTTP status and a partial body. Sanitized text is not a
byte-exact original; controls, JSON and escaped secrets are normalized.

Success requires complete transport, HTTP 2xx, boolean `ok:true` and a valid
method result. A complete valid rejection on HTTP 2xx/4xx is
`CONFIRMED_REJECTION` (exit 1); 429 reports `retry_after` without sleeping or
retrying. HTTP 5xx, malformed or contradictory replies and lost responses to any
authenticated request yield `UNKNOWN` (exit 3). Even `getMe` and
`getWebhookInfo` may affect session state. No dependent request, readback,
rollback or automatic retry follows an unknown outcome. A local pre-send error
is `NOT_SENT`; success and operator cancellation exit 0. The expected token-free
404 probe is checked separately from method success and cannot authenticate a host.

A root-wide atomic lock is acquired before inspecting previous runs or probing.
An active/stale lock, unfinished authenticated intent, UNKNOWN authenticated attempt or partial
migration blocks a new invocation before HTTP. This guard covers one script copy
and all bots using its storage root. Confirmed steps/effects remain in the summary
after a later failure. Stop and reconcile the dossier with independent evidence;
waiting for `retry_after`, repeating `getMe` or reading back a URL does not prove
that a previous effect did not occur. There is no automatic bypass or resume.

An unfinished token-free probe does not block after its lock has been released.
Every surviving lock blocks, including one left by SIGKILL. To recover, first stop
all helper processes and reconcile the attempts and confirmed effects against
independent evidence. After deciding a safe next procedure, archive the entire
dossier in an owner-only location outside `logs/migration`, then deliberately
remove the reconciled run directories and stale lock. Keep that archive until
the migration is resolved. Removing a lock alone is not reconciliation; copying
the script to another directory does not make an unknown effect safe to repeat.
This manual operator action is the recovery boundary pending issue #2.

Raw capture is private and removed only after sanitization succeeds. Crashes,
SIGKILL and storage failures may leave private raw files or incomplete intents;
retain and inspect those locally. Do not upload raw files or the dossier to public
issues. Retention lasts until deliberate manual removal after reconciliation.
The journal uses atomic rename, not an fsync durability guarantee. Issue #2 needs
an explicit adapter for this schema; other executors' journals are not interchangeable.
This contract applies only to `migrate_off_to_self.sh`: browser execution,
generated Bash and the raw-curl runbook below retain their separate contracts.
The manual curl examples create no dossier and do not implement the guard.
Obtain the updated helper from an up-to-date repository checkout. It runs on the
host, is excluded from the server image and Pages, and requires no server redeploy.

## Browser tool

An operation records its plan and observations separately in the current tab.
SUCCESS requires a confirmed final target URL; it does not establish delivery.
The stage journal is local to the page and is not the durable recovery mechanism
tracked in #2. Declining consent does not create an operation.
An authenticated Bot API rejection is distinct from an unreliable or lost
response, whose effect may be UNKNOWN. A valid `retry_after` establishes a
cooldown; its expiry neither retries nor resolves an uncertain operation. A local
`close` 429 window differs from the cloud return restriction after `logOut`.
During the cooldown the page offers a waiting instruction instead of executable
commands; expiry does not lift a separate recovery guard.
The result distinguishes ERROR, PARTIAL and UNKNOWN from SUCCESS. Source and
target bot IDs must match, and the final URL is read from the target rather than
assumed from the requested URL. The summary distinguishes source observation,
expected URL, target observation and the stage journal. Webhook URL paths and query
strings are masked in the result and history. After a failed or uncertain logout, follow the
recovery procedure in #2; do not log back into source merely to check it.
The tab blocks simultaneous actions and retains per-bot recovery guards in
memory. Editing settings invalidates the check. Closing or reloading the tab
loses these guards; coordination between processes remains outside this tool
(#2 and #14). After a completed transfer, a fresh webhook-only operation may
use the confirmed target, while the old source remains blocked in this tab.
The generated Bash plan stops on errors and reports its phase and outcome;
it compares bot IDs and the final URL. It is a separate process with no shared
lock or durable state with the page. Reconcile PARTIAL or UNKNOWN before any
repeat; a cooldown never restarts the plan automatically.

The generated Bash plan prompts separately for the webhook URL; it does not
copy the URL from the form into the script. Leave it empty to inherit the source URL.

[Open the migrator](../../tg_selfhost_botapi_migrator.html). The page is a static
client, not a server-side migration executor. It uses requests from your browser;
the API needs an appropriate origin/access setup.

Local checks and plan generation send no requests. State checks require consent
and read only the explicitly selected source; they do not discover where a bot
is logged in. Cloud → local execution probes the target without a token, asks
for consent, reads the source, detaches and logs out there, then accesses the
target. Webhook-only never calls `logOut` or `close`. Editing the form invalidates
cached source data. A partial or unknown operation blocks further execution for
that bot in the tab; reconcile state manually. A known rejection before any
effect may be retried after any applicable cooldown. Local transitions use manual checklists.

Browser execution and generated plans still have incompletely verified
[error-handling](https://github.com/ichinya/tg-selfhost-botapi/issues/6) and
[shell-escaping](https://github.com/ichinya/tg-selfhost-botapi/issues/8) limitations.
A CORS failure can hide the response to an already executed mutation: check the
current state before trying another plan. Review generated commands before use.

## Polling, webhook profile and files

Webhook profile #7 is integrated. State transfer #5 and action semantics #9 remain
independent; their unfinished modules are not runtime dependencies.
Empty webhook input retains legacy inheritance; it is not a polling action.
For explicit polling, after completing the server transition, manually delete
the **target** webhook and verify that `result.url` is a string equal to `""`:

```sh
# BOT_TOKEN and SELF_BOT_URL refer to the chosen target, after migration.
set -euo pipefail
curl -q -fsS --connect-timeout 5 --max-time 30 -X POST \
  "$SELF_BOT_URL/bot$BOT_TOKEN/deleteWebhook" \
  --data-urlencode 'drop_pending_updates=false' | jq -e '.ok == true and .result == true'
curl -q -fsS --connect-timeout 5 --max-time 30 \
  "$SELF_BOT_URL/bot$BOT_TOKEN/getWebhookInfo" | \
  jq -e '.ok == true and (.result.url | type == "string") and .result.url == ""'
```

Stop if either check fails. Start your own polling client only after verification;
the examples do not consume updates. URL readback does not prove webhook delivery.
Supply `secret_token`, certificate, `allowed_updates`, `max_connections` and other
required settings to the migration inputs from your saved profile. Secrets and the uploaded certificate
cannot be reconstructed from `getWebhookInfo`.

In local mode an absolute `getFile.file_path` names a path on the server/container.
It requires compatible mounts and application paths; state transfer alone does
not fix them. nginx forwards `/file/` requests to the Bot API instead of exposing
the state directory. Do not invent `X-Telegram-Bot-Token` authorization. See
[file access](configuration.md).
An independent downloads service's port 18081 does not replace API port 18080.

[Configuration](configuration.md) · [Maintenance](maintenance.md)

## Doctor migration preflight

Use `python3 tools/doctor.py --scenario official-to-self --migration-input /private/decisions.json`.
The strict input contract is `tools/doctor-input.schema.json`; keep the real file
outside every Git checkout and webroot, with owner-only POSIX permissions. It
contains planning decisions, never tokens, URLs, API hashes or certificate contents.
Native Windows private-file guarantees remain UNKNOWN.

A v1 input starts with `schema_version: 1`. Choose
`delivery_action: preserve|set|polling`, explicitly set `drop_pending_updates`
(boolean, including false), `file_access: not_used|local_path|shared_volume|remote_authenticated`
and `workflow_prepared` (boolean). The workflow declaration includes stopping the
application at the correct stage, backups, endpoint switching and absolute-path
handling when files are used. For preserve/set, also declare
`webhook_profile_prepared`: the full profile, secret/certificate handling, IP,
connections and allowed updates must be prepared in separate protected configuration.
No webhook secret or URL belongs in doctor input.

```json
{
  "schema_version": 1,
  "delivery_action": "polling",
  "drop_pending_updates": false,
  "file_access": "not_used",
  "workflow_prepared": true
}
```

This example declares a prepared plan; it is not a receipt of executed actions.
`remote_authenticated` remains UNKNOWN without an independently verified safe
contract at the boundary of issue #5; doctor v1 does not implement a download service.
Local/shared file access remains UNKNOWN until the application path/volume mapping
is independently verified; choosing a mode does not prove that mapping.

For `self-to-self`, select the source separately with `--source-file`,
`--source-env-file`, `--source-profile`, `--source-project-directory` and
`--source-project-name`. Add `transfer` with explicit `method`, boolean
`backup_prepared` and `exclusive_use_plan_prepared`, and `backlog_policy`:
`drain` or `accept-loss`. State backings must be distinct.

- `per-bot` requires `state_subdir`: one relative directory component in the source
  work root. Only that subtree is measured; shared tqueue/webhook stores do not
  move with it, so the backlog decision must cover them. The destination subtree
  must be absent.
- `dedicated-cold` measures the complete work root, including shared stores. Also
  declare `dedicated_source: true` and `target_empty_prepared: true`. The backup
  covers the whole source, and the exclusive-use plan stops every writer and
  supervisor at the copy boundary. The observed target root must be empty.
- `fresh-login` requires `backlog_policy: accept-loss`. Do not supply
  `state_subdir`. Subtree/copy capacity and copy compatibility are optional SKIP;
  baseline storage checks still apply.

Measurements read metadata only. Changing metadata, symlinks, nested mounts and
unsupported entries remain UNKNOWN. Hard links do not double the measured bytes.
Target reserve includes measured bytes/entries plus 10%; optional
`transfer_metadata` is declared information and cannot establish capacity.
Observed matching binary versions and available source revisions form the
compatibility baseline; differing or unknown versions remain UNKNOWN.

`self-to-official` also requires `source_backup_prepared: true` and
`source_backlog_policy: drain|accept-loss`; its prepared workflow is logout-first.
It checks the local source and prepared manual workflow. Cloud
authorization, session restrictions and delivery remain unverified. `hook-only`
is BLOCKED/1 with `unsupported_scenario` (issues #7/#9). Missing decisions are
UNKNOWN/3 with their field names; false preparedness or unsafe POSIX permissions
is BLOCKED/1; malformed or unreadable input exits 2. Reports retain pending actions and unverified facts.
Doctor does not run migration, helpers, bot methods, cloud probes, journals or
locks. READY means readiness to begin the prepared procedure; it does not certify
helpers, completed transfer, authorization or delivery.

## Complete webhook profile inputs

Before source mutations, the helper resolves `WEBHOOK_SECRET_MODE=provided|none`, `WEBHOOK_IP_MODE=dns|pinned`, `WEBHOOK_CERTIFICATE_MODE=provided|none`, `WEBHOOK_ALLOWED_UPDATES` (JSON array of strings), `WEBHOOK_MAX_CONNECTIONS` and `WEBHOOK_TARGET_LOCAL=true|false`. Unknown secret/IP and unavailable custom certificates stop preflight. `fixed` is an alias for pinned canonical IPv4. Source `ip_address` does not reveal pinning intent. Explicit inputs override source; omitted optional updates become the documented `[]` default. `[]` excludes chat_member, message_reaction and message_reaction_count; it is not every update type. Null or invalid values fail. Per-bot max_connections is 1–100; up to 100000 requires explicit local-mode capability (`TELEGRAM_LOCAL`/`--local`), independently of server `TELEGRAM_MAX_WEBHOOK_CONNECTIONS`. A self-host URL does not establish this capability.

Use `WEBHOOK_SECRET_TOKEN` or `WEBHOOK_SECRET_TOKEN_FILE`, exactly one for provided mode; none asserts an intentionally unprotected webhook. Secret files allow one final LF/CRLF; inline secrets are never trimmed. Use `WEBHOOK_CERTIFICATE_FILE` for a public PEM, never a private key. Protected files (including `BOT_TOKEN_FILE`) must be outside checkout/webroot, with operator-only access. Values from the process override trusted `ENV_FILE` (default: helper directory `.env`), including explicitly empty values; value/file pairs are selected at one tier. Positional URLs remain highest priority. Polling has no webhook profile.

Full profile transport is enabled: urlencoded without a certificate, entirely multipart with a certificate. Secret/scalar files are private snapshots; no token/secret/URL is placed in curl argv or raw diagnostics. The helper disables tracing, uses curl -q without redirects, guards HTTP/ok/result and never retries a mutation. Public PEM requires Bash 4+, jq, curl, realpath and openssl X.509 validation; no private key is accepted. Temporary files use umask 077 and are removed on exit/signals.

The standalone browser now has explicit secret/none, JSON updates, connections/local capability, DNS/fixed IPv4 and public certificate File controls. An incomplete profile blocks mutations. Files are captured before logout; uploads use FormData without a manually assigned boundary. Form changes invalidate snapshots and never clear UNKNOWN/completion locks. Local-to-local/cloud transitions remain separate manual stages.

Export/clipboard now contain a standalone Bash runtime and environment references only. Supply the profile, token and URLs again through trusted runtime inputs; the export does not contain browser values, private paths or certificate bytes. Source state is read fresh at execution. Manual transitions retain the STOP barrier and use a separate `MIGRATION_MODE=target-stage` helper invocation after lifecycle/state acceptance. UNKNOWN/completed migrations expose only reconciliation guidance.

Postflight performs two target reads separated by two seconds within a ten-second observation deadline. It compares exact URL, update sets, connections, certificate presence and fixed IP. DNS IP is observational. Pending trend and historical/new delivery/synchronization errors are reported separately using counters only. An empty queue does not prove delivery. Secret and certificate bytes cannot be verified by WebhookInfo. New errors, missing counters or mismatched readable settings stop acceptance; mutations are never retried.

### Protected profile and recovery

The two existing quick examples explicitly choose none: use that only when the receiver has no previous secret. For a protected receiver, prepare operator-only files outside checkout/webroot and use this placeholder example instead:

```sh
export BOT_TOKEN_FILE=/secure/bot-token
export SELF_BOT_URL=http://127.0.0.1:18080
export WEBHOOK_URL=https://example.com/telegram/webhook
export WEBHOOK_SECRET_MODE=provided
export WEBHOOK_SECRET_TOKEN_FILE=/secure/previous-webhook-secret
export WEBHOOK_IP_MODE=dns
export WEBHOOK_ALLOWED_UPDATES='["message","callback_query"]'
export WEBHOOK_MAX_CONNECTIONS=40
export WEBHOOK_CERTIFICATE_MODE=provided
export WEBHOOK_CERTIFICATE_FILE=/secure/public-certificate.pem
bash ./migrate_off_to_self.sh
```

The browser uses password/File controls and never persists private inputs in storage. Its certificate preflight checks X.509 structure only, not cryptographic validity; target API acceptance validates the certificate. The helper also checks X.509 with openssl. Exports require these private inputs again at runtime and contain no browser token, secret, URL, certificate bytes or actual private filename. The manual plan has an unconditional STOP/exit before a separately saved target-stage script; it never performs state transfer. For target-stage supply explicit saved URL, updates, connections and certificate mode. After source logOut, never diagnose by logging into the old source; reconcile on target. Before confirmed logOut, do not authorize both endpoints. UNKNOWN may mean the mutation applied: no blind retry, rollback or polling fallback.

Exit 0 means API acceptance and readable profile readback. Secret/certificate bytes cannot be readback-verified. Queue growth is an observation, not a count-equality or loss assertion; historical errors are distinguished from new delivery/synchronization errors. A zero queue does not prove delivery. Delivery stays unverified without a new, correlated receiver receipt. The 10-second/two-sample observation is shorter than the recommended 30-second maximum; it is not an SLA. Keep debug/VLOG disabled; logger/image qualification and real test-bot delivery are separate external gates. See maintenance for receiver, pinned-source and CI instructions.
