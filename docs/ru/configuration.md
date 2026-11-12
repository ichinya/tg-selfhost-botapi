---
title: Настройки
translation: /docs/en/configuration.html
---

# Настройки

## Файловые секреты Docker Compose

Для дополнительного secrets overlay нужен Compose версии 2.24.4 или новее.
Храните API ID и hash в отдельных файлах вне репозитория, доступных entrypoint
контейнера, с правами только владельца (0400 или 0600). Локальные файловые
secrets Compose являются bind mount и сохраняют права файлов хоста; это не
зашифрованное хранилище. Укажите пути в `TELEGRAM_API_ID_SECRET_PATH` и
`TELEGRAM_API_HASH_SECRET_PATH`, затем выполните:

```sh
docker compose -f docker-compose.yml -f docker-compose.secrets.yml up -d
```

Для локальной сборки добавьте `-f docker-compose.build.yml` перед secrets-файлом.
Overlay удаляет значения credentials из итогового окружения контейнера.
Прежняя конфигурация через переменные окружения сохраняется.

## Проверка конфигурации doctor

Doctor передаёт подстановку переменных и объединение файлов команде
`docker compose config --format json`. Повторяйте `-f`, `--env-file`, `--profile`
в нужном порядке; `-p` и `--project-directory` выбирают проект. Сохраняются
семантика окружения, неявного `.env` и Docker context. Контейнеры выбираются
по меткам Compose. Отсутствующий/остановленный сервис и доказанное расхождение
блокируют готовность; неоднозначные replicas, нестандартный entrypoint и
недоступные доказательства дают UNKNOWN. Проверяются наличие credentials,
конфликт источников и читаемость mounted secret без вывода значений.

Doctor проверяет work/temp внутри namespace сервера под наблюдаемыми UID/GID
и supplementary groups. Work требует persistent mount; temp может находиться
в слое контейнера. В каждом существующем каталоге создаётся и удаляется один
exclusive probe с таймаутом внутри контейнера. `--no-write-probe` исключает
запись doctor и оставляет проверку записи UNKNOWN. Ошибка удаления блокирует
готовность. Резерв по умолчанию — 1 GiB и 1024 inode на filesystem; флаги
`--min-free-bytes` и `--min-free-inodes` меняют пороги. Общая filesystem work/temp
учитывается один раз. Политика не гарантирует место для будущей нагрузки Telegram.
Пороги должны быть положительными целыми числами. Метаданные mounts проверяются
на включённые квоты; без учёта quota headroom для нужной identity проверка остаётся
UNKNOWN. Exclusive write использует открытый дескриптор в проверенном каталоге;
cleanup удаляет только свой probe после сравнения identity.
Пользователь, группа и дополнительные группы probe должны совпадать с наблюдаемым
процессом сервера; успешная запись от root не заменяет эту проверку. Нужны
существующие канонические каталоги: doctor не создаёт корни, не меняет владельца
или права доступа.

Doctor блокирует override с alias на служебный state root и доступ HTTP-компонента
к backing состояния, в том числе через read-only mount. Штатный nginx проксирует
запросы; его logging map для маскирования поддерживается. Doctor не исправляет
nginx или Compose. Проверка разбирает
поддерживаемые блоки/includes nginx и сопоставляет backing mounts. Динамические
handlers, неразрешённые includes и непроверенные symlinks media дают UNKNOWN.
Binlog, реальные каталоги ботов, statistics и state files не запрашиваются.
Read-only mounts, запрет листинга и публикация на loopback не предотвращают
HTTP-чтение известного файла. Для неподдерживаемого remote file workflow используется
граница #5; doctor не сертифицирует и не запускает соседние helpers.
## Доступ к helper

Оператор задаёт allowlist полных API endpoints в startup-файле. Loopback helper
отдаёт фиксированные routes/assets, не принимает Docker command/container.
Одноразовый bootstrap создаёт HttpOnly SameSite=Strict cookie и CSRF token.
Точные Host/Origin проверки отвергают external/null/file origins. Лимиты:
body 256 KiB, HTTP lifetime десять секунд, шестнадцать соединений и одна фоновая
миграция. Access/body logs отключены. Helper не публикуется через nginx.

## Приватное состояние миграции

Используйте один `MIGRATION_STATE_DIR` на оператора/хост в приватной Linux ФС
вне репозитория, mounts Bot API и webroot (каталог 0700, файлы 0600).
Все интерфейсы используют общую блокировку бота и резерв незавершённой операции.
Windows и state на Windows-диске в WSL не поддерживаются. Проверка документации
отвергает вложенные приватные файлы.

Readiness — свежая проверка протокола без токена и приватное свидетельство
deployment с TTL пять минут: image ID, UID/GID, готовность credentials,
persistent work mount и отдельный доступный temp. Для local-build RepoDigest
не обязателен; temp не обязан быть persistent. Credentials через `_FILE`
поддерживаются. Явная Docker-диагностика создаёт маленькие write probes от
runtime user и не является read-only; HTTP-helper не выбирает контейнеры.
Local mode подтверждается deployment: HTTP/private IP/любой порт разрешены
в local; cloud требует HTTPS, допустимый порт и публичный IPv4.
Несовместимый профиль блокируется до мутаций source. Транспорт ограничивает
DNS/connect/read/total time и body, не наследует proxy, не делает redirects/retry.

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

Bash helper импортирует документированные migration settings из trusted `.env`/`ENV_FILE`, включая `OFFICIAL_BOT_URL`. Полный whitelist указан ниже; per-bot входы отделены от настроек контейнера.

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

Разделение storage включается явно: добавьте `-f docker-compose.files.yml` после
базового Compose. Только Bot API пишет `./media` в `/var/lib/telegram-bot-api-files`
через `TELEGRAM_FILES_DIR` / `--files-dir`. Без override прежний combined layout
остаётся приватным. State, абсолютный private temp, логи и файлы учётных данных
не должны пересекаться с media. Относительные логи, неканонические пути и symlink
в предках отклоняются. Для новых каталогов действует umask `007`, identity —
`101:101`. Права существующего cache рекурсивно не меняются.

`--help` / `--version` работают без credentials. Явные server CLI arguments не
дополняются из env: split CLI требует длинные `--files-dir`, `--dir`, `--temp-dir`,
совпадающие с заданными directory/log env. Повтор directory-флага — ошибка.
Для настройки identity используйте обычный entrypoint; произвольный Compose
`user:` не поддерживается.

`getFile` может вернуть абсолютный путь внутри контейнера. Для прямого чтения
приложению бота нужен согласованный общий volume/путь. Нельзя превращать
произвольный абсолютный путь в HTTP URL скачивания простым склеиванием строк.

Для прямого чтения используйте [пример scoped reader](https://github.com/ichinya/tg-selfhost-botapi/blob/main/examples/files/README.md).
Монтируется только существующая subtree одного бота, RO, по тому же абсолютному
пути. Linux/amd64 opener использует openat2 без symlink и переходов mount,
отклоняет hardlink и special files, передаёт данные из проверенного FD. Вложенные
mount и компрометация доверенного writer/host не входят в deployment-контракт.
Общий stdlib getFile-клиент (`tools/file_contract.py`) ограничивает upstream JSON
до 64 KiB / 30 секунд, не следует redirects и не использует environment proxies.

Ранее описанная схема скачивания с `X-Telegram-Bot-Token` не реализована.
Удалённая выдача включается `docker-compose.downloads.yml` после base+files.
Один handler обслуживает одного бота: `POST /v1/files/download`, JSON только с
`file_id`, отдельный Bearer из `DOWNLOAD_AUTH_TOKEN_FILE`, bot token из
`DOWNLOAD_BOT_TOKEN_FILE`. RO монтируется только настроенная subtree. Loopback
HTTP 18082 должен быть за TLS frontend из
[примера](https://github.com/ichinya/tg-selfhost-botapi/blob/main/examples/files/README.md).
Registry, alias URL и клиентские path/token не принимаются. Запросы и upstream
ответы ограничены; streaming идёт блоками до 64 KiB, четыре slot, socket timeout
30 секунд, общий deadline 600 секунд (`DOWNLOAD_MAX_DURATION`). Коды ошибок,
подготовка, лимиты и ротация auth описаны в примере.

## Текущие ограничения

Короткий флаг каталога файлов `-f` отклоняется: используйте проверяемые длинные
флаги. Значения `file_id`, похожие на путь или URL, отклоняются до запроса upstream.
Поставляемый remote client требует один Content-Length и завершается с ошибкой
при усечённом ответе; после ненулевого exit удалите частично сохранённый файл.

Doctor берёт `--files-dir` из фактического argv (fallback — work), сопоставляет
media/private backings и проверяет scoped RO mounts consumers. Свободная ёмкость
одной FS учитывается один раз. Auth handler и mapping приложения остаются UNKNOWN
до независимой проверки `tools/check_file_contract.py`. Переданный JSON receipt
не даёт READY.

- nginx возвращает 404 для запросов `/file` и `/file/` и не раздаёт каталог состояния.
- В nginx не задан увеличенный лимит загрузки. Большие multipart-запросы могут
  получить HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- По умолчанию gateway доступен только на localhost. Установите в `.env`
  `GATEWAY_BIND=0.0.0.0`, только если удалённым клиентам, например получателю
  webhook, нужен доступ; защитите внешний доступ с помощью HTTPS и сетевых ограничений.
- Access log содержит фиксированные метки метода/маршрута и числовые
  status/bytes/timing. Ошибки запросов отбрасываются через `/dev/null`;
  подробные ошибки nginx недоступны. Внешнему proxy нужна отдельная политика.

[Установка](getting-started.md) · [Обслуживание](maintenance.md)

## Полный профиль webhook

До изменения source helper разрешает `WEBHOOK_SECRET_MODE=provided|none`, `WEBHOOK_IP_MODE=dns|pinned`, `WEBHOOK_CERTIFICATE_MODE=provided|none`, `WEBHOOK_ALLOWED_UPDATES` (JSON-массив строк), `WEBHOOK_MAX_CONNECTIONS`, `WEBHOOK_TARGET_LOCAL=true|false`. Неизвестный секрет/IP и отсутствующий custom certificate останавливают preflight. `fixed` — алиас pinned для canonical IPv4. Source `ip_address` не раскрывает намерение pinning. Явные параметры перекрывают source; отсутствие optional updates означает документированный default `[]`. `[]` исключает chat_member, message_reaction и message_reaction_count, а не включает все типы. Null и неверные типы отклоняются. Per-bot max_connections: 1–100; до 100000 только при явном подтверждении local mode (`TELEGRAM_LOCAL`/`--local`), независимо от серверного `TELEGRAM_MAX_WEBHOOK_CONNECTIONS`. Self-host URL этого не доказывает.

Используйте ровно один из `WEBHOOK_SECRET_TOKEN` и `WEBHOOK_SECRET_TOKEN_FILE` для provided; none явно утверждает отсутствие секрета. В файле разрешён один конечный LF/CRLF; inline-секрет не обрезается. `WEBHOOK_CERTIFICATE_FILE` — публичный PEM, никогда private key. Protected files, включая `BOT_TOKEN_FILE`, должны находиться вне checkout/webroot с доступом только оператору. Process env перекрывает trusted `ENV_FILE` (по умолчанию `.env` рядом с helper), включая явные пустые значения; пары value/file выбираются на одном уровне. Positional URL имеют высший приоритет. Для polling профиль webhook не применяется.

Передача полного профиля включена: urlencoded без сертификата, полностью multipart с сертификатом. Секрет и scalar-файлы — приватные снимки; токен/секрет/URL не попадают в curl argv и shareable diagnostics. Helper отключает trace, применяет curl -q без redirects, проверяет HTTP/ok/result и не повторяет мутации. Для публичного PEM нужны Bash 4+, jq, curl, realpath и проверка openssl X.509; private key отклоняется. Временные файлы создаются с umask 077 и очищаются при выходе/сигналах.

## Таймауты миграции на хосте

Корневой скрипт `migrate_off_to_self.sh` принимает `MIGRATION_CONNECT_TIMEOUT`
(по умолчанию 5 секунд, целое число 1..60) и `MIGRATION_REQUEST_DEADLINE`
(по умолчанию 30 секунд, целое число 1..300). Таймаут соединения не должен
превышать deadline. Deadline относится к одному запросу; проверка без токена
ограничена 10 секундами. Переменная процесса имеет приоритет перед доверенным
файлом окружения; значение по умолчанию используется только для незаданной
переменной. В отличие от адресов, явно пустой таймаут недопустим. Настройки
не передаются в контейнеры.

### Журналы gateway

Базовый Compose монтирует `nginx-main.conf` read-only во всех профилях. Access log
содержит только фиксированные метки метода/маршрута, числовые статус/байты и время.
Неизвестный метод получает OTHER, неизвестный путь — other. Ошибки запросов
отбрасываются через `error_log /dev/null`, включая наследуемые контексты.
Для диагностики используйте статусы и время; подробные ошибки nginx недоступны.
Внешнему proxy нужна отдельная политика. Doctor распознаёт только точные maps
с фиксированными метками, другая logging policy остаётся UNKNOWN.

### Диагностика нативного Bot API

Собственная сборка включает policy `issue17-v1`: Query log содержит счётчики,
webhook log исключает private state, а log sink преобразует каждое событие
native/TDLib в фиксированную метку severity до записи в файл и memory log.
Подробные нативные сообщения недоступны. Поддерживаются file/memory verbosity
0..3; большие значения при старте отклоняются, повышение во время работы ограничено.
Crash diagnostics исключает actor tags и debugger locals; entrypoint отключает
core dumps. Гарантия требует проверенного собственного image/digest, а не любого
upstream образа через BOTAPI_IMAGE. Private webhook state и исходящие secret
headers сохраняют исходные байты. Вывод версии остаётся доступен.
