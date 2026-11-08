---
title: Установка
translation: /docs/en/getting-started.html
---

# Установка

## Требования

- Docker с Compose v2.
- Для doctor: Python 3.11+ на host (только stdlib). Полная runtime-проверка требует
  локального Linux Engine с доступом к bridge; pure-проверки работают и на Windows.
- API ID и API hash приложения Telegram с [my.telegram.org](https://my.telegram.org).
- Для Bash-мигратора: Bash, curl и jq.

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
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
curl --connect-timeout 5 --max-time 15 \
  "http://127.0.0.1:18080/bot$BOT_TOKEN/getMe"
unset BOT_TOKEN
```

Примеры команд рассчитаны на Bash. Токен в URL curl может быть виден в аргументах
процесса и access logs; выполняйте диагностику в доверенном окружении.

[Настройки](configuration.md) · [Перенос работающего бота](migration.md)

## Запуск doctor

После запуска выбранной установки выполните:

```sh
python3 tools/doctor.py -f docker-compose.yml --scenario official-to-self --format json
```

Без приватных решений миграции результат остаётся UNKNOWN. Штатный alias `/file/`
для state — известная причина BLOCKED; до миграции нужна изоляция по задачам
#3/#5. Коды и границы — в [обслуживании](maintenance.md), Compose/storage —
в [настройках](configuration.md), контракт приватного входа —
в [миграции](migration.md). READY — снимок предпосылок; он не авторизует бота
и не выполняет перенос.
