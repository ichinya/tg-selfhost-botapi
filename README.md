# TG Selfhost Bot API

Docker packaging of the official [Telegram Bot API](https://github.com/tdlib/telegram-bot-api),
with outgoing `User-Agent: WebhookDelivery/1.0` and migration tools.

[English installation](docs/en/getting-started.md) · [Установка на русском](docs/ru/getting-started.md) ·
[Documentation](https://ichinya.github.io/tg-selfhost-botapi/) ·
[Migration tool](https://ichinya.github.io/tg-selfhost-botapi/tg_selfhost_botapi_migrator.html)

Create `.env` from `.env.example` and fill in `API_ID` / `API_HASH`. Select a
qualified bundle into `selected.env` using the installation guide, then start:

```sh
docker compose --env-file .env --env-file selected.env up -d --no-build
```

`selected_release: null` means no registry bundle has been accepted yet; use the
[saved-input local build](docs/en/configuration.md#saved-build-inputs) in that case.
Defaults refer to local tags. The gateway binds to localhost, rejects legacy
`/file` access and waits for HTTP readiness. Observability is an opt-in overlay.

[Maintenance EN](docs/en/maintenance.md) · [Обслуживание RU](docs/ru/maintenance.md) ·
[Contributing](CONTRIBUTING.md)
