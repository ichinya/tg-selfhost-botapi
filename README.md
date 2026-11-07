# TG Selfhost Bot API

Self-hosted Telegram Bot API in Docker, built directly from the official
[tdlib server](https://github.com/tdlib/telegram-bot-api).
Includes a webhook User-Agent patch and migration tools.

[English docs](docs/en/README.md) · [Документация на русском](docs/ru/README.md) ·
[Documentation website](https://ichinya.github.io/tg-selfhost-botapi/) ·
[Migration tool](https://ichinya.github.io/tg-selfhost-botapi/tg_selfhost_botapi_migrator.html)

See [installation](docs/en/getting-started.md) / [установка](docs/ru/getting-started.md)
for Compose, private credentials and storage preparation. Review the
[networking limitations](docs/en/configuration.md#current-limitations) before
starting on a public host.

- Official server source; independent Docker entrypoint.
- `User-Agent: WebhookDelivery/1.0` on outgoing webhooks.
- Checked image builds and nightly upstream checks.
- Bash migration helper and browser-based migration planner.

The gateway binds to localhost and keeps state private. Split storage supports
local readers and a separate opt-in download handler; see the
[English file contract](docs/en/configuration.md#files-in-local-mode) /
[файловый контракт](docs/ru/configuration.md). These profiles require a qualified
image pair; source implementation alone is not release or production evidence.

[Contributing](CONTRIBUTING.md) · [Issues](https://github.com/ichinya/tg-selfhost-botapi/issues)
