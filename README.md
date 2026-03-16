# tg_gateway

Лёгкий шлюз для запуска локального Telegram Bot API сервера (aiogram/telegram-bot-api) в Docker и удобной смены `Bot API URL` / `webhook` при миграции между серверами.

## Быстрый старт

1. Создайте `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

2. Укажите `API_ID` и `API_HASH` (берутся из https://my.telegram.org).

3. Запустите контейнер:

```bash
docker compose up -d
```

Сервис стартует на `http://localhost:18081` и будет использовать папку `./data` для хранения состояния.

---

## О сервере

Этот проект запускает локальный Telegram Bot API сервер (`aiogram/telegram-bot-api`) в Docker. Он работает как прокси-совместимый Bot API сервер, который может использоваться вместо официального `https://api.telegram.org`.

- **`TELEGRAM_BOT_URL`** в конфиге обычно указывает на Bot API endpoint, через который вы делаете вызовы методов (`getMe`, `setWebhook`, `sendMessage` и т.п.).
- **`WEB_HOOK`** — это HTTPS-адрес, на который Telegram будет отправлять апдейты после успешного `setWebhook`. Это **не** то же самое, что Bot API URL.

`setWebhook` и `deleteWebhook` не требуют знания старого `WEB_HOOK`:
- `setWebhook` просто переписывает текущий webhook на новый URL.
- `deleteWebhook` удаляет webhook (без знания, на какой URL он был настроен).
- `getWebhookInfo` вернёт пустой `url`, если webhook не настроен.

---

## Миграция бота (upgrade / смена Bot API сервера)

Для универсальной миграции важно строить логику не от текущего `TELEGRAM_BOT_URL`, а от пары:

- `OLD_BOT_API_URL` → `NEW_BOT_API_URL`

И хранить последний успешно применённый `Bot API URL` (например, в БД или в файле состояния):

```text
last_bot_api_url
last_webhook_url
last_applied_at
```

Без `last_bot_api_url` нельзя корректно обработать сценарий **local -> другой local**, так как Telegram рекомендует вызывать `close` именно на старом локальном Bot API сервере.

### Правильная модель

- `TELEGRAM_BOT_URL` — это **Bot API endpoint**, через который вы вызываете методы (`getMe`, `setWebhook`, `sendMessage`).
- `WEB_HOOK` — это **адрес, куда Telegram слать апдейты** после `setWebhook`.

### Общая (универсальная) логика

#### 1) Если `OLD_BOT_API_URL == NEW_BOT_API_URL`

Ничего переносить не нужно. Просто обновляем webhook:

1. `getMe` через `NEW_BOT_API_URL`
2. `setWebhook(url=NEW_WEB_HOOK)` через `NEW_BOT_API_URL`
3. `getWebhookInfo` через `NEW_BOT_API_URL`

Это покрывает и сценарий, когда меняется только webhook.

#### 2) Если `OLD_BOT_API_URL = api.telegram.org`, а `NEW_BOT_API_URL` — локальный сервер (self-hosted)

Переход **официальный → self-hosted**:

1. `deleteWebhook` через `api.telegram.org`
2. `logOut` через `api.telegram.org`
3. `getMe` через новый локальный Bot API
4. `setWebhook(url=NEW_WEB_HOOK)` через новый локальный Bot API
5. `getWebhookInfo` через новый локальный Bot API

`logOut` нужен перед запуском бота локально. После успешного `logOut` вернуться в cloud Bot API можно только через ~10 минут.

#### 3) Если `OLD_BOT_API_URL` — локальный, а `NEW_BOT_API_URL` — другой локальный

Переход **self-hosted → другой self-hosted**:

1. `deleteWebhook` через `OLD_BOT_API_URL`
2. `close` через `OLD_BOT_API_URL`
3. `getMe` через `NEW_BOT_API_URL`
4. `setWebhook(url=NEW_WEB_HOOK)` через `NEW_BOT_API_URL`
5. `getWebhookInfo` через `NEW_BOT_API_URL`

Telegram прямо рекомендует вызывать `close` перед переносом бота между local серверами; при этом webhook нужно удалить до `close`.

> В первые 10 минут после старта local Bot API `close` может возвращать `429`.

#### 4) Если `OLD_BOT_API_URL` — локальный, а `NEW_BOT_API_URL = api.telegram.org`

Переход **self-hosted → official**:

1. `deleteWebhook` через `OLD_BOT_API_URL`
2. `close` через `OLD_BOT_API_URL`
3. `getMe` через `api.telegram.org`
4. `setWebhook(url=NEW_WEB_HOOK)` через `api.telegram.org`
5. `getWebhookInfo` через `api.telegram.org`

`logOut` здесь не нужен: он применяется только при выходе из cloud перед запуском локального.

---

## Примеры сценариев

### 1) BEGIN — первый запуск (официальный)

`official + hook1`

1. `getMe` через `api.telegram.org`
2. `setWebhook(hook1)` через `api.telegram.org`

### 2) MOVE TO SELF — official → self-hosted

`official -> telega.ru`, webhook тот же

1. `deleteWebhook` на official
2. `logOut` на official
3. `getMe` на `telega.ru`
4. `setWebhook(hook1)` на `telega.ru`

### 3) MOVE TO ANOTHER SELF — self-hosted → другой self-hosted

`telega.ru -> coolserver.ru`, webhook тот же

1. `deleteWebhook` на `telega.ru`
2. `close` на `telega.ru`
3. `getMe` на `coolserver.ru`
4. `setWebhook(hook1)` на `coolserver.ru`

### 4) CHANGE HOOK — смена URL webhook

`coolserver.ru`, `hook1 -> hook2`

1. `getMe` на `coolserver.ru`
2. `setWebhook(hook2)` на `coolserver.ru`

### 5) RETURN TO OFFICIAL — self-hosted → official

`coolserver.ru -> official`, webhook снова `hook1`

1. `deleteWebhook` на `coolserver.ru`
2. `close` на `coolserver.ru`
3. `getMe` на `api.telegram.org`
4. `setWebhook(hook1)` на `api.telegram.org`

---

## Важные моменты

- **Не делай `logOut`, если старый сервер уже local.** Для local→local и local→official нужен `close`, а не `logOut`.
- **Старый `WEB_HOOK` не нужен.** `deleteWebhook` и `setWebhook` не требуют знать предыдущий адрес.
- Если нужно сбросить очередь старых апдейтов, используйте `drop_pending_updates=true`.

---

## Формальная логика (псевдокод)

```text
if old_bot_api_url == new_bot_api_url:
    new/getMe
    new/setWebhook(web_hook)
    new/getWebhookInfo

elif old is official and new is local:
    official/deleteWebhook
    official/logOut
    new/getMe
    new/setWebhook(web_hook)
    new/getWebhookInfo

elif old is local and new is local:
    old/deleteWebhook
    old/close
    new/getMe
    new/setWebhook(web_hook)
    new/getWebhookInfo

elif old is local and new is official:
    old/deleteWebhook
    old/close
    official/getMe
    official/setWebhook(web_hook)
    official/getWebhookInfo
```

---

## Предложение по параметрам для updater-а

Добавь в updater явные поля:

```text
OLD_BOT_API_URL
NEW_BOT_API_URL
WEB_HOOK
DROP_PENDING_UPDATES=false
```

После успешного применения сохрани `NEW_BOT_API_URL` как `last_bot_api_url`.

---

## Ссылки

- [Telegram Bot API](https://core.telegram.org/bots/api)
