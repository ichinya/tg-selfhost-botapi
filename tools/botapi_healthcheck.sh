#!/bin/sh
# Root handler check: expected 404 is handled separately from transport failure.
set -eu
umask 077
case "${TELEGRAM_HTTP_IP_ADDRESS:-0.0.0.0}" in
    0.0.0.0|'') host=127.0.0.1 ;;
    ::|'[::]') host='[::1]' ;;
    \[*\]) host="$TELEGRAM_HTTP_IP_ADDRESS" ;;
    *:*) host="[${TELEGRAM_HTTP_IP_ADDRESS}]" ;;
    *) host="$TELEGRAM_HTTP_IP_ADDRESS" ;;
esac
port="${TELEGRAM_HTTP_PORT:-8081}"
case "$port" in ''|*[!0-9]*) exit 1 ;; esac
[ "${#port}" -le 5 ] || exit 1
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || exit 1
case "$host" in *[!0-9a-fA-F.:\[\]]*) exit 1 ;; esac
work=$(mktemp -d 2>/dev/null) || exit 1
trap 'rm -f "$work/body" "$work/headers" 2>/dev/null; rmdir "$work" 2>/dev/null' EXIT HUP INT TERM
code=$(curl --disable --silent --proxy '' --noproxy '*' --max-redirs 0 --connect-timeout 1 --max-time 2 --max-filesize 16384 \
    --output "$work/body" --dump-header "$work/headers" --write-out '%{http_code}' \
    "http://$host:$port/" 2>/dev/null) || exit 1
[ "$code" = 404 ] || exit 1
[ "$(wc -c < "$work/body")" -le 16384 ] || exit 1
tr -d '\r' < "$work/headers" | grep -Eiq '^content-type:[[:space:]]*application/json([;[:space:]]|$)' || exit 1
jq -s -e 'length == 1 and (.[0] | type == "object" and .ok == false and (.error_code | type == "number") and .error_code == 404)' \
    "$work/body" >/dev/null 2>&1
