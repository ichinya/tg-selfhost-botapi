---
title: Documentation
permalink: /docs/en/
translation: /docs/ru/
---

# TG Selfhost Bot API

Run the official Telegram Bot API server in Docker with an independent entrypoint,
a webhook User-Agent patch, and migration helpers.

## Guides

- [Getting started](getting-started.md) — install, build or pull an image, verify the service.
- [Configuration](configuration.md) — ports, environment variables, files and access.
- [Migration](migration.md) — cloud/local transitions and the current helper limitations.
- [Maintenance](maintenance.md) — image updates, backups, diagnostics and documentation.

[Русская версия](../ru/README.md) · [Browser migration tool](../../tg_selfhost_botapi_migrator.html)

## Components

| Component | Role |
| --- | --- |
| Official tdlib server | Bot API implementation |
| This project's image | Builds the server, applies the webhook patch and starts it from environment variables |
| nginx gateway | Forwards HTTP requests to the server |
| Bash helper | Automates cloud → local migration with a confirmation step |
| Browser tool | Reads an explicitly selected source with consent; executes cloud → local or webhook-only; gives manual stages for local transitions |

The build does not depend on aiogram. Their project packages the same official
server; this repository maintains its own Docker packaging.

The image pipeline supports `linux/amd64`. Publication and scheduled builds require
the image workflow to be merged into the default branch and its first successful
release. A configured image name alone does not mean the image has been published.

Implementation work is tracked in [issues](https://github.com/ichinya/tg-selfhost-botapi/issues/19).
