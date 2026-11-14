ARG ALPINE_IMAGE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
FROM ${ALPINE_IMAGE} AS build-deps


ARG APK_REFRESH_ID
RUN test -n "$APK_REFRESH_ID" \
 && mkdir -p /usr/share/tg-selfhost-botapi/build \
 && cp /lib/apk/db/installed /usr/share/tg-selfhost-botapi/build/base-installed \
 && apk upgrade --no-cache \
 && apk add --no-cache alpine-sdk linux-headers git zlib-dev openssl-dev gperf cmake python3 \
 && cp /lib/apk/db/installed /usr/share/tg-selfhost-botapi/build/installed \
 && apk info -vv | sort > /usr/share/tg-selfhost-botapi/build/build-packages.txt \
 && cp /etc/apk/repositories /usr/share/tg-selfhost-botapi/build/build-repositories.txt \
 && { apk --version; apk --print-arch; printf '%s\n' "$APK_REFRESH_ID"; } > /usr/share/tg-selfhost-botapi/build/build-apk.txt \
 && { c++ --version; ld --version; cmake --version; } > /usr/share/tg-selfhost-botapi/build/compiler.txt
FROM build-deps AS source
ARG BOT_API_REVISION
ARG BOT_API_VERSION
ARG SUBMODULES
ARG TDLIB_REVISION

WORKDIR /usr/src/telegram-bot-api
# Pin the official source so upstream changes cannot silently drop the header.
RUN test -n "$BOT_API_REVISION" && test -n "$SUBMODULES" && test -n "$TDLIB_REVISION" \
 && git init . \
 && git remote add origin https://github.com/tdlib/telegram-bot-api.git \
 && git fetch --depth 1 origin ${BOT_API_REVISION} \
 && git checkout --detach FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$BOT_API_REVISION" \
 && git submodule update --init --recursive --depth 1
COPY tools/image_inputs.py /tmp/image_inputs.py
RUN test -n "$BOT_API_VERSION" \
 && test "$(python3 /tmp/image_inputs.py --extract-version CMakeLists.txt --runtime-source telegram-bot-api/telegram-bot-api.cpp)" = "$BOT_API_VERSION" \
 && test "$(git -C td rev-parse HEAD)" = "$TDLIB_REVISION" \
 && actual="$(git submodule status --recursive | awk '{print $2 "=" $1}' | LC_ALL=C sort | paste -sd, -)" \
 && test "$actual" = "$SUBMODULES" \
 && { git rev-parse HEAD; git submodule status --recursive; printf '%s\n' "$BOT_API_VERSION"; } > /usr/share/tg-selfhost-botapi/build/source.txt
COPY patches/webhook-user-agent.patch /tmp/webhook-user-agent.patch
RUN git apply --check /tmp/webhook-user-agent.patch \
 && git apply /tmp/webhook-user-agent.patch \
 && git diff --check
COPY patches/botapi-secrets-redaction.patch /tmp/botapi-secrets-redaction.patch
RUN git apply --check /tmp/botapi-secrets-redaction.patch \
 && git apply /tmp/botapi-secrets-redaction.patch \
 && git diff --check
RUN sha256sum /tmp/webhook-user-agent.patch /tmp/botapi-secrets-redaction.patch > /usr/share/tg-selfhost-botapi/build/patch.sha256
COPY tools/fixtures/issue17_security/botapi_log_driver.cpp /tmp/botapi_log_driver.cpp
RUN printf '\nadd_executable(botapi-privacy-driver /tmp/botapi_log_driver.cpp telegram-bot-api/Query.cpp telegram-bot-api/Stats.cpp)\ntarget_include_directories(botapi-privacy-driver PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})\ntarget_link_libraries(botapi-privacy-driver PRIVATE memprof tdactor tdcore tddb tdnet tdutils)\n' >> CMakeLists.txt

FROM source AS build
# One job limits peak memory consumption when building TDLib on a VPS.
ARG BUILD_JOBS=1
COPY tools/webhook_sender/ /usr/src/telegram-bot-api/webhook_sender/
RUN printf '\nadd_subdirectory(webhook_sender)\n' >> CMakeLists.txt
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build build --target install -j ${BUILD_JOBS} \
 && cmake --build build --target botapi-privacy-driver -j ${BUILD_JOBS} \
 && build/botapi-privacy-driver \
 && strip /usr/local/bin/telegram-bot-api \
 && sha256sum /usr/local/bin/telegram-bot-api > /usr/share/tg-selfhost-botapi/build/binary.sha256 \
 && cp build/CMakeFiles/telegram-bot-api.dir/link.txt /usr/share/tg-selfhost-botapi/build/link-commands.txt \
 && find build -name '*.a' -exec sha256sum '{}' ';' | LC_ALL=C sort > /usr/share/tg-selfhost-botapi/build/static-archives.sha256 \
 && sha256sum webhook_sender/CMakeLists.txt webhook_sender/webhook_sender_test.cpp > /usr/share/tg-selfhost-botapi/build/adapter.sha256 \
 && find build/webhook_sender/CMakeFiles/release_webhook_core.dir -name '*.o' -exec sha256sum '{}' ';' | LC_ALL=C sort > /usr/share/tg-selfhost-botapi/build/production-objects.sha256

FROM ${ALPINE_IMAGE} AS runtime-deps
ARG APK_REFRESH_ID
RUN test -n "$APK_REFRESH_ID" \
 && mkdir -p /usr/share/tg-selfhost-botapi/runtime \
 && cp /lib/apk/db/installed /usr/share/tg-selfhost-botapi/runtime/base-installed \
 && apk upgrade --no-cache && apk add --no-cache openssl libstdc++ su-exec curl jq \
 && cp /lib/apk/db/installed /usr/share/tg-selfhost-botapi/runtime/installed \
 && apk info -vv | sort > /usr/share/tg-selfhost-botapi/runtime/runtime-packages.txt \
 && cp /etc/apk/repositories /usr/share/tg-selfhost-botapi/runtime/runtime-repositories.txt \
 && { apk --version; apk --print-arch; printf '%s\n' "$APK_REFRESH_ID"; } > /usr/share/tg-selfhost-botapi/runtime/runtime-apk.txt


FROM runtime-deps AS runtime
ARG BOT_API_REVISION
ARG BOT_API_VERSION
ARG TDLIB_REVISION
ARG WRAPPER_REVISION
ARG TARGETPLATFORM
ARG ALPINE_IMAGE
# Public recipe fingerprint, stored in image metadata.
ARG BUILD_FINGERPRINT
LABEL org.opencontainers.image.source="https://github.com/ichinya/tg-selfhost-botapi" \
      org.opencontainers.image.licenses="BSL-1.0" \
      org.opencontainers.image.version="${BOT_API_VERSION}" \
      org.opencontainers.image.revision="${BOT_API_REVISION}" \
      io.tg-selfhost.tdlib-revision="${TDLIB_REVISION}" \
      io.tg-selfhost.wrapper-revision="${WRAPPER_REVISION}" \
      io.tg-selfhost.base="${ALPINE_IMAGE}" \
      io.tg-selfhost.platform="${TARGETPLATFORM}" \
      io.tg-selfhost.verification-contract="1" \
      io.tg-selfhost.bot-api-revision="${BOT_API_REVISION}" \
      io.tg-selfhost.build-key="${BUILD_FINGERPRINT}"
LABEL io.tg-selfhost.privacy-policy="issue17-v1"
ENV TELEGRAM_WORK_DIR="/var/lib/telegram-bot-api" \
    TELEGRAM_TEMP_DIR="/tmp/telegram-bot-api"
RUN test -n "$BUILD_FINGERPRINT" && test -n "$WRAPPER_REVISION" \
 && test -n "$BOT_API_REVISION" && test -n "$BOT_API_VERSION" && test -n "$TDLIB_REVISION" \
 && addgroup -g 101 -S telegram-bot-api \
 && adduser -S -D -H -u 101 -h /var/lib/telegram-bot-api -s /sbin/nologin -G telegram-bot-api telegram-bot-api \
 && mkdir -p /var/lib/telegram-bot-api /tmp/telegram-bot-api /var/lib/telegram-bot-api-files \
 && chown telegram-bot-api:telegram-bot-api /var/lib/telegram-bot-api /tmp/telegram-bot-api /var/lib/telegram-bot-api-files \
 && chmod 770 /var/lib/telegram-bot-api-files
COPY --from=build /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY --from=build /usr/src/telegram-bot-api/build/botapi-privacy-driver /usr/local/bin/botapi-privacy-driver
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh
COPY --chmod=755 tools/botapi_healthcheck.sh /usr/local/bin/botapi-healthcheck
COPY --from=source /usr/src/telegram-bot-api/LICENSE_1_0.txt /usr/share/licenses/telegram-bot-api/LICENSE_1_0.txt
COPY --from=build /usr/share/tg-selfhost-botapi/build/ /usr/share/tg-selfhost-botapi/build/
RUN sha256sum /usr/local/bin/telegram-bot-api /docker-entrypoint.sh /usr/local/bin/botapi-healthcheck > /usr/share/tg-selfhost-botapi/runtime/files.sha256 \
 && ldd /usr/local/bin/telegram-bot-api > /usr/share/tg-selfhost-botapi/runtime/linkage.txt
EXPOSE 8081/tcp
ENTRYPOINT ["/docker-entrypoint.sh"]

FROM runtime AS qualification
COPY --from=build /usr/local/libexec/release-webhook-sender /usr/local/libexec/release-webhook-sender
FROM runtime AS production
