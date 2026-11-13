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
Файлы credentials должны быть непустыми обычными файлами, доступными для чтения
пользователю сервера; каталоги и FIFO отклоняются без чтения. `docker compose config`
проверяет структуру конфигурации, а entrypoint проверяет credentials при запуске.

Gateway и необязательный downloads ожидают HTTP-готовности Bot API. Эта проверка
не подтверждает авторизацию бота и не гарантирует восстановление при unhealthy.
Для остановки Bot API задано 120 секунд; измерьте время на своих данных и при
необходимости увеличьте его до создания резервной копии остановленного сервиса.
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
Managed readiness наблюдает сервер с PID 1 и сверяет UID, GID и нормализованный
набор дополнительных групп probe до чтения секретов и записи. Несовпадение или
смена процесса блокирует evidence. Внешний формат v1 сохраняет UID/GID и не
удостоверяет набор групп отдельным полем.
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
| Временные загрузки gateway | Project-scoped volume `gateway_client_temp` в `/var/cache/nginx/client_temp` |
| Каталог данных в контейнере | `/var/lib/telegram-bot-api` |
| UID/GID сервера по умолчанию | `101:101` |
| Local mode | Включён в Compose |

По умолчанию контейнер начинает работу от root только для подготовки новых или
пустых каталогов состояния и временных файлов, затем запускает сервер как
`101:101`. Владельцы непустых каталогов и их содержимого не меняются. Docker
`--user UID:GID` или Compose `user: "UID:GID"` запускает сервер сразу с указанной
identity; оба каталога нужно подготовить заранее. Используйте отдельные абсолютные
пути без символических ссылок в компонентах. Доступ проверяется от пользователя
сервера. Новые приватные каталоги имеют `0700`, umask сервера — `0027`; права
существующих каталогов не меняются. Файлы секретов `_FILE` должны читаться
конечным пользователем сервера. Доступ к файлу журнала проверяет сам сервер.
Явные аргументы entrypoint, например `--version`, обходят обычную подготовку и
выполняются от пользователя контейнера.

Bot API endpoint принимает вызовы методов. Webhook URL находится в вашем
приложении и принимает обновления от сервера. Это разные адреса.

## Переменные Compose

Необязательный `docker-compose.nonroot.yml` требует `BOTAPI_UID`, `BOTAPI_GID`,
`BOTAPI_STATE_SOURCE` и `BOTAPI_TEMP_SOURCE`. Они задают пользователя Compose и
подготовленные bind-каталоги, а не меняют учётные записи в образе. Порядок и
подготовка описаны в разделе [установки](getting-started.md).

Необязательный `TELEGRAM_FILES_DIR` задаёт отдельный upstream `--files-dir`;
без него используется рабочий каталог по умолчанию. Каталоги состояния, HTTP
temp и media должны быть отдельными абсолютными путями без символических ссылок.
Изменение настройки не переносит старые файлы и пути кеша. Media override требует
non-root override и подготовленный `BOTAPI_MEDIA_SOURCE`.

| Переменная в `.env` | Назначение |
| --- | --- |
| `API_ID` | Обязательный API ID приложения |
| `API_HASH` | Обязательный API hash приложения |
| `GATEWAY_BIND` | Адрес gateway на хосте; по умолчанию `127.0.0.1` |
| `BOTAPI_IMAGE` | Локальный тег по умолчанию для config; для развёртывания нужен проверенный immutable ref |
| `OBSERVER_IMAGE` | Локальный тег по умолчанию для config; для развёртывания нужен проверенный immutable ref |
| `GATEWAY_IMAGE` | Локальный тег по умолчанию для config; для развёртывания нужен проверенный immutable ref |

Для развёртывания используйте refs из проверенного release receipt. Созданный
`.env.build` содержит входы локальной сборки. Без refs базовый `up` завершится
ошибкой загрузки gateway, если локального образа с резервным тегом нет.

Для проверенной сборки:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi@sha256:<qualified-botapi-digest>
OBSERVER_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi-observer@sha256:<qualified-observer-digest>
GATEWAY_IMAGE=nginx@sha256:<qualified-gateway-digest>
```

Локальный build override использует образ
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

Разделение storage включается явно: после базового Compose добавьте
`-f docker-compose.nonroot.yml`, затем `-f docker-compose.files.yml`. Только Bot API
пишет `BOTAPI_MEDIA_SOURCE` в `/var/lib/telegram-bot-api-files`
через `TELEGRAM_FILES_DIR` / `--files-dir`. Без override прежний combined layout
остаётся приватным. State, абсолютный private temp, логи и файлы учётных данных
не должны пересекаться с media. Относительные логи, неканонические пути и symlink
в предках отклоняются. Для новых каталогов действует umask `0027`, media принадлежит
настроенным non-root UID/GID. Права существующего cache рекурсивно не меняются.

`--help` / `--version` работают без credentials. Явные server CLI arguments не
дополняются из env: split CLI требует длинные `--files-dir`, `--dir`, `--temp-dir`,
совпадающие с заданными directory/log env. Повтор directory-флага — ошибка.
Для настройки identity используйте поддерживаемый non-root override; произвольный
Compose `user:` не поддерживается.

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
- Для методов Bot API, принимающих файлы, лимит тела — `2048m` (2 147 483 648 байт),
  включая multipart-поля и все вложения; превышение даёт HTTP 413. Буферизация
  запроса включена: до передачи upstream тело сохраняется на отдельном дисковом
  volume. Для загрузок таймауты простоя чтения от клиента и отправки upstream — 300 секунд,
  чтения ответа — 600 секунд, соединения — 5 секунд. Это не общие deadlines.
  Upstream указывает до 2000 MB на файл в local mode; лимит gateway относится ко
  всему телу, поэтому вложения делят общий бюджет. Из 2048 MiB остаётся 48 MiB
  сверх 2000 MiB для multipart. Ограничения метода, образа, клиента и внешнего
  ingress сохраняются; успешная загрузка в Telegram не гарантирована. У pinned
  upstream есть собственный предел простоя около 500 секунд, nginx его не продлевает.

  Буферизация добавляет дисковый I/O и задерживает передачу до полного приёма.
  Для N параллельных загрузок рассчитывайте до N × 2 GiB плюс резерв только для
  nginx: при N=2 это около 4 GiB плюс резерв. Добавьте потребности Bot API в
  temp/work/cache на той же файловой системе. Volume не резервирует место или
  квоту, а стандартный резерв Doctor 1 GiB не подтверждает готовность к большим
  загрузкам. Проверяйте байты и inode, включая диск Docker Desktop. Spool может
  содержать конфиденциальные данные; ограничьте доступ. Допускаются две загрузки
  на адрес и четыре всего: зарезервируйте минимум 8 GiB плюс рабочий запас. Частота
  начала загрузок — 2/с на адрес (burst 4) и 10/с общая (burst 20); превышение
  возвращает 429. Ingress должен сохранять адрес клиента: nginx не доверяет
  forwarded-заголовкам. Разрешены GET, HEAD и POST; тела GET/HEAD отклоняются,
  остальные методы получают 403.

  Обычные RPC ограничены 1 MiB; таймаут простоя тела/отправки — 15 секунд,
  чтения ответа — 30 секунд. Для `getUpdates` чтение — 600 секунд. Публичный
  порт 80 до чтения тела отклоняет Transfer-Encoding с 411: передавайте загрузки
  с Content-Length. Внутренний порт 82 принимает chunked и не опубликован в
  Compose; открывайте его только доверенным клиентам. Idle-таймаут не ограничивает
  полное время: медленный Content-Length может удерживать слот неограниченно.
  Для недоверенного доступа используйте ingress с абсолютным deadline или
  минимальной скоростью и проверкой допуска до чтения тела.
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

## Безопасная статистика

`TELEGRAM_STAT` по умолчанию false. При включении raw stats слушает только
127.0.0.1:8082 внутри namespace Bot API. Публиковать или проксировать этот порт нельзя.
Observer принимает проверенный tab-separated формат manager и выдаёт только
числовые наблюдения. Coverage очереди всегда sampled: пропущенный pending означает
unknown, сумма выборки — нижняя граница, а не глобальный итог.
Неверные, повторные, слишком большие, Closing и несовместимые ответы дают unavailable.

## Развёртывание и изоляция observer

Перед Compose up подготовьте входы на Linux host:

```sh
install -d -m 0700 .observability
install -d -m 0755 .observability/runtime .observability/migration
sudo install -d -o 101 -g 101 -m 0700 .observability/registry .observability/credentials
python3 tools/image_inputs.py --build-env .env.build
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Observer делит только network namespace Bot API, работает как 101:101 с read-only
root и сброшенными capabilities, без Docker socket, state/temp и private migration
dossier mounts. Пустые каталоги работают без bot credentials. Management на host:
`http://127.0.0.1:18081`; проксируются только три точных пути, GET/HEAD, без query,
body и Authorization. API listener 18080 закрывает эти пути. Отложенный Docker DNS
позволяет nginx стартовать без target; management upstream errors дают фиксированный
503. Management 4xx от nginx могут содержать стандартные HTML-страницы ошибок.
Порты API 8082/8090 зарезервированы. Custom API port требует nginx override и
doctor. Raw stats остаётся на loopback. Доступ к observer 8090 доверен только сети
Compose; публиковать его как monitoring ingress нельзя.

Doctor проверяет контексты routes и владельца namespace. Неизвестные переменные,
лишние management routes, публичный management bind, raw stats proxy, state/socket
mounts и неверный namespace owner дают fail или unknown. Doctor — preflight и
не заменяет continuous health или доказательства доставки. База — pinned Alpine;
APK repositories Python/curl/jq остаются изменяемыми. Immutable пара фиксирует
результат сборки; побайтовая воспроизводимость не обещается.

Опубликованный observer использует digest-pinned Python base, разрешённую CI.
Локальный fallback — pinned Alpine с APK Python; для release base задайте
OBSERVER_BASE с approved Python image digest. Supervision host producer,
права registry/credentials и ownership/rotation описаны в
[обслуживании](maintenance.md). Ready секции описывает её источник наблюдения;
исходы миграции проверяются отдельно от готовности процесса.

## Сохранённые входы сборки

`image-inputs.lock.json` — датированный снимок обнаруженных source/base, ещё без квалификации.
Повторение работает без сети: `python3 tools/image_inputs.py --build-env .env.build --json-file /private/resolved.json`.
Сборка: `docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --build`.
Храните сгенерированные входы закрыто. Observer использует одинаковую базу Alpine локально и в CI;
необязательный downloads — сохранённую базу Python. Discovery запускается явно (`--save-discovery /private/candidate.json`),
сохраняя выбранную ревизию сервера до отдельного review обновления исходников. PR повторяет сохранённый снимок.
Ключ сборки исключает deployment digests и документацию; у квалификации отдельный ключ.
Local build overlay и downloads явно выбирают `linux/amd64`; эмуляция не
квалифицирует native ARM64 release.
Исторические digest требуют повторной проверки registry/platform/support в CI до выбора выпуска.

Test-only sender artifact сохраняется по digest вместе с runtime; reuse скачивает
его без повторной компиляции. Отсутствие парного test artifact запрещает reuse до восстановления evidence.
После commit изменений упаковки выполните `--capture-wrapper /private/source-inputs.json`,
затем повторите файл через `--inputs-file`, чтобы записать фактический commit обёртки.
