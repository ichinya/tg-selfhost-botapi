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

Перед запуском на доступном извне хосте ограничьте gateway. Замените публикацию
порта в `docker-compose.yml` на:

```yaml
ports:
  - "127.0.0.1:18080:80"
```

Текущий Compose слушает все интерфейсы хоста, а nginx раздаёт каталог данных через
`/file/`. До [исправления файлового доступа](https://github.com/ichinya/tg-selfhost-botapi/issues/3)
используйте доверенное локальное окружение. Для удалённого доступа также нужны
HTTPS и ограничение доступа.

## Доступ к registry

| Registry | Назначение |
| --- | --- |
| GHCR | Готовый образ Bot API |
| Docker Hub | gateway `nginx:alpine` и закреплённый `alpine` при локальной сборке |

Публичные образы доступны анонимно, пока позволяют доступ и действующие лимиты. Для приватного образа нужна учётная запись с правами; вход может помочь при анонимном pull limit, но не исправляет любой ответ 429. См. [лимиты Docker Hub](https://docs.docker.com/docker-hub/usage/pulls/). Вход в Hub не авторизует в GHCR.

Задайте `DOCKERHUB_USER` как имя пользователя, а `DOCKERHUB_TOKEN_FILE` как путь к файлу PAT вне репозитория, доступному только владельцу. Создайте его приватно, не записывая токен в историю shell. Выключите трассировку; не выводите токен или файл:

```sh
set +x
docker login --username "$DOCKERHUB_USER" --password-stdin < "$DOCKERHUB_TOKEN_FILE"
```

Ожидаются код 0 и `Login Succeeded`; затем отдельно выполните pull нужного reference и проверьте код 0; вход сам по себе не подтверждает доступ к образу. Другой вариант — `docker login --username "$DOCKERHUB_USER"` и скрытый ввод PAT. Без `--username` Docker Hub использует device-code flow. Для приватного GHCR нужны отдельные credentials с правом чтения пакета: `docker login ghcr.io --username "$GHCR_USER" --password-stdin < "$GHCR_TOKEN_FILE"`. Защитите файл таким же образом.

Выполняйте login и pull от одного Unix-пользователя с одинаковыми Docker context и `DOCKER_CONFIG`: `sudo docker` может использовать другую конфигурацию. Используйте credential helper: без него Docker может сохранить credentials в `config.json` в base64, без шифрования. Не передавайте registry PAT в environment Compose или `.env` приложения и не включайте Docker config в отчёты.

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
