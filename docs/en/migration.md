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
Positional token/target/webhook arguments are rejected without echoing values.
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

The official procedure for retaining updates is `deleteWebhook`, then `close` on
the old server, followed by moving the bot's state subdirectory (identified by its
user ID) to the new server's working directory. Resume requests on the new server
after the transfer. Handle a `retry_after` response from `close` before proceeding.

Use a consistent backup, preserve ownership and paths, and prevent simultaneous
use of the same state. `drop_pending_updates=false` alone does not transfer state
or guarantee continuity.

## Adapter compatibility

Use `bash migrate_off_to_self.sh plan/apply/status/resume/export ...` with the
same flags as Python. There are no curl/jq requirements for migration itself.
The repository `.env` and `.env.example` are Compose configuration only.
Migration inputs belong in process environment or a separate private file
selected with `--env-file`; the wrapper never reads `.env` automatically.
Environment values take precedence. An empty webhook requires an explicit action
even in legacy mode. Use `BOT_TOKEN` or `BOT_TOKEN_FILE`; positional credentials
are rejected. Legacy mode prints the plan and
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
