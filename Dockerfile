ARG ALPINE_IMAGE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
FROM ${ALPINE_IMAGE} AS source

ARG BOT_API_REVISION=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1

RUN apk add --no-cache alpine-sdk linux-headers git zlib-dev openssl-dev gperf cmake
WORKDIR /usr/src/telegram-bot-api
# Pin the official source so upstream changes cannot silently drop the header.
RUN git init . \
 && git remote add origin https://github.com/tdlib/telegram-bot-api.git \
 && git fetch --depth 1 origin ${BOT_API_REVISION} \
 && git checkout --detach FETCH_HEAD \
 && git submodule update --init --recursive --depth 1
COPY patches/webhook-user-agent.patch /tmp/webhook-user-agent.patch
RUN git apply --check /tmp/webhook-user-agent.patch \
 && git apply /tmp/webhook-user-agent.patch \
 && git diff --check

FROM source AS build
# One job limits peak memory consumption when building TDLib on a VPS.
ARG BUILD_JOBS=1
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build build --target install -j ${BUILD_JOBS} \
 && strip /usr/local/bin/telegram-bot-api

FROM ${ALPINE_IMAGE}
ARG BOT_API_REVISION=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1
# Public recipe fingerprint, stored in image metadata.
ARG BUILD_FINGERPRINT=local
LABEL org.opencontainers.image.source="https://github.com/ichinya/tg-selfhost-botapi" \
      org.opencontainers.image.licenses="BSL-1.0" \
      io.tg-selfhost.bot-api-revision="${BOT_API_REVISION}" \
      io.tg-selfhost.build-key="${BUILD_FINGERPRINT}"
ENV TELEGRAM_WORK_DIR="/var/lib/telegram-bot-api" \
    TELEGRAM_TEMP_DIR="/tmp/telegram-bot-api"
RUN apk add --no-cache openssl libstdc++ curl jq \
 && addgroup -g 101 -S telegram-bot-api \
 && adduser -S -D -H -u 101 -h /var/lib/telegram-bot-api -s /sbin/nologin -G telegram-bot-api telegram-bot-api \
 && mkdir -p /var/lib/telegram-bot-api /tmp/telegram-bot-api /var/lib/telegram-bot-api-files \
 && chown telegram-bot-api:telegram-bot-api /var/lib/telegram-bot-api /tmp/telegram-bot-api /var/lib/telegram-bot-api-files \
 && chmod 770 /var/lib/telegram-bot-api-files
COPY --from=build /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh
COPY --chmod=755 tools/botapi_healthcheck.sh /usr/local/bin/botapi-healthcheck
COPY --from=source /usr/src/telegram-bot-api/LICENSE_1_0.txt /usr/share/licenses/telegram-bot-api/LICENSE_1_0.txt
EXPOSE 8081/tcp
ENTRYPOINT ["/docker-entrypoint.sh"]
