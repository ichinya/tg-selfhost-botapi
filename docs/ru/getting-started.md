---
title: Установка
translation: /docs/en/getting-started.html
---

# Установка

## Требования

- Docker с Compose v2.
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

Для split file profile в Linux подготовьте `./files` перед запуском:

```sh
sudo install -d -o 101 -g 101 -m 0770 ./files
```

Reader/handler требуют Linux/amd64, kernel >= 5.6 и openat2. Используйте проверенную
пару Bot API/downloads образов. Приватные token и registry хранятся вне media;
reader получает read-only только выбранный полный token bot-root по тому же
абсолютному пути. См. [файловый контракт](configuration.md) и команды в репозитории
`examples/files/README.md`; исходники examples исключены из Pages. Базовый gateway
не поддерживает HTTP-скачивание; remote требует opt-in override и HTTPS ingress
оператора перед proxy на `18082`.

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
