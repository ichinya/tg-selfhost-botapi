---
title: Установка
translation: /docs/en/getting-started.html
---

# Установка

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
```

Заполните `API_ID` и `API_HASH` в `.env`. Не публикуйте этот файл.

По умолчанию gateway слушает `127.0.0.1` и не раздаёт каталог состояния.
Если удалённым клиентам, включая получатель webhook, нужен доступ к Bot API,
задайте `GATEWAY_BIND=0.0.0.0` в `.env` и обеспечьте HTTPS и сетевые ограничения.

## Запуск

До первой публикации в GHCR используйте локальную сборку:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Когда готовый образ опубликован:

```sh
docker compose pull
docker compose up -d
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
