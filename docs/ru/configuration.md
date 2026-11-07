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
| `GATEWAY_BIND` | Адрес gateway на хосте; по умолчанию `127.0.0.1` |
| `BOTAPI_IMAGE` | Необязательный тег или digest; по умолчанию `ghcr.io/ichinya/tg-selfhost-botapi:latest` |

Для проверенной сборки:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi:build-<key>
```

Вместо тега можно указать digest. Локальный build override использует образ
`tg-selfhost-botapi:local` независимо от `BOTAPI_IMAGE`.

## Окружение помощника миграции

Это настройки host-side утилиты, не окружение контейнера. Здесь точный whitelist доверенного файла; остальные ключи игнорируются. `OFFICIAL_BOT_URL` — только из процесса для изолированных тестов. Приоритет по присутствию и семантика пустоты: [миграция](migration.md).

| Переменная | Значение |
| --- | --- |
| `SELF_BOT_URL`, `TELEGRAM_BOT_URL` | Целевой Bot API; legacy alias |
| `WEBHOOK_URL`, `WEB_HOOK` | Receiver URL; игнорируется polling/preserve |
| `WEBHOOK_ACTION` | Обязательно: preserve / set / polling; без default |
| `DROP_PENDING_UPDATES` | true / false; default false; только target mutation |
| `WEBHOOK_TARGET_LOCAL` | true / false; default false; подтверждение оператором --local |
| `WEBHOOK_SECRET_MODE` | `provided` / `none`; явный выбор обязателен для webhook |
| `WEBHOOK_SECRET_TOKEN`, `WEBHOOK_SECRET_TOKEN_FILE` | Приватное значение secret ИЛИ читаемый файл; API alphabet, 1-256 символов |
| `WEBHOOK_ALLOWED_UPDATES` | JSON-массив строк; default []; пустая строка невалидна |
| `WEBHOOK_MAX_CONNECTIONS` | Целое; default 40; cloud 1-100, подтверждённый local до 100000 и server limit |
| `WEBHOOK_IP_MODE`, `WEBHOOK_IP_ADDRESS` | `dns` / `fixed`; fixed требует явного IP; observed IP не подтверждает policy |
| `WEBHOOK_CERTIFICATE_MODE`, `WEBHOOK_CERTIFICATE_FILE` | `provided` / `none`; Для provided читаемый непустой публичный PEM; private key запрещён; нужен openssl |

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
Обновления отправляются с `User-Agent: WebhookDelivery/1.0`. Нейтральное имя не
содержит `bot`, по которому получатели могут блокировать роботов. Входящие заголовки
nginx или запрос `setWebhook` этот исходящий заголовок не настраивают.

## Файлы в local mode

`getFile` может вернуть абсолютный путь внутри контейнера. Для прямого чтения
приложению бота нужен согласованный общий volume/путь. Нельзя превращать
произвольный абсолютный путь в HTTP URL скачивания простым склеиванием строк.

Ранее описанная схема скачивания с `X-Telegram-Bot-Token` не реализована.
Авторизованная удалённая выдача файлов запланирована в
[issue #5](https://github.com/ichinya/tg-selfhost-botapi/issues/5).

## Текущие ограничения

- nginx передаёт запросы `/file/` в Bot API и не раздаёт каталог состояния.
- В nginx не задан увеличенный лимит загрузки. Большие multipart-запросы могут
  получить HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- По умолчанию gateway доступен только на localhost. Установите в `.env`
  `GATEWAY_BIND=0.0.0.0`, только если удалённым клиентам, например получателю
  webhook, нужен доступ; защитите внешний доступ с помощью HTTPS и сетевых ограничений.
- Access log скрывает токены ботов и исключает query string. Для error log nginx
  задан порог `crit`, чтобы исключить ошибки со строкой запроса; предупреждения и
  ошибки уровня `error` при этом не записываются. Критические сообщения всё ещё
  могут содержать секреты: фильтруйте журналы перед передачей и не публикуйте
  необработанную диагностику.

[Установка](getting-started.md) · [Обслуживание](maintenance.md)
