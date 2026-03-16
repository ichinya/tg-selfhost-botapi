# tg_gateway

Лёгкий шлюз для запуска локального Telegram Bot API сервера (`aiogram/telegram-bot-api`) в Docker и удобной смены `Bot API URL` и `webhook` при миграции между серверами.

## Быстрый старт

1. Создайте `.env` на основе примера:
```bash
cp .env.example .env
```
2. Укажите `API_ID` и `API_HASH` (их можно получить на [my.telegram.org](https://my.telegram.org)).
3. Запустите контейнер:
```bash
docker compose up -d
```
Сервис поднимется на `http://localhost:18081` и будет использовать директорию `./data` для постоянного хранения состояния.

---

## Архитектура и термины

Этот проект работает как прокси-совместимый Bot API сервер, который полностью заменяет официальное облако `https://api.telegram.org` для вашего бота. 

Важно различать две настройки:
* **`TELEGRAM_BOT_URL`** — это адрес (endpoint) самого Bot API сервера, к которому вы обращаетесь для вызова методов (`getMe`, `setWebhook`, `sendMessage`).
* **`WEB_HOOK`** — это HTTPS-адрес вашего приложения, на который Telegram будет отправлять входящие апдейты после успешной установки.

> ℹ️ **Примечание:** Для смены webhook на новый не требуется знать его старый адрес — метод `setWebhook` просто перезапишет его. Метод `deleteWebhook` аналогично удалит хук без привязки к конкретному URL.

---

## Миграция бота (Смена Bot API сервера)

Для надёжной и бесперебойной миграции бота архитектуру обновления необходимо строить вокруг перехода от старого к новому серверу: **`OLD_BOT_API_URL` → `NEW_BOT_API_URL`**.

> ⚠️ **Важно:** Если бот уже запущен на локальном Bot API сервере, для корректного переноса **необходимо** знать адрес старого сервера. Это требуется для вызова метода `close`, который корректно завершает сессию. Без вызова `close` Telegram может заблокировать подключение на новом сервере (ошибка `429 Too Many Requests`).

Рекомендуемая модель хранения состояния (например, в БД или `.env`):
```text
LAST_BOT_API_URL
LAST_WEBHOOK_URL
LAST_APPLIED_AT
```

### Универсальный алгоритм миграции (с известным состоянием)

В зависимости от текущего (старого) сервера и целевого (нового), алгоритм действий отличается:

#### Сценарий А. Смена только Webhook
`OLD_BOT_API_URL == NEW_BOT_API_URL` — меняется лишь адрес доставки апдейтов.
1. `NEW_BOT_API_URL/getMe`
2. `NEW_BOT_API_URL/setWebhook(url=NEW_WEB_HOOK)`
3. `NEW_BOT_API_URL/getWebhookInfo`

#### Сценарий Б. Переход Official → Self-Hosted
`OLD = api.telegram.org`, `NEW = локальный сервер`.
1. `api.telegram.org/deleteWebhook`
2. `api.telegram.org/logOut` *(Необходим перед запуском локального сервера. Блокирует возврат в облако на 10 минут)*.
3. `NEW_BOT_API_URL/getMe`
4. `NEW_BOT_API_URL/setWebhook(url=NEW_WEB_HOOK)`

#### Сценарий В. Переход Self-Hosted → Self-Hosted
Переезд между двумя приватными локальными серверами.
1. `OLD_BOT_API_URL/deleteWebhook`
2. `OLD_BOT_API_URL/close` *(Обязательно закрываем сессию на старом локальном сервере)*.
3. `NEW_BOT_API_URL/getMe`
4. `NEW_BOT_API_URL/setWebhook(url=NEW_WEB_HOOK)`

#### Сценарий Г. Возврат Self-Hosted → Official
1. `OLD_BOT_API_URL/deleteWebhook`
2. `OLD_BOT_API_URL/close` *(Только `close`, метод `logOut` здесь не применяется)*.
3. `api.telegram.org/getMe`
4. `api.telegram.org/setWebhook(url=NEW_WEB_HOOK)`

---

## Автоматическое определение (Best-effort миграция)

Если старый `Bot API URL` **неизвестен** (например, при утере базы данных), полностью гарантировать корректный перенос `local → local` технически невозможно. В этом случае применяется логика *best-effort* с проверкой статуса бота через официальное облако:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getMe"
```

1. **Если получен ответ `ok=true`:**
   Значит бот работает через облако. Смело применяем **Сценарий Б** (штатный переезд Official → Self-Hosted с предварительным `logOut` в облаке).
   
2. **Если получена ошибка вида `Logged out`:**
   Значит бот отвязан от облака и работает на каком-то неизвестном `local`-сервере. Поскольку вызвать `close` на старом сервере нельзя, делаем перенос втупую:
   * `NEW_BOT_API_URL/getMe`
   * `NEW_BOT_API_URL/setWebhook(url=NEW_WEB_HOOK)`
   *(Учитывайте, что такой перенос не гарантирует моментальную чистую работу, так как старый сервер не был закрыт должным образом).*

---

## Важные нюансы

* **Очередь сообщений (`drop_pending_updates`):** При миграции накопившиеся за время простоя апдейты будут доставлены на новый сервер. Если они больше не актуальны, используйте флаг `drop_pending_updates=true` в запросах `setWebhook` / `deleteWebhook`.
* **Fix the loop:** Обязательно сохраняйте `NEW_BOT_API_URL` в качестве `LAST_BOT_API_URL` после каждого успешного старта, чтобы в следующий раз миграция пошла по надежному (универсальному) алгоритму.

---

## Ссылки и материалы

* [Telegram Bot API — Официальная документация](https://core.telegram.org/bots/api)
* [TDLib Bot API — Особенности работы с Local Server](https://tdlib.github.io/telegram-bot-api/)
* [Метод logOut — Документация (GramIO)](https://gramio.dev/telegram/methods/logOut)
