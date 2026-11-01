---
title: Настройки
translation: /docs/en/configuration.html
---

# Настройки

## Адреса и хранение

| Настройка | Значение |
| --- | --- |
| Порт gateway на хосте | `18080` |
| Внутренний адрес Bot API | `http://botapi:8081` |
| Постоянные данные на хосте | `./data` |
| Каталог данных в контейнере | `/var/lib/telegram-bot-api` |
| UID/GID пользователя контейнера | `101:101` |
| Local mode | Включён в Compose |

Bot API endpoint принимает вызовы методов. Webhook URL находится в вашем
приложении и принимает обновления от сервера. Это разные адреса.

## Переменные Compose

| Переменная в `.env` | Назначение |
| --- | --- |
| `API_ID` | Обязательный API ID приложения |
| `API_HASH` | Обязательный API hash приложения |
| `BOTAPI_IMAGE` | Необязательный тег или digest; по умолчанию `ghcr.io/ichinya/tg-selfhost-botapi:latest` |

Для проверенной сборки:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi:build-<key>
```

Вместо тега можно указать digest. Локальный build override использует образ
`tg-selfhost-botapi:local` независимо от `BOTAPI_IMAGE`.

## Переменные контейнера

Они настраивают entrypoint образа. В текущем Compose переменные
`API_ID/API_HASH` передаются как `TELEGRAM_API_ID/TELEGRAM_API_HASH`.

| Переменная | Назначение / значение по умолчанию |
| --- | --- |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Обязательные учётные данные |
| `TELEGRAM_API_ID_FILE`, `TELEGRAM_API_HASH_FILE` | Чтение соответствующих данных из смонтированного файла |
| `TELEGRAM_WORK_DIR` | Каталог состояния; задаётся образом |
| `TELEGRAM_TEMP_DIR` | Временный каталог; задаётся образом |
| `TELEGRAM_HTTP_PORT` | Порт Bot API; `8081` |
| `TELEGRAM_LOCAL` | Local mode; Compose задаёт `true` |
| `TELEGRAM_STAT` | Статистика на порту `8082`; по умолчанию выключена |
| `TELEGRAM_LOG_FILE`, `TELEGRAM_VERBOSITY` | Путь журнала и уровень логирования |
| `TELEGRAM_FILTER` | Фильтр по user ID бота |
| `TELEGRAM_MAX_CONNECTIONS`, `TELEGRAM_MAX_WEBHOOK_CONNECTIONS` | Лимиты соединений |
| `TELEGRAM_PROXY` | HTTP proxy для исходящих webhook |
| `TELEGRAM_HTTP_IP_ADDRESS` | Адрес прослушивания Bot API |

Булевы флаги принимают `true/false` и `1/0`. Не задавайте одновременно значение
учётных данных и его вариант `_FILE`. Для файловых секретов нужны монтирование и
изменение environment сервиса: одной записи `_FILE` в `.env` недостаточно.

Endpoint статистики оставляйте внутренним: upstream может выводить токены ботов.
nginx сейчас обращается к порту `8081`; изменение порта контейнера требует
соответствующей правки nginx.

## User-Agent webhook

При сборке к официальному серверу применяется `patches/webhook-user-agent.patch`.
Обновления отправляются с `User-Agent: TelegramBotWebhook/1.0`. Входящие заголовки
nginx или запрос `setWebhook` этот исходящий заголовок не настраивают.

## Файлы в local mode

`getFile` может вернуть абсолютный путь внутри контейнера. Для прямого чтения
приложению бота нужен согласованный общий volume/путь. Нельзя превращать
произвольный абсолютный путь в HTTP URL скачивания простым склеиванием строк.

Ранее описанная схема скачивания с `X-Telegram-Bot-Token` не реализована.
Авторизованная удалённая выдача файлов запланирована в
[issue #5](https://github.com/ichinya/tg-selfhost-botapi/issues/5).

## Текущие ограничения

- nginx раздаёт каталог состояния через `/file/`; это не авторизованный файловый
  API. Ограничьте доступ; [issue #3](https://github.com/ichinya/tg-selfhost-botapi/issues/3).
- В nginx не задан увеличенный лимит загрузки. Большие multipart-запросы могут
  получить HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- Публикация `18080:80` в Compose не ограничивает доступ адресом localhost.
- Не публикуйте необработанные журналы и диагностику с токенами в URL.

[Установка](getting-started.md) · [Обслуживание](maintenance.md)
