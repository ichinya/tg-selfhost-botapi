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

Bash-помощник миграции считывает из доверенного файла `.env` только `SELF_BOT_URL`, `TELEGRAM_BOT_URL`, `WEBHOOK_URL`, `WEB_HOOK` и `DROP_PENDING_UPDATES`; остальные значения из файла не экспортируются в окружение помощника. `OFFICIAL_BOT_URL` — расширенная настройка для тестовой подмены исходного endpoint; она читается из окружения процесса, а не из файла.

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
Локальный reader принимает один `file_id`, вызывает getFile на приватном endpoint
оператора и читает исходный абсолютный путь без преобразования в URL. Read-only
mount содержит только полный token/DC каталог своего бота по тому же абсолютному
пути. Одного numeric bot ID недостаточно: test DC добавляет `:T`, альтернативный
layout заменяет `:` на `~`. Token читается из отдельного защищённого regular file
(владелец root/reader, mode `0640` или строже, без symlink/hardlink), не из аргумента.

Общий opener требует Linux/amd64, kernel >= 5.6 и рабочий openat2 под seccomp.
Он закрепляет root и открывает один regular single-link FD внутри него. Symlink,
nested mount, traversal и внешние пути отклоняются без pathname fallback.
Изоляцию local-доступа задают mounts и Unix permissions. Writer и оператор
доверенные; FD не создаёт snapshot изменяемого writer файла.

После подготовки приватных путей и проверенной пары образов по инструкции
`examples/files/README.md` local reader запускается так:

```sh
docker compose -f docker-compose.yml -f examples/files/compose.local.yml run --rm reader '<FILE_ID>' > downloaded.bin
```

### Удалённая выдача (opt-in)

Базовый gateway не предоставляет HTTP-скачивание файлов. Отдельный handler
принимает `POST /downloads/<bot-alias>`, ровно `Content-Type: application/json`,
один `Authorization: Bearer <DOWNLOAD_CREDENTIAL>` и только
`{"file_id":"<FILE_ID>"}`. Приватный registry связывает alias с уникальным credential
из не менее 32 случайных символов, полным Telegram token/DC, endpoint и bot-root.
Клиент не задаёт path, token, endpoint или root. Лишние/дублированные JSON keys,
query string, повторные auth/framing headers, chunked body и legacy auth запрещены.

Нет credential, неверный/отозванный/дублированный credential — 401. Валидный
credential к чужому либо неизвестному alias — одинаковый 403 до getFile/open.
Неверный input/Content-Type — 400, method — 405, Range — 416, превышение размера —
413, отсутствующий/запрещённый файл — 404, upstream failure/timeout — 502/504,
перегрузка — 503. Успех: octet-stream, фиксированное attachment имя, Content-Length
из FD, no-store/nosniff. Приватные пути и raw upstream diagnostics не возвращаются.

Лимиты: 4 workers и очередь 8; headers/body <= 16 KiB; file_id <= 1024 байт UTF-8;
upstream connect/read 5/60 секунд; client idle 30 секунд; chunks 64 KiB.
HEAD/Range/resume и прозрачных retries нет. Ошибка после начала stream закрывает
соединение без добавления JSON. Для отзыва смените credential в приватном registry
и пересоздайте handler. Нужен HTTPS, Telegram token остаётся на сервере.
Недоверенные клиенты не должны иметь прямого доступа к local Bot API: handler
не обеспечивает tenant-изоляцию всех его методов.

После приватного заполнения `.env` и registry:

```sh
docker compose -f docker-compose.yml -f docker-compose.downloads.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.downloads.yml up -d downloads downloads-gateway
curl --config /absolute/private/download.curl --fail-with-body \
  --header 'Content-Type: application/json' --data '{"file_id":"<FILE_ID>"}' \
  https://downloads.example.com/downloads/bot-a --output downloaded.bin
```

Bearer header хранится в приватном curl-файле. Backend не публикует host port;
отдельный proxy слушает `127.0.0.1:18082`, disk buffering/cache отключены.
Используйте `examples/files/nginx.downloads-tls.conf` на HTTPS ingress оператора.
Каждому боту нужен отдельный read-only bind; отсутствующий source останавливает
запуск. Registry/token находятся вне media; token/DC пути нельзя публиковать.

## Разделённое хранение

Compose хранит приватное состояние в `./data` (`/var/lib/telegram-bot-api`), а медиа
в `./files` (`/var/lib/telegram-bot-api-files`). `TELEGRAM_FILES_DIR` передаётся как
`--files-dir`; без переменной отдельный образ сохраняет upstream legacy default.
Entry point отклоняет неканонические, пересекающиеся пути и symlink в предках.
Temp и журналы должны быть вне media; относительный `TELEGRAM_LOG_FILE` считается
от `TELEGRAM_WORK_DIR`. Явные CLI-аргументы обходят проверку профиля и переменных;
`--help` и `--version` доступны без API credentials.

Writer работает как `101:101`, media root должен иметь владельца `101:101` и mode
`770`, umask writer — `007`. Подготовьте только нужный bot-root с mode `2750`;
reader `10001:101` получает group read/traverse либо адресный ACL оператора.
Рекурсивные chown/chmod состояния не выполняются. Несовместимый владелец или mode
существующего media root останавливает запуск. Реальные права файлов TDLib должен
подтвердить runtime gate проверенной пары образов: umask и shell fixture этого
сами по себе не доказывают.

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
