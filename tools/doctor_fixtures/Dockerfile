ARG PYTHON_IMAGE=python:3.13.5-alpine3.22
FROM ${PYTHON_IMAGE}
LABEL io.tg-selfhost.doctor-fixture="synthetic" \
      io.tg-selfhost.build-key="local" \
      org.opencontainers.image.source="https://github.com/ichinya/tg-selfhost-botapi"
ENV TELEGRAM_WORK_DIR=/var/lib/telegram-bot-api TELEGRAM_TEMP_DIR=/tmp/telegram-bot-api
RUN addgroup -g 101 -S telegram-bot-api \
 && adduser -u 101 -S -D -H -G telegram-bot-api telegram-bot-api \
 && mkdir -p /var/lib/telegram-bot-api /tmp/telegram-bot-api /audit \
 && printf 'synthetic state sentinel\n' > /var/lib/telegram-bot-api/sentinel \
 && chown -R 101:101 /var/lib/telegram-bot-api /tmp/telegram-bot-api /audit
COPY --chmod=755 botapi_stub.py /usr/local/bin/telegram-bot-api
COPY --chmod=755 entrypoint.sh /docker-entrypoint.sh
USER 101:101
ENTRYPOINT ["/docker-entrypoint.sh"]
HEALTHCHECK --interval=1s --timeout=2s --retries=20 CMD python3 -c "import socket; s=socket.create_connection(('127.0.0.1',8081),1); s.close()"
