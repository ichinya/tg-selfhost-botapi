# tg_gateway

Лёгкий шлюз для запуска локального Telegram Bot API сервера в Docker и удобной смены `Bot API URL` и `webhook` при миграции между серверами. Образ собирается из исходников `tdlib/telegram-bot-api` с entrypoint от `aiogram/telegram-bot-api` и заголовком User-Agent для webhook.

## Быстрый старт

### Требования

- Docker (рекомендуется Docker Engine 20.10+)
- Docker Compose (v2.x)
- `jq` (для запуска `migrate_off_to_self.sh`)

1. Создайте `.env` на основе примера:
```bash
cp .env.example .env
```
2. Укажите `API_ID` и `API_HASH` (их можно получить на [my.telegram.org](https://my.telegram.org)).
3. Запустите контейнер:
```bash
docker compose pull
docker compose up -d
```
Сервис поднимется на `http://localhost:18080` и будет использовать директорию `./data` для постоянного хранения состояния.

## Обращение к API

### User-Agent при доставке webhook

Готовый образ `ghcr.io/ichinya/tg-selfhost-botapi` собирается в GitHub Actions
из закреплённой для каждой сборки ревизии исходников Telegram с патчем
`patches/webhook-user-agent.patch`. Все исходящие POST-запросы с обновлениями
содержат `User-Agent: TelegramBotWebhook/1.0`, чтобы защита хостинга не
блокировала VPS из-за отсутствующего заголовка.

Заголовок добавляется в самом отправщике webhook (`WebhookActor.cpp`).
Настройки входящего nginx и заголовки запроса `setWebhook` на него не влияют.

Для обновления существующего сервера:

```bash
docker compose pull botapi
docker compose up -d --no-deps botapi
```

На VPS компиляция не нужна. Публикация образа начинается после включения
workflow в основной ветке; до первой успешной публикации используйте локальную
сборку:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Локальная сборка компилирует TDLib и может занять продолжительное время.
По умолчанию используется один поток для ограничения потребления памяти.
Каталог `./data` сохраняет сессии и настройки webhook; повторная миграция ботов
не требуется. После перезапуска отправьте сообщение боту и проверьте в журнале
принимающего сайта, что POST к webhook содержит `TelegramBotWebhook/1.0`.

При обновлении ревизии Bot API патч проверяется перед сборкой: несовместимое
изменение исходника остановит сборку, а не уберёт заголовок незаметно.

### Свой образ и обновления

`tdlib/telegram-bot-api` содержит официальный C++ сервер. Репозиторий
`aiogram/telegram-bot-api` упаковывает этот же сервер в Docker, добавляя Alpine,
entrypoint, переменные окружения и сборку для нескольких архитектур. Это не
отдельная реализация протокола. Их workflow получает исходники tdlib напрямую:
[официальный сервер](https://github.com/tdlib/telegram-bot-api),
[сборка aiogram](https://github.com/aiogram/telegram-bot-api/blob/master/.github/workflows/multiarch.yml).

| Вариант | Последствия |
| --- | --- |
| Готовый образ aiogram | Минимум сопровождения, но сейчас нет нашего User-Agent |
| Официальный бинарник без Docker | Нужно самостоятельно обеспечить сборку, пользователя, параметры запуска и обновления; User-Agent всё равно требует патча |
| Свой Docker-образ из официальных исходников | Контроль над патчем и публикацией; сохраняем совместимые переменные, UID/GID 101 и каталог данных |

Выбран третий вариант: официальный исходник, закреплённый entrypoint aiogram и
собственная публикация в GHCR. Бинарник из образа aiogram не модифицируется.
Его digest используется как сигнал обновления, а в метаданных собственного
образа отдельно записываются настоящие ревизии исходников и entrypoint.

Workflow `.github/workflows/image.yml`:

- Ежедневно около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменениях основной
  ветки и вручную проверяет tdlib, aiogram, digest `aiogram/telegram-bot-api:latest`
  и digest Alpine 3.22. Расписание GitHub может задерживаться.
- Создаёт ключ из этих входных данных и файлов сборки. Если такой образ уже
  опубликован, повторная компиляция пропускается; при недоступности проверки
  registry сборка повторяется, успешная публикация не предполагается.
- Проверяет применимость патча, компилирует весь сервер, выполняет `--version`,
  проверяет наличие User-Agent в бинарнике и синтаксис entrypoint. Проверка
  бинарника не заменяет интеграционную доставку webhook тестовому боту.
- После проверок публикует `build-<key>` и продвигает `latest`. Ошибка патча,
  компиляции или smoke-проверки оставляет прежний `latest`. В PR публикация
  отключена. Первая версия собственного образа поддерживает **linux/amd64**.

Расписание работает только после попадания workflow в основную ветку. Для GHCR
используется `GITHUB_TOKEN` с `packages: write`, дополнительный пароль не нужен.
Первый package может оказаться приватным: для скачивания без входа нужно явно
выбрать Public в настройках пакета GitHub либо настроить доступ к GHCR на VPS.

На production рекомендуется указать проверенный `build-<key>` или digest через
`BOTAPI_IMAGE` в `.env`. Обновление образа в registry **не перезапускает VPS**.
Перед сменой версии остановите сервис, сделайте согласованную резервную копию
`./data`, затем выполните pull и запуск. Откат бинарника требует проверки
совместимости сохранённых данных. При замене упаковки на том же сервере
сохраняются volume, endpoint, UID/GID и local mode; параллельно два процесса с
одним каталогом состояния запускать нельзя.

После запуска замените базовый URL:
- Официальный: `https://api.telegram.org/bot<TOKEN>/...`
- Self-hosted: `http://localhost:18080/bot<TOKEN>/...`

### Примеры

**getMe**
```bash
curl http://localhost:18080/bot<TOKEN>/getMe
```

**sendMessage**
```bash
curl -X POST http://localhost:18080/bot<TOKEN>/sendMessage \
  -d "chat_id=123456789" \
  -d "text=Hello from self-hosted API"
```

**getWebhookInfo**
```bash
curl http://localhost:18080/bot<TOKEN>/getWebhookInfo
```

## Работа с файлами

Файлы скачиваются с вашего сервера, а не с `api.telegram.org`.

1) Получите `file_path`:
```bash
FILE_PATH=$(curl -s http://localhost:18080/bot<TOKEN>/getFile \
  -d "file_id=AgACAgIAAxkBAAI..." | jq -r '.result.file_path')
```

2) Скачайте файл:
```bash
curl -o photo.jpg "http://localhost:18080/file/bot<TOKEN>/$FILE_PATH"
```

> Если не хотите передавать токен в URL, используйте заголовок `X-Telegram-Bot-Token`:
> ```bash
> curl -H "X-Telegram-Bot-Token: <TOKEN>" \
>   "http://localhost:18080/file/path/to/file.jpg" \
>   -o photo.jpg
> ```

---

## Архитектура и термины

Этот проект работает как прокси-совместимый Bot API сервер, который полностью заменяет официальное облако `https://api.telegram.org` для вашего бота. 

### Роль nginx

В `docker-compose.yml` поднят контейнер с `nginx`, который служит обратным прокси между внешним портом `80` и внутренним Bot API (`botapi:8081`). Файл `nginx.conf`:

- перенаправляет `/file/` на локальную файловую директорию `/var/lib/telegram-bot-api/`, где хранятся файлы (документы, фото и т.п.);
- проксирует все остальные запросы на `http://botapi:8081`;
- сохраняет заголовки `Host` и `X-Real-IP` для корректной работы.

Это даёт удобный внешний адрес и изоляцию сервиса.

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

В зависимости от текущего (старого) сервера и целевого (нового), алгоритм действий отличается. Ниже представлена визуальная схема и сводная таблица.

#### Визуальная схема алгоритма

```text
  ┌─────────────────────────────────────────────────────────────────────┐
  │                      АЛГОРИТМ МИГРАЦИИ                              │
  └─────────────────────────────────────────────────────────────────────┘

                      ┌─────────────────┐
                      │  OLD == NEW ?   │
                      └────────┬────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
               ДА                            НЕТ
                │                             │
                ▼                             ▼
      ┌─────────────────┐           ┌─────────────────┐
      │  Сценарий А:    │           │  OLD это        │
      │  Только webhook │           │  api.telegram   │
      │                 │           │  .org?          │
      │  setWebhook     │           └────────┬────────┘
      └─────────────────┘                    │
                                     ┌───────┴───────┐
                                     │               │
                                     ▼               ▼
                                    ДА              НЕТ
                                     │               │
                                     ▼               ▼
                           ┌──────────────┐  ┌──────────────┐
                           │ Сценарий Б:  │  │ NEW это      │
                           │ Official →   │  │ api.telegram │
                           │ Self-Hosted  │  │ .org?        │
                           │              │  └──────┬───────┘
                           │ 1. logOut    │         │
                           │ 2. setWebhook│  ┌──────┴───────┐
                           └──────────────┘  │              │
                                             ▼              ▼
                                            ДА             НЕТ
                                             │              │
                                             ▼              ▼
                                   ┌──────────────┐ ┌──────────────┐
                                   │ Сценарий Г:  │ │ Сценарий В:  │
                                   │ Self-Hosted  │ │ Self-Hosted  │
                                   │ → Official   │ │ → Self-Hosted│
                                   │              │ │              │
                                   │ 1. close     │ │ 1. close     │
                                   │ 2. setWebhook│ │ 2. setWebhook│
                                   └──────────────┘ └──────────────┘
```

#### Сводная таблица сценариев

| Сценарий | Старый сервер (OLD) | Новый сервер (NEW) | Основные шаги |
| :---: | :--- | :--- | :--- |
| **А** | Любой *( `OLD == NEW` )* | *(Тот же самый)* | Просто сделать `setWebhook` |
| **Б** | `api.telegram.org` (Облако) | `self-hosted` | `logOut` на OLD → `setWebhook` на NEW |
| **В** | `self-hosted` | `self-hosted` | `close` на OLD → `setWebhook` на NEW |
| **Г** | `self-hosted` | `api.telegram.org` (Облако) | `close` на OLD → `setWebhook` на NEW |

---

### Детальное описание шагов

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

## Скрипт миграции: `migrate_off_to_self.sh`

В репозитории есть утилита `migrate_off_to_self.sh`, которая автоматизирует переход:
* **Official (`api.telegram.org`) → Self-hosted**
* **Polling без webhook** (если `WEBHOOK_URL` не указан)
* **Учитывает `drop_pending_updates`** для удаления накопленных апдейтов

> **Требуется:** `jq` (скрипт использует его для разбора JSON). Если хотите, можно создать `.env` рядом со скриптом — тогда переменные будут автоматически загружены.

### Пример запуска (polling)
```bash
SELF_BOT_URL="https://tg.ie0.ru" \
  ./migrate_off_to_self.sh "$BOT_TOKEN"
```

### Пример запуска (с webhook)
```bash
SELF_BOT_URL="https://tg.ie0.ru" \
  ./migrate_off_to_self.sh "$BOT_TOKEN" "https://mysite/updates"
```

### Пример запуска с очисткой накопившихся апдейтов
```bash
DROP_PENDING_UPDATES=true \
  SELF_BOT_URL="https://tg.ie0.ru" \
  ./migrate_off_to_self.sh "$BOT_TOKEN"
```

### Переменные окружения
* `BOT_TOKEN` — обязательный (аргумент 1)
* `SELF_BOT_URL` — адрес self-hosted Bot API (аргумент 2 или env)
* `WEBHOOK_URL` — URL webhook (аргумент 3 или env); если не задан, используется polling
* `DROP_PENDING_UPDATES` — `true/false` (по умолчанию `false`)
* `.env` — при наличии в директории загружается автоматически (конфиденциальные переменные можно хранить здесь)

---

## Ссылки и материалы

* [Telegram Bot API — Официальная документация](https://core.telegram.org/bots/api)
* [TDLib Bot API — Особенности работы с Local Server](https://tdlib.github.io/telegram-bot-api/)
* [Метод logOut — Документация (GramIO)](https://gramio.dev/telegram/methods/logOut)
