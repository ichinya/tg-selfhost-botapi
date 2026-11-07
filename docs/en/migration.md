---
title: Migration
translation: /docs/ru/migration.html
---

# Migration

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

The helper supports **cloud → local**. Arguments are `BOT_TOKEN`, `SELF_BOT_URL`,
`WEBHOOK_URL`, then the required `WEBHOOK_ACTION=preserve|set|polling`. Missing,
empty or unknown action stops before networking. Existing three-argument commands
must add an action; there is no inference from URL emptiness.

It reads a trusted Bash `.env` beside the script, or `ENV_FILE` relative to the
caller's directory. An absent default is allowed; an invalid explicit file stops.
Only the [documented whitelist](configuration.md#migration-helper-environment)
returns from that file. Precedence uses **presence**, including empty strings:
positional argument > process canonical > process URL alias > file canonical/alias.
Other settings use process > file > default. Empty values never activate fallback.
`OFFICIAL_BOT_URL` is a process-only source override for isolated tests.

The following equivalent examples intentionally choose a new webhook without a
secret or custom certificate, DNS policy, API-default updates and 40 connections.
Use your own complete saved profile when those choices do not match your receiver.
Argument 2 is the Bot API, argument 3 is the receiver. Both use API port **18080**.

<!-- issue10-example:environment -->
```sh
set -euo pipefail
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
SELF_BOT_URL="http://127.0.0.1:18080" \
WEBHOOK_URL="https://example.com/telegram/webhook" \
WEBHOOK_ACTION=set WEBHOOK_SECRET_MODE=none WEBHOOK_IP_MODE=dns \
WEBHOOK_CERTIFICATE_MODE=none WEBHOOK_ALLOWED_UPDATES='[]' WEBHOOK_MAX_CONNECTIONS=40 \
  bash ./migrate_off_to_self.sh "$BOT_TOKEN"
unset BOT_TOKEN
```

<!-- issue10-example:positional -->
```sh
set -euo pipefail
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
WEBHOOK_SECRET_MODE=none WEBHOOK_IP_MODE=dns WEBHOOK_CERTIFICATE_MODE=none \
WEBHOOK_ALLOWED_UPDATES='[]' WEBHOOK_MAX_CONNECTIONS=40 \
  bash ./migrate_off_to_self.sh "$BOT_TOKEN" \
  "http://127.0.0.1:18080" "https://example.com/telegram/webhook" set
unset BOT_TOKEN
```

For polling, pass an empty third argument and `polling` as the fourth argument.
For preserve, pass an empty third argument and `preserve`; supply the source secret
or explicitly confirm none, choose its IP policy, and provide its public PEM when
required. See the action table below. No command starts a polling consumer.

```sh
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
bash ./migrate_off_to_self.sh "$BOT_TOKEN" "http://127.0.0.1:18080" "" polling
unset BOT_TOKEN
```

### Current helper limitations

- The token-free probe is not host authentication. Confirm the endpoint and stop
  old clients before allowing token-bearing reads. A second confirmation applies
  the resolved profile, source detach/logOut, then the first target getMe.
- Source detach always uses `drop_pending_updates=false`. The selected drop
  (default false) applies only to the single target set/delete. True intentionally
  destroys target backlog; false does not guarantee queue transfer or survival
  after local logOut. There is no automatic rollback, resume or retry after UNKNOWN.
- Secret and certificate bytes cannot be recovered through getWebhookInfo. Supply
  private inputs before detach; available readback checks configuration, not delivery.
- The positional bot token may be visible in process arguments. New request bodies
  use private temporary files; this does not close the broader privacy scope of #2.
- Full delivery qualification in [#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7)
  remains separate. Use a test bot before migration of a working installation.

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

| Action and receiver input | Result |
| --- | --- |
| `preserve` + empty (or any new URL) | Preserve source mode; the new URL is ignored |
| `set` + empty | Preflight error, zero mutations |
| `set` + valid URL | Set the explicit complete profile |
| `polling` + any URL, including invalid | Ignore inactive URL/profile; target deleteWebhook and typed empty-URL readback |

In Webhook only, preserve is read-only; it never resets the queue or reinstalls a
webhook, and `drop=true` is rejected. During migration, preserve snapshots the
source: polling becomes explicit target delete; webhook becomes target set with
the same URL, allowed_updates, max_connections and certificate flag. A missing
optional allowed_updates means API default `[]`; malformed data is an error.
Observed IP cannot establish DNS/fixed policy. Unknown secret/certificate bytes
must be supplied privately before detach; choose `set` to intentionally change
the profile. HTTP receiver URLs require explicit `WEBHOOK_TARGET_LOCAL=true` /
the UI --local capability, asserted by the operator, not discovered remotely.
Cloud always requires HTTPS. Local max_connections is also bounded by server limits.

The browser has no default action. Clearing URL never changes the selected action.
File/profile/action/drop changes invalidate checks while preserving completed and
UNKNOWN locks. Preview performs no fetch. Export uses runtime `BOT_TOKEN`,
`SOURCE_API`, `TARGET_API`, `WEBHOOK_URL`, secret and certificate file variables;
it copies no entered token, receiver URL, secret, PEM bytes or local path. The script
re-reads source and asks consent; the browser snapshot is not a current-state guarantee.

Readback requires HTTP success, ok=true, typed results and the expected configuration;
lost/malformed responses stop without retry. Queue assertions in mocks are models,
not evidence of Telegram delivery. Start your own polling client only after verification.
Independent [#5](https://github.com/ichinya/tg-selfhost-botapi/issues/5) file access and
[#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) delivery qualification remain
outside this action slice; their unfinished modules are not runtime dependencies.

In local mode an absolute `getFile.file_path` names a path on the server/container.
It requires compatible mounts and application paths; state transfer alone does
not fix them. nginx forwards `/file/` requests to the Bot API instead of exposing
the state directory. Do not invent `X-Telegram-Bot-Token` authorization. See
[file access](configuration.md).
An independent downloads service's port 18081 does not replace API port 18080.

[Configuration](configuration.md) · [Maintenance](maintenance.md)
