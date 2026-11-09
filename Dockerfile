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
 && test "$(git rev-parse HEAD)" = "$BOT_API_REVISION" \
 && git submodule update --init --recursive --depth 1
COPY patches/webhook-user-agent.patch /tmp/webhook-user-agent.patch
RUN git apply --check /tmp/webhook-user-agent.patch \
 && git apply /tmp/webhook-user-agent.patch \
 && git diff --check \
 && { git rev-parse HEAD; sha256sum /tmp/webhook-user-agent.patch; git submodule status --recursive; } > /source-identity.txt \
 && ! grep -Eq "^[-+U]" /source-identity.txt

COPY tools/webhook_sender /opt/webhook_sender
RUN printf '\nadd_subdirectory(/opt/webhook_sender webhook_sender)\n' >> CMakeLists.txt

FROM source AS build
# One job limits peak memory consumption when building TDLib on a VPS.
ARG BUILD_JOBS=1
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build build --target install -j ${BUILD_JOBS} \
 && strip /usr/local/bin/telegram-bot-api

FROM ${ALPINE_IMAGE} AS runtime-base
ARG BOT_API_REVISION=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1
# Public recipe fingerprint, stored in image metadata.
ARG BUILD_FINGERPRINT=local
ARG PLATFORM_SET=linux/amd64,linux/arm64
ARG VERIFICATION_CONTRACT=native-multiarch-v3
ARG ALPINE_IMAGE
LABEL org.opencontainers.image.source="https://github.com/ichinya/tg-selfhost-botapi" \
      org.opencontainers.image.licenses="BSL-1.0" \
      io.tg-selfhost.bot-api-revision="${BOT_API_REVISION}" \
      io.tg-selfhost.build-key="${BUILD_FINGERPRINT}" \
      io.tg-selfhost.base-reference="${ALPINE_IMAGE}" \
      io.tg-selfhost.platform-set="${PLATFORM_SET}" \
      io.tg-selfhost.verification-contract="${VERIFICATION_CONTRACT}"
ENV TELEGRAM_WORK_DIR="/var/lib/telegram-bot-api" \
    TELEGRAM_TEMP_DIR="/tmp/telegram-bot-api"
RUN apk add --no-cache openssl libstdc++ \
 && addgroup -g 101 -S telegram-bot-api \
 && adduser -S -D -H -u 101 -h /var/lib/telegram-bot-api -s /sbin/nologin -G telegram-bot-api telegram-bot-api \
 && mkdir -p /var/lib/telegram-bot-api /tmp/telegram-bot-api \
 && chown telegram-bot-api:telegram-bot-api /var/lib/telegram-bot-api /tmp/telegram-bot-api
COPY --from=build /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh
COPY --from=source /source-identity.txt /usr/share/botapi/source-identity.txt
COPY --from=source /usr/src/telegram-bot-api/LICENSE_1_0.txt /usr/share/licenses/telegram-bot-api/LICENSE_1_0.txt
EXPOSE 8081/tcp 8082/tcp
ENTRYPOINT ["/docker-entrypoint.sh"]

# Test adapter and receiver never enter the default runtime target.
FROM runtime-base AS sender-test
RUN apk add --no-cache python3
COPY --from=build /usr/local/libexec/webhook-sender /usr/local/libexec/webhook-sender
COPY tools/webhook_sender/receiver.py /opt/webhook_sender/receiver.py
ENTRYPOINT ["python3", "/opt/webhook_sender/receiver.py"]

FROM runtime-base AS runtime
