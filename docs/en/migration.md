---
title: Migration
translation: /docs/ru/migration.html
---

# Migration

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

A migration changes the Bot API endpoint used by your application and may also
change its webhook. Know the old endpoint before starting. Do not use cloud
`getMe` as a neutral discovery request: token-bearing calls can affect sessions.

Stop the application or background worker that keeps calling the old API.
Include pollers, scheduled jobs, retries and supervisors. A webhook receiver is a
different process: stopping an API client does not freeze the queue or stop Bot
API webhook delivery. Keep the receiver available while draining existing work.
Prepare the new service without authorizing this bot, back up state and record
the webhook profile. `getWebhookInfo` does not return the previous
`secret_token`; keep it in your own configuration.

A local Bot API running with `--local` accepts HTTP or HTTPS webhook URLs; the official cloud Bot API requires HTTPS.

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

The helper checks the target's root without a token, with a deadline and without
following redirects. A characteristic 404 response does not authenticate the
host. Confirm source, target, webhook and drop policy before allowing token calls.
Source detach and `logOut` must succeed before the first target `getMe`. An HTTP/API
failure, malformed response or unknown mutation outcome stops the sequence;
do not probe both sides or automatically retry a lost `logOut` response.

### Local → local with state transfer

The upstream per-bot procedure is `deleteWebhook` without an intentional drop,
then a successful `close` on the old server, then moving the bot's subdirectory
(located using its user ID) into the compatible target's working directory.
Stop old API clients first. A failed `close`, including 429/`retry_after`, or an
unknown response blocks the transfer and any target login. Do not blindly retry.
Directory names can contain a token: do not paste them into public logs.

There is an important storage boundary in the
[pinned ClientManager.cpp](https://github.com/tdlib/telegram-bot-api/blob/e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1/telegram-bot-api/ClientManager.cpp):
`tqueue.binlog` and `webhooks_db.binlog` live in the shared working directory,
outside per-bot directories. Moving one bot directory does not prove preservation
of its accumulated local queue. On a shared server, drain or explicitly account
for backlog before moving that bot. Merging shared binlogs into a running target
with other bots is not supported. `drop_pending_updates=false` is not a transfer
or preservation guarantee. A simpler source `logOut` and fresh target login is
possible when the loss of local backlog is acceptable.

For a **dedicated installation**, a separate cold-transfer procedure is:

1. Reserve a maintenance window. Stop all API clients, retries and supervisors;
   save the full webhook profile and a consistent [backup](maintenance.md).
2. Detach the source webhook without intentionally dropping updates and obtain a
   successful `close`. Stop on any failure or unknown result.
3. Stop all source writers and Bot API containers before copying the working
   directory. Keep `restart: always` and external automation from starting the
   old service again. Stopping a shared container affects every bot on it.
4. Transfer the entire consistent working directory, including shared stores,
   only to an empty compatible target. Preserve ownership and permissions; check
   versions, mount paths and the application's handling of absolute media paths.
   Never copy a live database or overwrite another installation's shared binlogs.
5. Independently verify the transfer and that no old writers remain. Only then
   start the target and make its first token-bearing request (`getMe`).
6. Restore the required webhook profile or explicitly configure polling. Verify
   the actual configuration and a test update before resuming normal traffic.

The browser provides separate manual stages for this scenario. It neither copies
state nor offers a copy-all script that logs in to the target across that boundary.
Mocks do not prove that Telegram updates survive a real transfer.

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
- The helper does not transfer `secret_token`, certificates or the full delivery
  profile. Restore required parameters deliberately.
- Tokens can appear in process arguments and logs.

These are tracked in [#2](https://github.com/ichinya/tg-selfhost-botapi/issues/2),
[#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) and
[#9](https://github.com/ichinya/tg-selfhost-botapi/issues/9).
Use a test bot before relying on the helper for a working installation.

## Browser tool

[Open the migrator](../../tg_selfhost_botapi_migrator.html). The page is a static
client, not a server-side migration executor. It uses requests from your browser;
the API needs an appropriate origin/access setup.

Local checks and plan generation send no requests. State checks require consent
and read only the explicitly selected source; they do not discover where a bot
is logged in. Cloud → local execution probes the target without a token, asks
for consent, reads the source, detaches and logs out there, then accesses the
target. Webhook-only never calls `logOut` or `close`. Editing the form invalidates
cached source data. A failed/unknown mutation blocks further execution on the
page until you reconcile state manually. Local transitions use manual checklists.

Browser execution and generated plans still have
[error-handling](https://github.com/ichinya/tg-selfhost-botapi/issues/6) and
[shell-escaping](https://github.com/ichinya/tg-selfhost-botapi/issues/8) limitations.
A CORS failure can hide the response to an already executed mutation: check the
current state before trying another plan. Review generated commands before use.

## Polling, webhook profile and files

The independent fixes in [#5](https://github.com/ichinya/tg-selfhost-botapi/issues/5),
[#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) and
[#9](https://github.com/ichinya/tg-selfhost-botapi/issues/9) are not integrated in
this candidate. Their unfinished modules are not dependencies of these helpers.
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
Restore `secret_token`, certificate, `allowed_updates`, `max_connections` and other
required settings from your saved profile. Secrets and the uploaded certificate
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
