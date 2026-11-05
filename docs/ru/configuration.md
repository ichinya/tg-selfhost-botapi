---
title: Настройки
translation: /docs/en/configuration.html
---

# Настройки

## Адреса и хранение

| Настройка | Значение |
| --- | --- |
| Порт gateway на хосте | `18080` |
| Внутренний адрес Bot API | `http://botapi:8081` |
| Постоянные данные на хосте | `./data` |
| Каталог данных в контейнере | `/var/lib/telegram-bot-api` |
| Пользователь сервера | Root bootstrap сбрасывает права до `101:101`; Docker `user` задаёт прямой non-root запуск |
| Local mode | Включён в Compose |

Bot API endpoint принимает вызовы методов. Webhook URL находится в вашем
приложении и принимает обновления от сервера. Это разные адреса.

## Переменные Compose

| Переменная в `.env` | Назначение |
| --- | --- |
| `API_ID` | Обязательный API ID приложения |
| `API_HASH` | Обязательный API hash приложения |
| `BOTAPI_IMAGE` | Необязательный тег или digest; по умолчанию `ghcr.io/ichinya/tg-selfhost-botapi:latest` |

Для проверенной сборки:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi:build-<key>
```

Вместо тега можно указать digest. Локальный build override использует образ
`tg-selfhost-botapi:local` независимо от `BOTAPI_IMAGE`.

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

- nginx раздаёт каталог состояния через `/file/`; это не авторизованный файловый
  API. Ограничьте доступ; [issue #3](https://github.com/ichinya/tg-selfhost-botapi/issues/3).
- В nginx не задан увеличенный лимит загрузки. Большие multipart-запросы могут
  получить HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- Публикация `18080:80` в Compose не ограничивает доступ адресом localhost.
- Не публикуйте необработанные журналы и диагностику с токенами в URL.

[Установка](getting-started.md) · [Обслуживание](maintenance.md)
## Пользователь процесса

По умолчанию entrypoint запускается от root, меняет владельца только корней
каталогов состояния и временных файлов на `101:101` и запускает сервер от этой
учётной записи. Существующие вложенные файлы автоматически не исправляются.
При заданном в Docker непривилегированном `user` сохраняются его UID, GID и
дополнительные группы; владелец не меняется, оба каталога должны быть доступны
для записи и прохода. Числовому UID запись в passwd не нужна; именованный user
использует ту же ветку. Новые каталоги entrypoint создаёт с режимом `0750` при
umask `0027`, их владелец — создавший их пользователь. Подключённые секреты
`_FILE` должны быть доступны для чтения, а родитель `TELEGRAM_LOG_FILE` — для
записи и прохода фактическому пользователю сервера. Явные аргументы команды
обходят настройки сервиса и подготовку volume.

Новые файлы принадлежат эффективному UID сервера; группу задаёт primary GID либо
существующий setgid-каталог. Umask `0027` ограничивает обычное создание с `0666`
до `0640`; явно заданный upstream режим `0600` остаётся приватным. Старые данные
от этого не становятся читаемыми. При замене bind состояния на named volume
подготовьте новый отдельный volume offline с выбранным владельцем и режимом до
прямого non-root запуска. Root bootstrap меняет только два верхних каталога,
не мигрируя вложенные старые файлы. Проверьте create/read/rename от фактического
пользователя writer; существующие volumes адаптируйте по [offline-инструкции](maintenance.md#смена-пользователя-хранилища).

Необязательный `docker-compose.nonroot.yml` задаёт Docker user через `BOTAPI_UID`
и `BOTAPI_GID`, подключая заранее созданный каталог `BOTAPI_TEMP_SOURCE`. См.
[установку](getting-started.md#необязательный-запуск-compose-без-root).

Порты 8081 и 8082 непривилегированные, дополнительные capabilities для них не
нужны. Файловые Compose secrets сохраняют права источника на хосте: обеспечьте
чтение эффективному UID, поскольку `uid`, `gid` и `mode` в YAML эти права не
меняют.

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
