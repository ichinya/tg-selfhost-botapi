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

На Linux VPS запишите версии Docker Engine и Compose v2 (`docker version`, `docker compose version`), архитектуру (`uname -m`), доступные ресурсы и свободный порт 18080. Проверьте daemon, curl и jq. CI публикует linux/amd64; поддержка ARM не подтверждена. Используйте отдельные данные и отдельный daemon или хост без конфликтующих фиксированных имён контейнеров и порта. До старта ограничьте доступ к gateway. Для config и up нужны `API_ID` и `API_HASH` в `.env` или окружении: синтетические значения подходят для config, для запуска нужны настоящие данные приложения.

Используйте отдельный VPS или одноразовый daemon и изначально пустой `./data`, без production volumes: старый state может восстановить сессии ботов. Имена `tg_botapi`, `tg_gateway` и порт 18080 не изолируются именем Compose-проекта. Штатная публикация открыта на всех интерфейсах, `/file/` раздаёт state: ограничьте ingress до запуска. Сохраняйте рабочий каталог, проект, `--env-file .env`, пользователя, context и `DOCKER_CONFIG`; команды ниже предполагают `.env` по умолчанию в этом каталоге. Используйте только tracked base и build файлы. Проверьте `docker compose config --help`, `docker compose up --help`, `docker run --help` и поддержку `--quiet`, `--images`, `--no-build`, `--pull` и политики `never`. При отсутствии остановитесь и используйте совместимый CLI; не опускайте флаги.

Выберите один режим и сохраняйте один набор Compose-файлов. Для готового образа замените шаблон на проверенный существующий `build-<key>` или `ghcr.io/ichinya/tg-selfhost-botapi@sha256:<verified-digest>`; шаблон digest не является рабочим значением. Экспортируйте переменную для Compose и shell: Compose читает `.env`, но shell не импортирует его автоматически.

```sh
export BOTAPI_IMAGE='ghcr.io/ichinya/tg-selfhost-botapi:build-<verified-key>'
export IMAGE="$BOTAPI_IMAGE"
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml config --images
docker compose -f docker-compose.yml pull botapi gateway
```

Запишите RepoDigest Bot API командой inspect ниже, затем повторите published pull с фактическим `BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi@sha256:<verified-digest>` и обновите `IMAGE`. Шаблон не является digest. Ошибка pull или недоступный digest означают, что точное повторение не подтверждено.

Gateway загружается из Docker Hub на описанных выше условиях. Для локальной сборки вместо этого:

```sh
export IMAGE=tg-selfhost-botapi:local
docker compose -f docker-compose.yml -f docker-compose.build.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.build.yml config --images
docker compose -f docker-compose.yml -f docker-compose.build.yml pull gateway
docker pull alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
```

При сборке Alpine загружается из Docker Hub, также нужны GitHub и APK repositories. Запишите inputs Dockerfile и переопределения build args. Сборка TDLib с `BUILD_JOBS=1` может занять десятки минут и больше на малом VPS; обеспечьте запас RAM и диска и непрерывную сессию screen/tmux или SSH. После pull/build запишите reference, ID, OS/architecture, RepoDigests и labels `io.tg-selfhost.bot-api-revision`, `io.tg-selfhost.build-key`, `org.opencontainers.image.source`; у локального образа RepoDigests может отсутствовать. Запишите digest и ID nginx. ID конфигурации образа не равен manifest digest, labels не являются аттестацией. `nginx:alpine` и `latest` изменяемы. При публикации результатов ограничивайтесь нужными полями.

```sh
docker image inspect --format 'ID={''{.Id}} OS/arch={''{.Os}}/{''{.Architecture}} digests={''{json .RepoDigests}} source={''{index .Config.Labels "org.opencontainers.image.source"}} revision={''{index .Config.Labels "io.tg-selfhost.bot-api-revision"}} build-key={''{index .Config.Labels "io.tg-selfhost.build-key"}}' "$IMAGE"
docker image inspect --format 'ID={''{.Id}} OS/arch={''{.Os}}/{''{.Architecture}} digests={''{json .RepoDigests}}' nginx:alpine
IMAGE_ID=$(docker image inspect --format '{''{.Id}}' "$IMAGE")
docker run --rm --network none --pull never "$IMAGE_ID" --version
```
Ожидаются строка версии и код 0; рабочие данные и credentials не монтируются. Entrypoint passthrough обходит проверку credentials и настройку владельца и не доказывает readiness. Для точного повтора gateway только на одноразовом daemon загрузите записанный `nginx@sha256:<verified-digest>`, локально присвойте тег `nginx:alpine` и сверьте ID с записанным. Retag влияет на всех пользователей имени; недоступный digest означает неподтверждённый повтор. Запустите выбранный режим:

```sh
# Готовый образ:
docker compose -f docker-compose.yml up -d --no-build --pull never
# Локальная сборка вместо него:
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-build --pull never
```

Проверьте оба сервиса и сравните ID образов контейнеров с записанными ID, включая nginx. Оба должны работать, а RestartCount не должен расти между двумя наблюдениями; несовпадение или цикл перезапусков означает неуспех, даже если HTTP отвечает:

```sh
docker compose -f docker-compose.yml ps
docker inspect --format 'name={''{.Name}} image={''{.Image}} status={''{.State.Status}} restarts={''{.RestartCount}}' tg_botapi tg_gateway
```

Для локального режима укажите оба файла `-f` и в `ps`. Не публикуйте полный inspect с environment.
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
