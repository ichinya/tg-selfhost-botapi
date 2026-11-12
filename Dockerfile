ARG ALPINE_IMAGE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
FROM ${ALPINE_IMAGE} AS build-deps
ARG APK_REFRESH_ID
ARG ALPINE_IMAGE
RUN --mount=type=bind,source=tools/capture_apk_metadata.sh,target=/tmp/capture_apk_metadata.sh \
    : "${APK_REFRESH_ID:?Run tools/image_inputs.py --build-env-out .env.build first}" \
 && printf '%s\n' "$APK_REFRESH_ID" | grep -Eq '^v[0-9]+-[0-9]{4}-[0-9]{2}-[0-9]{2}-g[0-9]+$' \
 && printf '%s\n' "$ALPINE_IMAGE" | grep -Eq '^alpine:3[.]22@sha256:[0-9a-f]{64}$' \
 && apk upgrade --no-cache \
 && apk add --no-cache alpine-sdk linux-headers git zlib-dev openssl-dev gperf cmake python3 binutils \
 && sh /tmp/capture_apk_metadata.sh build "$APK_REFRESH_ID"

FROM build-deps AS source

ARG BOT_API_REVISION=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1

WORKDIR /usr/src/telegram-bot-api
# Pin the official source so upstream changes cannot silently drop the header.
RUN : "${BOT_API_REVISION:?Run tools/image_inputs.py to resolve pinned source inputs}" \
 && printf '%s\n' "$BOT_API_REVISION" | grep -Eq '^[0-9a-f]{40}$' \
 && git init . \
 && git remote add origin https://github.com/tdlib/telegram-bot-api.git \
 && git fetch --depth 1 origin ${BOT_API_REVISION} \
 && git checkout --detach FETCH_HEAD \
 && git submodule update --init --recursive --depth 1
COPY patches/webhook-user-agent.patch /tmp/webhook-user-agent.patch
RUN git apply --check /tmp/webhook-user-agent.patch \
 && git apply /tmp/webhook-user-agent.patch \
 && git diff --check
COPY patches/botapi-secrets-redaction.patch /tmp/botapi-secrets-redaction.patch
RUN git apply --check /tmp/botapi-secrets-redaction.patch \
 && git apply /tmp/botapi-secrets-redaction.patch \
 && git diff --check
COPY tools/fixtures/issue17_security/botapi_log_driver.cpp /tmp/botapi_log_driver.cpp
RUN printf '\nadd_executable(botapi-privacy-driver /tmp/botapi_log_driver.cpp telegram-bot-api/Query.cpp telegram-bot-api/Stats.cpp)\ntarget_include_directories(botapi-privacy-driver PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})\ntarget_link_libraries(botapi-privacy-driver PRIVATE memprof tdactor tdcore tddb tdnet tdutils)\n' >> CMakeLists.txt

FROM source AS build
# One job limits peak memory consumption when building TDLib on a VPS.
ARG BUILD_JOBS=1
ARG ALPINE_IMAGE
ARG BOT_API_REVISION
ARG BUILD_FINGERPRINT
ARG APK_REFRESH_ID
ARG TARGETPLATFORM
RUN --mount=type=bind,source=tools/capture_link_metadata.py,target=/tmp/capture_link_metadata.py \
    : "${BUILD_FINGERPRINT:?Run tools/image_inputs.py to resolve build inputs}" \
 && printf '%s\n' 'set_property(TARGET telegram-bot-api APPEND_STRING PROPERTY LINK_FLAGS " -Wl,-Map=${CMAKE_BINARY_DIR}/telegram-bot-api.map")' >> CMakeLists.txt \
 && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build build --target install -j ${BUILD_JOBS} \
 && cmake --build build --target botapi-privacy-driver -j ${BUILD_JOBS} \
 && build/botapi-privacy-driver \
 && sha256sum /usr/local/bin/telegram-bot-api > /usr/share/tg-selfhost-botapi/build/pre-strip.sha256 \
 && strip /usr/local/bin/telegram-bot-api \
 && python3 /tmp/capture_link_metadata.py

FROM ${ALPINE_IMAGE} AS runtime-deps
ARG APK_REFRESH_ID
ARG ALPINE_IMAGE
RUN --mount=type=bind,source=tools/capture_apk_metadata.sh,target=/tmp/capture_apk_metadata.sh \
    : "${APK_REFRESH_ID:?Run tools/image_inputs.py --build-env-out .env.build first}" \
 && printf '%s\n' "$APK_REFRESH_ID" | grep -Eq '^v[0-9]+-[0-9]{4}-[0-9]{2}-[0-9]{2}-g[0-9]+$' \
 && printf '%s\n' "$ALPINE_IMAGE" | grep -Eq '^alpine:3[.]22@sha256:[0-9a-f]{64}$' \
 && apk upgrade --no-cache \
 && apk add --no-cache openssl libstdc++ curl jq \
 && sh /tmp/capture_apk_metadata.sh runtime "$APK_REFRESH_ID"

FROM runtime-deps AS runtime
ARG BOT_API_REVISION=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1
# Public recipe fingerprint, stored in image metadata.
ARG BUILD_FINGERPRINT
ARG APK_REFRESH_ID
ARG APK_POLICY_VERSION
ARG APK_REFRESH_WINDOW
ARG APK_REFRESH_GENERATION
ARG TARGETPLATFORM
LABEL org.opencontainers.image.source="https://github.com/ichinya/tg-selfhost-botapi" \
      org.opencontainers.image.licenses="BSL-1.0" \
      io.tg-selfhost.bot-api-revision="${BOT_API_REVISION}" \
      io.tg-selfhost.build-key="${BUILD_FINGERPRINT}" \
      io.tg-selfhost.apk-refresh-id="${APK_REFRESH_ID}" \
      io.tg-selfhost.apk-policy-version="${APK_POLICY_VERSION}" \
      io.tg-selfhost.apk-refresh-window="${APK_REFRESH_WINDOW}" \
      io.tg-selfhost.apk-refresh-generation="${APK_REFRESH_GENERATION}" \
      io.tg-selfhost.platform="${TARGETPLATFORM}"
LABEL io.tg-selfhost.privacy-policy="issue17-v1"
ENV TELEGRAM_WORK_DIR="/var/lib/telegram-bot-api" \
    TELEGRAM_TEMP_DIR="/tmp/telegram-bot-api"
RUN addgroup -g 101 -S telegram-bot-api \
 && adduser -S -D -H -u 101 -h /var/lib/telegram-bot-api -s /sbin/nologin -G telegram-bot-api telegram-bot-api \
 && mkdir -p /var/lib/telegram-bot-api /tmp/telegram-bot-api /var/lib/telegram-bot-api-files \
 && chown telegram-bot-api:telegram-bot-api /var/lib/telegram-bot-api /tmp/telegram-bot-api /var/lib/telegram-bot-api-files \
 && chmod 770 /var/lib/telegram-bot-api-files
COPY --from=build /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY --from=build /usr/share/tg-selfhost-botapi/build /usr/share/tg-selfhost-botapi/build
COPY --from=build /usr/src/telegram-bot-api/build/botapi-privacy-driver /usr/local/bin/botapi-privacy-driver
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh
COPY --chmod=755 tools/botapi_healthcheck.sh /usr/local/bin/botapi-healthcheck
COPY --from=source /usr/src/telegram-bot-api/LICENSE_1_0.txt /usr/share/licenses/telegram-bot-api/LICENSE_1_0.txt
EXPOSE 8081/tcp
ENTRYPOINT ["/docker-entrypoint.sh"]
