---
title: Установка
translation: /docs/en/getting-started.html
---

# Установка

Для скачивания файлов нужен явный split-storage override и scoped reader:
см. [настройки](configuration.md) и
[исполняемые примеры](https://github.com/ichinya/tg-selfhost-botapi/blob/main/examples/files/README.md).
Не добавляйте абсолютный getFile-путь к HTTP URL. Отсутствующая bot subtree —
ошибка; не устраняйте её монтированием всего private cache.

Перед запуском задайте в `.env` проверенные refs образов из release receipt,
включая `GATEWAY_IMAGE`. Во всех командах file-enabled установки сохраняйте
порядок Compose-файлов:

```sh
# Подготовьте BOTAPI_STATE_SOURCE, BOTAPI_TEMP_SOURCE и BOTAPI_MEDIA_SOURCE
# для BOTAPI_UID:BOTAPI_GID по инструкции ниже и задайте их в .env.
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml up -d
# Локальный reader после настройки private bindings из примера:
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml \
  -f examples/files/compose.local.yml run --rm reader '<FILE_ID>' > downloaded.bin
# Per-bot handler: нужны проверенный DOWNLOADS_IMAGE и защищённые файлы:
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml \
  -f docker-compose.downloads.yml up -d
```

Для локальной сборки Bot API вставьте `-f docker-compose.build.yml` сразу после
base и используйте `up -d --build`. Для сборки downloads по сохранённым входам
добавьте `-f docker-compose.downloads.build.yml` после `docker-compose.downloads.yml`
и выполните `docker compose --env-file .env.build -f docker-compose.yml -f docker-compose.files.yml -f docker-compose.downloads.yml -f docker-compose.downloads.build.yml build downloads`.
В `DOWNLOADS_IMAGE` задавайте candidate, прошедший file gate. API — порт 18080;
downloads HTTP — loopback 18082 за TLS frontend из примера.

## Локальный UI миграции

Нужны Linux/WSL, Python 3.11+ и приватное состояние на Linux ФС. Создайте
helper JSON с правами 0600 вне checkout:

```json
{"state_dir":"/home/operator/.local/state/tg-selfhost-botapi/migrations","allowed_endpoints":["https://api.telegram.org","http://bot-api.internal:8081"],"evidence_file":"/home/operator/private/deployment.json","trust_file":"/home/operator/private/providers.json","fixture":false}
```

Отдельно подготовьте свежее deployment evidence и независимые trusted provider
keys; без них реальные внешние checkpoints блокируются. Запустите явно:

```sh
python3 tools/migration_helper.py --config "$HELPER_CONFIG" --bootstrap-file "$PAIRING_FILE" --port 8765
```

Выберите новый `PAIRING_FILE` в принадлежащем оператору каталоге с правами 0700
вне checkout, журнала и mounts Bot API. Helper создаст файл с правами 0600 и
откажется перезаписывать существующий. Прочитайте код приватно из файла и введите
его на `http://127.0.0.1:8765/`; в стартовые логи код не выводится.
Код действует пять минут, сессия — один час. Для новой сессии перезапустите helper
с новым файлом кода.
UI/API работают с одного origin. Pages только объясняет запуск. Удалённый хост:
`ssh -N -L 8765:127.0.0.1:8765 operator@HOST`, затем тот же локальный URL.

## Требования

- Docker с Compose v2.
- Для doctor: Python 3.11+ на host (только stdlib). Полная runtime-проверка требует
  локального Linux Engine с доступом к bridge; pure-проверки работают и на Windows.
- API ID и API hash приложения Telegram с [my.telegram.org](https://my.telegram.org).
- Для миграции: Linux/WSL, Python 3.11+; совместимому Bash-адаптеру также нужны
  curl, jq и GNU coreutils на POSIX-хосте (`mktemp`, `date`, `stat`, `mkdir`,
  `mv`, `chmod`, `rm`, `rmdir`, `cat`) для сохранённого standalone-варианта.
  Приватной диагностике нужны POSIX-права только для владельца; runtime-проверка
  в Windows отложена до Linux CI.
- Node 24 нужен для разработки/UI-приёмки, а не для работы helper.

API ID/hash приложения и токен бота от BotFather — разные учётные данные.

## Подготовка

```sh
git clone https://github.com/ichinya/tg-selfhost-botapi.git
cd tg-selfhost-botapi
cp .env.example .env
install -d -m 0700 .observability
install -d -m 0755 .observability/runtime .observability/migration
sudo install -d -o 101 -g 101 -m 0700 .observability/registry .observability/credentials
```

Заполните `API_ID` и `API_HASH` в `.env`. Не публикуйте этот файл.
Compose проверяет структуру, а entrypoint отклоняет незаданные и пустые credentials
до запуска сервера. Файловые секреты читаются пользователем сервера; применяйте
`docker-compose.secrets.yml` последним, в том числе после overlay локальной сборки.

По умолчанию gateway слушает `127.0.0.1` и не раздаёт каталог состояния.

Перед большими загрузками подготовьте место и inode для отдельного volume
`gateway_client_temp` и хранилища Bot API. Worker nginx должен иметь право записи
в spool. Расчёт приведён в [настройках](configuration.md).
Если удалённым клиентам, включая получатель webhook, нужен доступ к Bot API,
задайте `GATEWAY_BIND=0.0.0.0` в `.env` и обеспечьте HTTPS и сетевые ограничения.

## Запуск

Для произвольных UID/GID создайте отдельные пустые bind-каталоги вне webroot:

```sh
sudo install -d -m 0700 -o 1000 -g 1000 /srv/botapi/data /srv/botapi/scratch
```

В `.env` задайте `BOTAPI_UID=1000`, `BOTAPI_GID=1000`,
`BOTAPI_STATE_SOURCE=/srv/botapi/data` и `BOTAPI_TEMP_SOURCE=/srv/botapi/scratch`.

```sh
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml up -d
```

Для локальной сборки добавьте после override `-f docker-compose.build.yml` и
`--build`. Оба bind-каталога должны существовать заранее. Для именованных томов
нужна отдельная конфигурация Compose. Каждый новый пустой том можно один раз
подготовить root-контейнером, подставив имя тома и ID:

```sh
docker run --rm --user 0:0 -v botapi-state:/volume alpine:3.22 sh -c 'chown 1000:1000 /volume && chmod 700 /volume'
```

Повторите для отдельного временного тома. Не применяйте команду к существующим
данным; владелец в слое образа не подготавливает монтируемый том.

Для ограниченного чтения media используйте writer с основной группой `2000`:
подготовьте приватные state и scratch для `1000:2000`, отдельный media-каталог
владельца `1000:2000` с правами `0700`. Задайте `BOTAPI_UID=1000`,
`BOTAPI_GID=2000`, абсолютный `BOTAPI_MEDIA_SOURCE` и добавьте после non-root
override файл `-f docker-compose.files.yml`. Gateway не получает storage.
Передавайте reader только одно конечное поддерево media бота, не корень бота,
download temp, приватный state или соседних ботов. Приватно задайте
`BOT_MEDIA_SUBDIR` как путь к поддереву бота на хосте: имя может содержать
чувствительные данные. Для подготовленного при остановленных writers поддерева
`documents` каталоги должны разрешать группе чтение и поиск (не шире `0750`),
файлы — чтение (не шире `0640`). Проверка на синтетическом файле:

```sh
docker run --rm --user 2001:3000 --group-add 2000 \
  --mount "type=bind,src=$BOT_MEDIA_SUBDIR/documents,dst=/media,readonly" \
  alpine:3.22 cat /media/synthetic.txt
```

Предварительно создайте там синтетический файл от writer с правом чтения для
группы. Не выводите приватный путь в публичный журнал. Временные файлы загрузки
находятся внутри media, не в `TELEGRAM_TEMP_DIR`; основная группа writer
сохраняется при rename внутри файловой системы. Reader не получает Docker socket
или права монтирования. Проверка не подтверждает реальную загрузку Telegram.

До первой публикации в GHCR используйте локальную сборку:

```sh
RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
python3 tools/image_inputs.py --capture-wrapper "$RUNNER_TEMP/source-inputs.json"
python3 tools/image_inputs.py --inputs-file "$RUNNER_TEMP/source-inputs.json" --build-env .env.build
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Когда готовый образ опубликован:

```sh
docker compose --env-file .env --env-file selected.env pull
docker compose --env-file .env --env-file selected.env up -d --no-build
```

Для приватного пакета GHCR нужен вход под аккаунтом с доступом; для анонимного
скачивания владелец репозитория должен открыть пакет.
Локальная компиляция может занять продолжительное время. По умолчанию используется
один поток компиляции.

## Проверка

```sh
docker compose ps
docker compose logs --tail=100 botapi gateway
curl --connect-timeout 5 --max-time 10 -i http://127.0.0.1:18080/
```

Ответ по маршруту Bot API подтверждает доступность HTTP, даже если сообщает об
отсутствующем методе или токене. Это не проверка сессии бота и доставки webhook.

Адрес для приложения:

```text
http://127.0.0.1:18080/bot<TOKEN>/<METHOD>
```

Запросы с токеном отправляйте только выбранному серверу на соответствующем этапе
миграции. Для бота, уже работающего через этот сервер:

```sh
set -euo pipefail
export BOT_TOKEN_FILE=/secure/bot-token
export SELF_BOT_URL=http://127.0.0.1:18080
python3 - <<'PY'
import json, os, re, sys, urllib.request
sys.path.insert(0, 'tools')
from migration_cli import private_text
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None
try:
    token = re.sub(r'\r?\n$', '', private_text(os.environ['BOT_TOKEN_FILE']))
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token): raise ValueError()
    client = urllib.request.build_opener(NoRedirect)
    for method in ['getMe']:
        url = os.environ['SELF_BOT_URL'].rstrip('/') + '/bot' + token + '/' + method
        data = b'drop_pending_updates=false' if method == 'deleteWebhook' else None
        with client.open(urllib.request.Request(url, data=data), timeout=15) as response:
            result = json.load(response)
        if result.get('ok') is not True: raise ValueError()
        if method == 'deleteWebhook' and result.get('result') is not True: raise ValueError()
        if method == 'getWebhookInfo' and result['result']['url'] != '': raise ValueError()
    print('api_checks_pass; delivery_not_verified')
except Exception:
    raise SystemExit('request_failed; reconcile before retry') from None
PY
```

Примеры используют Bash и Python с private-file input. Токен остаётся внутри
HTTP-клиента; выводится только фиксированный результат. Используйте проверенную
logging policy gateway и native image из раздела настроек.

[Настройки](configuration.md) · [Перенос работающего бота](migration.md)

## Запуск doctor

После запуска выбранной установки выполните:

```sh
python3 tools/doctor.py -f docker-compose.yml --scenario official-to-self --format json
```

Без приватных решений миграции результат остаётся UNKNOWN. Штатный gateway только
проксирует запросы и не раздаёт state. Небезопасное изменение оператора, открывающее
state через alias, файловый сервер или монтирование в gateway, приводит к BLOCKED.
Коды и границы — в [обслуживании](maintenance.md), Compose/storage —
в [настройках](configuration.md), контракт приватного входа —
в [миграции](migration.md). READY — снимок предпосылок; он не авторизует бота
и не выполняет перенос.
Для файловых credentials используйте [secrets-профиль Compose](configuration.md#файловые-секреты-docker-compose), храните файлы вне checkout и применяйте secrets после build overlay.


Автономный экспортированный план требует Bash 4+ в Linux/WSL; сохранённый файл запускается командой `bash ./migration-plan.sh`. PowerShell и cmd не поддерживаются.

## Health без входа ботом

Management listener отдаёт точные GET/HEAD `/health/live` и `/health/ready`
из кеша root probes. Ожидается JSON 404 Bot API; HTML, redirect, timeout и stale
success дают отказ. При stats off глубина `http_handler_only`; при stats on
добавляется распознанный manager response (`http_handler_and_manager`).
Ни одна глубина не авторизует бота и не подтверждает связь с Telegram или доставку.
`/status` — документ, а не общий UP. Внутренний `/selfz` проверяет scheduler
observer и недоступен через management gateway.

Для запуска из registry требуется полный qualified `selected.env` с архивированным receipt;
`selected_release: null` означает, что выпуск не принят. Примеры запуска не заменяют обновление установки;
для него используйте [регламент обслуживания](maintenance.md#холодный-backup-обновление-и-откат-вместе-с-данными).
