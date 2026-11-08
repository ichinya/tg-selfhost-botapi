---
title: Настройки
translation: /docs/en/configuration.html
---

# Настройки

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

## Полный профиль webhook

До изменения source helper разрешает `WEBHOOK_SECRET_MODE=provided|none`, `WEBHOOK_IP_MODE=dns|pinned`, `WEBHOOK_CERTIFICATE_MODE=provided|none`, `WEBHOOK_ALLOWED_UPDATES` (JSON-массив строк), `WEBHOOK_MAX_CONNECTIONS`, `WEBHOOK_TARGET_LOCAL=true|false`. Неизвестный секрет/IP и отсутствующий custom certificate останавливают preflight. `fixed` — алиас pinned для canonical IPv4. Source `ip_address` не раскрывает намерение pinning. Явные параметры перекрывают source; отсутствие optional updates означает документированный default `[]`. `[]` исключает chat_member, message_reaction и message_reaction_count, а не включает все типы. Null и неверные типы отклоняются. Per-bot max_connections: 1–100; до 100000 только при явном подтверждении local mode (`TELEGRAM_LOCAL`/`--local`), независимо от серверного `TELEGRAM_MAX_WEBHOOK_CONNECTIONS`. Self-host URL этого не доказывает.

Используйте ровно один из `WEBHOOK_SECRET_TOKEN` и `WEBHOOK_SECRET_TOKEN_FILE` для provided; none явно утверждает отсутствие секрета. В файле разрешён один конечный LF/CRLF; inline-секрет не обрезается. `WEBHOOK_CERTIFICATE_FILE` — публичный PEM, никогда private key. Protected files, включая `BOT_TOKEN_FILE`, должны находиться вне checkout/webroot с доступом только оператору. Process env перекрывает trusted `ENV_FILE` (по умолчанию `.env` рядом с helper), включая явные пустые значения; пары value/file выбираются на одном уровне. Positional URL имеют высший приоритет. Для polling профиль webhook не применяется.

Передача полного профиля включена: urlencoded без сертификата, полностью multipart с сертификатом. Секрет и scalar-файлы — приватные снимки; токен/секрет/URL не попадают в curl argv и raw diagnostics. Helper отключает trace, применяет curl -q без redirects, проверяет HTTP/ok/result и не повторяет мутации. Для публичного PEM нужны Bash 4+, jq, curl, realpath и проверка openssl X.509; private key отклоняется. Временные файлы создаются с umask 077 и очищаются при выходе/сигналах.
