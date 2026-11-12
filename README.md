# TG Selfhost Bot API

Self-hosted Telegram Bot API in Docker, built directly from the official
[tdlib server](https://github.com/tdlib/telegram-bot-api).
Includes a webhook User-Agent patch and migration tools.

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
- One Python migration executor with a Bash adapter and local helper UI.

The API gateway binds to localhost and rejects the old `/file` interface with 404.
For downloads use explicit split storage with a scoped reader or the per-bot
authenticated handler: [English](docs/en/configuration.md#files-in-local-mode) ·
[Русский](docs/ru/configuration.md#файлы-в-local-mode).

[Contributing](CONTRIBUTING.md) · [Issues](https://github.com/ichinya/tg-selfhost-botapi/issues)

File secrets: [EN](docs/en/configuration.md#docker-compose-file-secrets) · [RU](docs/ru/configuration.md#файловые-секреты-docker-compose).
