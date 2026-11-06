---
title: Migration
translation: /docs/ru/migration.html
---

# Migration

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

1. Confirm the target infrastructure is reachable and correctly configured using the [image and startup steps](getting-started.md#start), followed by the [token-free readiness check](getting-started.md#verify). Bash and HTML tool preflights use a bot token and are not neutral checks of a new server.
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

## Bash helper

The current script supports **cloud → local**. Run it from the repository root:
it reads `.env` from the **current working directory**.

Arguments are `BOT_TOKEN`, `SELF_BOT_URL`, then `WEBHOOK_URL`:

```sh
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
SELF_BOT_URL="http://127.0.0.1:18080" \
WEBHOOK_URL="https://example.com/telegram/webhook" \
  bash ./migrate_off_to_self.sh "$BOT_TOKEN"
unset BOT_TOKEN
```

Alternatively pass all three positional arguments. Do not put the webhook URL in
argument 2: that argument is the Bot API endpoint.

`DROP_PENDING_UPDATES=true` discards pending updates. Its default is `false`.

### Current helper limitations

- A failed target preflight only warns; the script can still disable the old route.
- It makes token-bearing calls before confirmation and does not implement resume
  after an ambiguous `logOut` result. Do not blindly rerun after a lost response.
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

Browser execution and generated plans still have
[error-handling](https://github.com/ichinya/tg-selfhost-botapi/issues/6) and
[shell-escaping](https://github.com/ichinya/tg-selfhost-botapi/issues/8) limitations.
A CORS failure can hide the response to an already executed mutation: check the
current state before trying another plan. Review generated commands before use.

[Configuration](configuration.md) · [Maintenance](maintenance.md)
