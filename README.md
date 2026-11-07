# TG Selfhost Bot API

Self-hosted Telegram Bot API in Docker, built directly from the official
[tdlib server](https://github.com/tdlib/telegram-bot-api).
Includes a webhook User-Agent patch and migration tools.
Migration requires explicit `preserve`, `set` or `polling`: empty URL preserves source mode
only with `preserve`, errors with `set`, and is ignored by `polling` (target webhook deletion).
See the [English](docs/en/migration.md#polling-webhook-profile-and-files) /
[Russian](docs/ru/migration.md#polling-профиль-webhook-и-файлы) action tables.

[English docs](docs/en/README.md) · [Документация на русском](docs/ru/README.md) ·
[Documentation website](https://ichinya.github.io/tg-selfhost-botapi/) ·
[Migration tool](https://ichinya.github.io/tg-selfhost-botapi/tg_selfhost_botapi_migrator.html)

## Quick start

Requires Docker with Compose v2. Review the [networking limitations](docs/en/configuration.md#current-limitations)
before starting on a public host. Create `.env` and fill in `API_ID` / `API_HASH`:

```sh
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Local builds work before the first GHCR release. Once a published image is
available, use `docker compose pull && docker compose up -d`.
See [installation](docs/en/getting-started.md) for networking and verification.

- Official server source; independent Docker entrypoint.
- `User-Agent: WebhookDelivery/1.0` on outgoing webhooks.
- Checked image builds and nightly upstream checks.
- Bash migration helper and browser-based migration planner.

The gateway binds to localhost by default and forwards file requests to the Bot API
without exposing its state directory. See [configuration](docs/en/configuration.md)
before enabling external access.

[Contributing](CONTRIBUTING.md) · [Issues](https://github.com/ichinya/tg-selfhost-botapi/issues)
