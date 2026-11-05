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
## Необязательный запуск Compose без root

Подготовьте `./data` и отдельный дисковый каталог вне checkout и дерева
состояния с владельцем выбранным UID:GID, обычно с режимом `0700`. Задайте
`BOTAPI_UID`, `BOTAPI_GID` и `BOTAPI_TEMP_SOURCE` в приватном окружении. Порядок
файлов: `docker compose -f docker-compose.yml -f docker-compose.build.yml -f
docker-compose.nonroot.yml up -d botapi` (для опубликованного образа исключите
build-файл). Временный каталог должен существовать заранее. При использовании
secrets overlay применяется последним, а файлы секретов должны быть читаемы.
UID 0 включает обычный root bootstrap со сбросом до 101. Проксирование API не
гарантирует доступность и безопасность старого alias `/file/` при другом UID;
см. задачи #3 и #5.

Только для нового пустого хранилища пример точечной подготовки:
`sudo install -d -m 0700 -o 1000 -g 2000 ./data /srv/tg-selfhost-botapi/temp`.
Сначала проверьте оба пути; существующие данные готовьте по [offline-инструкции](maintenance.md#смена-пользователя-хранилища).
Для опубликованного образа команда запуска только сервиса:

```sh
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml up -d botapi
```

До запуска задайте все три переменные, включая путь дискового temp. Они задают
интерполяцию override, а не environment API образа. Для тех же UID/GID нужны
читаемые секреты и доступный для записи и прохода родитель файла журнала.

## Reader разрешённых медиа

Runnable-пример ниже использует writer `1000:2000` и reader `3000:3000` с
дополнительной группой `2000`. Храните `ISSUE21_MEDIA_PATH` в приватной
конфигурации: это одобренный администратором абсолютный media leaf одного бота,
смонтированный по тому же абсолютному пути, что доверенный `getFile.file_path`.
Путь может содержать токен бота; не печатайте его при диагностике. Не монтируйте
в reader корень бота, state или temp и не принимайте произвольный путь клиента.

Подготовьте только разрешённый leaf с режимом `0750` и общие файлы `0640`,
владелец `1000:2000`; приватные корни state/temp остаются `0700`. Primary GID
writer 2000 сохраняет группу после создания в temp и rename. Существующие файлы
`0600` остаются закрытыми. Контракт даёт только чтение. Probe примера ожидает
синтетические файлы runtime gate; production reader использует команду своего
приложения и проверенный layout медиа.

```yaml
services:
  botapi:
    user: "1000:2000"
  reader:
    image: ${BOTAPI_IMAGE:?Set BOTAPI_IMAGE}
    user: "3000:3000"
    group_add: ["2000"]
    network_mode: none
    entrypoint: ["/bin/sh", "/reader-probe.sh"]
    environment:
      MEDIA_PATH: ${ISSUE21_MEDIA_PATH:?Set ISSUE21_MEDIA_PATH}
    volumes:
      - type: bind
        source: ${ISSUE21_MEDIA_PATH:?Set ISSUE21_MEDIA_PATH}
        target: ${ISSUE21_MEDIA_PATH:?Set ISSUE21_MEDIA_PATH}
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: ./tools/fixtures/issue21/reader-probe.sh
        target: /reader-probe.sh
        read_only: true
        bind:
          create_host_path: false
```

Из корня репозитория задайте `BOTAPI_IMAGE` и приватный `ISSUE21_MEDIA_PATH`,
затем выполните `docker compose -f docker-compose.yml -f
 tools/fixtures/issue21/docker-compose.reader.yml run --rm --no-deps reader` для
синтетического probe. Fixture проверяет общую группу и read-only mount, отсутствие
соседнего бота и приватного хранилища. Это имитация filesystem create/rename, а не
реальная загрузка из Telegram. Рекурсивная подготовка старого state не выполняется.
Общая группа не распространяется на private migration state. После появления
отдельного media root в #5 примените туда тот же ограниченный mapping.
Nginx workers могут сбрасывать дополнительные группы: группа master не доказывает
доступ worker. HTTP-выдача файлов остаётся задачами #3/#5.
