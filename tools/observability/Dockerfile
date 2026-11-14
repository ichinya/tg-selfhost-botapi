ARG OBSERVER_BASE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
FROM ${OBSERVER_BASE}
ARG OBSERVER_BASE
ARG BUILD_FINGERPRINT
ARG APK_REFRESH_ID
LABEL org.opencontainers.image.source="https://github.com/ichinya/tg-selfhost-botapi" \
      io.tg-selfhost.build-key="${BUILD_FINGERPRINT}" \
      io.tg-selfhost.base="${OBSERVER_BASE}"
# APK repository revisions remain mutable; immutable release images are paired by key.
RUN test -n "$APK_REFRESH_ID" && test -n "$BUILD_FINGERPRINT" \
 && mkdir -p /usr/share/tg-selfhost-botapi/observer \
 && apk upgrade --no-cache && apk add --no-cache python3 \
 && cp /lib/apk/db/installed /usr/share/tg-selfhost-botapi/observer/installed \
 && printf '%s\n' "$APK_REFRESH_ID" > /usr/share/tg-selfhost-botapi/observer/refresh-id \
 && addgroup -g 101 -S observer \
 && adduser -S -D -H -u 101 -G observer observer
WORKDIR /app
COPY tools/observability/*.py tools/observability/status.schema.json /app/observability/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 101:101
ENTRYPOINT ["python3", "-m", "observability.server"]
