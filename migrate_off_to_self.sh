#!/usr/bin/env bash
set -euo pipefail

# =========================
# Load a trusted shell file without overriding process configuration.
# =========================

process_self="${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}"
process_hook="${WEBHOOK_URL:-${WEB_HOOK:-}}"
process_drop="${DROP_PENDING_UPDATES:-}"
process_connect_set="${MIGRATION_CONNECT_TIMEOUT+x}"
process_connect="${MIGRATION_CONNECT_TIMEOUT-}"
process_deadline_set="${MIGRATION_REQUEST_DEADLINE+x}"
process_deadline="${MIGRATION_REQUEST_DEADLINE-}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${ENV_FILE+x} ]]; then
  env_path="$ENV_FILE"
  [[ -n "$env_path" && -f "$env_path" && -r "$env_path" && -s "$env_path" ]] || {
    echo "Error: invalid ENV_FILE" >&2; exit 1;
  }
else
  env_path="$script_dir/.env"
fi
file_self= file_hook= file_drop= file_connect_set= file_connect= file_deadline_set= file_deadline=
if [[ -e "$env_path" ]]; then
  [[ -f "$env_path" && -r "$env_path" ]] && bash -n "$env_path" 2>/dev/null || {
    echo "Error: cannot load environment file" >&2; exit 1;
  }
  # The file is trusted Bash. Capture only supported helper settings.
  if ! file_values="$(bash -e -c '
    unset SELF_BOT_URL TELEGRAM_BOT_URL WEBHOOK_URL WEB_HOOK DROP_PENDING_UPDATES MIGRATION_CONNECT_TIMEOUT MIGRATION_REQUEST_DEADLINE
    source "$1" >/dev/null 2>&1
    printf "file_self=%q\nfile_hook=%q\nfile_drop=%q\n" \
      "${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}" "${WEBHOOK_URL:-${WEB_HOOK:-}}" "${DROP_PENDING_UPDATES:-}"
    printf "file_connect_set=%q\nfile_connect=%q\nfile_deadline_set=%q\nfile_deadline=%q\n" \
      "${MIGRATION_CONNECT_TIMEOUT+x}" "${MIGRATION_CONNECT_TIMEOUT-}" \
      "${MIGRATION_REQUEST_DEADLINE+x}" "${MIGRATION_REQUEST_DEADLINE-}"
  ' _ "$env_path")"; then
    echo "Error: cannot load environment file" >&2; exit 1
  fi
  eval "$file_values"
fi

OFFICIAL_BOT_URL="${OFFICIAL_BOT_URL:-https://api.telegram.org}"

BOT_TOKEN="${1:-}"
SELF_BOT_URL="${2:-${process_self:-$file_self}}"
WEBHOOK_URL_ARG="${3:-${process_hook:-$file_hook}}"
DROP_PENDING_UPDATES="${process_drop:-${file_drop:-false}}"
if [[ -n "$process_connect_set" ]]; then MIGRATION_CONNECT_TIMEOUT="$process_connect"
elif [[ -n "$file_connect_set" ]]; then MIGRATION_CONNECT_TIMEOUT="$file_connect"
else MIGRATION_CONNECT_TIMEOUT=5; fi
if [[ -n "$process_deadline_set" ]]; then MIGRATION_REQUEST_DEADLINE="$process_deadline"
elif [[ -n "$file_deadline_set" ]]; then MIGRATION_REQUEST_DEADLINE="$file_deadline"
else MIGRATION_REQUEST_DEADLINE=30; fi

# =========================
# checks
# =========================

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: need command '$1'"
    exit 1
  }
}

need_cmd curl
need_cmd jq
need_cmd mktemp
need_cmd cat
need_cmd rm

# Bound the length before decimal conversion to avoid overflow and octal parsing.
if [[ ! "$MIGRATION_CONNECT_TIMEOUT" =~ ^[0-9]{1,2}$ || ! "$MIGRATION_REQUEST_DEADLINE" =~ ^[0-9]{1,3}$ ]] ||
   (( 10#$MIGRATION_CONNECT_TIMEOUT < 1 || 10#$MIGRATION_CONNECT_TIMEOUT > 60 ||
      10#$MIGRATION_REQUEST_DEADLINE < 1 || 10#$MIGRATION_REQUEST_DEADLINE > 300 ||
      10#$MIGRATION_CONNECT_TIMEOUT > 10#$MIGRATION_REQUEST_DEADLINE )); then
  echo 'Invalid migration timeout settings' >&2; exit 1
fi
MIGRATION_CONNECT_TIMEOUT=$((10#$MIGRATION_CONNECT_TIMEOUT))
MIGRATION_REQUEST_DEADLINE=$((10#$MIGRATION_REQUEST_DEADLINE))

if [[ -z "$BOT_TOKEN" ]]; then
  echo "BOT_TOKEN required"
  exit 1
fi

if [[ -z "${SELF_BOT_URL:-}" ]]; then
  echo "SELF_BOT_URL required"
  exit 1
fi

SELF_BOT_URL="${SELF_BOT_URL%/}"
OFFICIAL_BOT_URL="${OFFICIAL_BOT_URL%/}"

for endpoint in "$SELF_BOT_URL" "$OFFICIAL_BOT_URL"; do
  if [[ ! "$endpoint" =~ ^https?://[^/@?#[:space:]]+(/[^?#[:space:]]*)?$ ]]; then
    echo "Invalid API endpoint" >&2; exit 1
  fi
done
if [[ -n "$WEBHOOK_URL_ARG" && ! "$WEBHOOK_URL_ARG" =~ ^https?://[^/@?#[:space:]]+([^@[:space:]]*)?$ ]]; then
  echo "Invalid webhook URL" >&2; exit 1
fi

if [[ "$SELF_BOT_URL" == "$OFFICIAL_BOT_URL" ]]; then
  echo "SELF_BOT_URL must not be api.telegram.org"
  exit 1
fi

case "$DROP_PENDING_UPDATES" in
  true|false) ;;
  *)
    echo "DROP_PENDING_UPDATES must be true/false"
    exit 1
    ;;
esac

# =========================
# api helpers
# =========================

capture() {
  local dir="$1" connect="$2" deadline="$3" rc
  shift 3
  if curl -q -sS --retry 0 --connect-timeout "$connect" --max-time "$deadline" \
      --output "$dir/body.raw" --write-out '%{http_code}' "$@" >"$dir/http-status" 2>"$dir/transport.raw"; then
    rc=0
  else
    rc=$?
  fi
  printf '%s\n' "$rc" >"$dir/curl-exit" || return 1
  local status
  status="$(cat "$dir/http-status")" || return 1
  if [[ "$status" == 000 || -z "$status" ]]; then
    printf 'null\n' >"$dir/http-status" || return 1
  fi
}

request() {
  local dir="$1" status rc
  shift
  capture "$dir" "$MIGRATION_CONNECT_TIMEOUT" "$MIGRATION_REQUEST_DEADLINE" "$@" || return 1
  rc="$(cat "$dir/curl-exit")" || return 1
  status="$(cat "$dir/http-status")" || return 1
  if (( rc != 0 )); then
    echo 'Request failed; a mutation may have an UNKNOWN outcome. Stop and reconcile before retrying.' >&2
    return 1
  fi
  [[ "$status" =~ ^2[0-9][0-9]$ ]] || {
    echo "Request failed with HTTP $status; stopping before dependent actions." >&2
    return 1
  }
}

api_get() {
  request "$1" "$2/bot$BOT_TOKEN/$3"
}

api_post() {
  local dir="$1" base="$2" method="$3"
  shift 3

  request "$dir" -X POST "$base/bot$BOT_TOKEN/$method" "$@"
}

assert_ok() {
  local json="$1"
  local name="$2"

  local ok
  ok="$(jq -r '.ok' <<<"$json")"

  if [[ "$ok" != "true" ]]; then
    echo "Error: $name failed"
    exit 1
  fi
}

# =========================
# 0 Preflight self
# =========================

echo "== 0/7 Token-free target probe =="
umask 077
request_dir="$(mktemp -d)" || { echo 'Cannot create request directory' >&2; exit 1; }
capture_root="$request_dir"
next_request() {
  request_dir="$(mktemp -d "$capture_root/request.XXXXXXXX")" || {
    echo 'Cannot create request directory' >&2; exit 1
  }
}
trap 'rm -rf -- "$capture_root"' EXIT
next_request
probe_deadline="$MIGRATION_REQUEST_DEADLINE"
(( probe_deadline <= 10 )) || probe_deadline=10
probe_connect="$MIGRATION_CONNECT_TIMEOUT"
(( probe_connect <= probe_deadline )) || probe_connect="$probe_deadline"
if ! capture "$request_dir" "$probe_connect" "$probe_deadline" "$SELF_BOT_URL/" ||
   [[ "$(cat "$request_dir/curl-exit")" != 0 || "$(cat "$request_dir/http-status")" != 404 ]] ||
   ! jq -e '.ok == false and .error_code == 404 and .description == "Not Found"' "$request_dir/body.raw" >/dev/null 2>&1; then
  echo "Target did not return the expected Bot API response; stopped before token requests." >&2
  exit 1
fi
echo "Probe does not authenticate the host. Verify the endpoint independently."
echo "Source: $OFFICIAL_BOT_URL"
echo "Target: $SELF_BOT_URL"
echo "Webhook: ${WEBHOOK_URL_ARG:-inherit source if present}"
echo "Drop updates: $DROP_PENDING_UPDATES"
if ! read -r -p "Continue with token-bearing requests? [y/N]: " c; then exit 0; fi
case "$c" in y|Y|yes|YES) ;; *) exit 0 ;; esac


# =========================
# 1 getMe official
# =========================

echo
echo "== 1/7 Official getMe =="

next_request
api_get "$request_dir" "$OFFICIAL_BOT_URL" getMe
GETME="$(cat "$request_dir/body.raw")"
assert_ok "$GETME" "getMe official"
jq -e '.result.id | type == "number"' >/dev/null <<<"$GETME" || exit 1

BOT_ID="$(jq -r '.result.id' <<<"$GETME")"
BOT_NAME="$(jq -r '.result.first_name' <<<"$GETME")"
BOT_USERNAME="$(jq -r '.result.username' <<<"$GETME")"

echo "Bot:"
echo "ID: $BOT_ID"
echo "Name: $BOT_NAME"
echo "User: @$BOT_USERNAME"


# =========================
# 2 webhook info
# =========================

echo
echo "== 2/7 Webhook official =="

next_request
api_get "$request_dir" "$OFFICIAL_BOT_URL" getWebhookInfo
HOOK_INFO="$(cat "$request_dir/body.raw")"
assert_ok "$HOOK_INFO" "getWebhookInfo official"
jq -e '.result.url | type == "string"' >/dev/null <<<"$HOOK_INFO" || exit 1

CURRENT_WEBHOOK="$(jq -r '.result.url' <<<"$HOOK_INFO")"

if [[ "$CURRENT_WEBHOOK" != "" ]]; then
  echo "Current webhook:"
  echo "$CURRENT_WEBHOOK"
else
  echo "No webhook"
fi


# =========================
# decide webhook
# =========================

if [[ -n "$WEBHOOK_URL_ARG" ]]; then

  TARGET_WEBHOOK="$WEBHOOK_URL_ARG"

elif [[ -n "$CURRENT_WEBHOOK" ]]; then

  TARGET_WEBHOOK="$CURRENT_WEBHOOK"

else

  TARGET_WEBHOOK=""

fi


# =========================
# plan
# =========================

echo
echo "Plan:"
echo "Old API: $OFFICIAL_BOT_URL"
echo "New API: $SELF_BOT_URL"

if [[ -n "$TARGET_WEBHOOK" ]]; then
  echo "Webhook: $TARGET_WEBHOOK"
else
  echo "Webhook: polling mode"
fi

echo "Drop updates: $DROP_PENDING_UPDATES"
echo

# =========================
# 3 delete webhook
# =========================

echo
echo "== 3/7 deleteWebhook =="

next_request
api_post "$request_dir" "$OFFICIAL_BOT_URL" deleteWebhook \
  --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
DEL="$(cat "$request_dir/body.raw")"

assert_ok "$DEL" deleteWebhook
jq -e '.result == true' >/dev/null <<<"$DEL" || { echo "deleteWebhook result is not true" >&2; exit 1; }

echo "$DEL"


# =========================
# 4 logout
# =========================

echo
echo "== 4/7 logOut =="

next_request
api_post "$request_dir" "$OFFICIAL_BOT_URL" logOut
LOGOUT="$(cat "$request_dir/body.raw")"
assert_ok "$LOGOUT" logOut
jq -e '.result == true' >/dev/null <<<"$LOGOUT" || { echo "logOut result is not true" >&2; exit 1; }

echo "$LOGOUT"


# =========================
# 5 getMe self
# =========================

echo
echo "== 5/7 self getMe =="

next_request
api_get "$request_dir" "$SELF_BOT_URL" getMe
SELF_GETME="$(cat "$request_dir/body.raw")"
assert_ok "$SELF_GETME" "getMe self"
jq -e '.result.id | type == "number"' >/dev/null <<<"$SELF_GETME" || exit 1

echo "$SELF_GETME"


# =========================
# 6 set webhook
# =========================

if [[ -n "$TARGET_WEBHOOK" ]]; then

  echo
  echo "== 6/7 setWebhook =="

  next_request
  api_post "$request_dir" "$SELF_BOT_URL" setWebhook \
    --data-urlencode "url=$TARGET_WEBHOOK" \
    --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
  SET="$(cat "$request_dir/body.raw")"

  assert_ok "$SET" setWebhook
  jq -e '.result == true' >/dev/null <<<"$SET" || { echo "setWebhook result is not true" >&2; exit 1; }

  echo "$SET"

else

  echo
  echo "== 6/7 polling mode =="

fi


# =========================
# 7 check
# =========================

echo
echo "== 7/7 check =="

next_request
api_get "$request_dir" "$SELF_BOT_URL" getWebhookInfo
FINAL="$(cat "$request_dir/body.raw")"
assert_ok "$FINAL" final
jq -e '.result.url | type == "string"' >/dev/null <<<"$FINAL" || exit 1

echo "$FINAL"

FINAL_URL="$(jq -r '.result.url' <<<"$FINAL")"

if [[ -n "$TARGET_WEBHOOK" ]]; then

  if [[ "$FINAL_URL" == "$TARGET_WEBHOOK" ]]; then
    echo
    echo "DONE"
    echo "Webhook OK"
  else
    echo "Webhook mismatch"
    exit 1
  fi

else

  if [[ "$FINAL_URL" == "" ]]; then
    echo
    echo "DONE polling mode"
  else
    echo "Webhook still exists"
    exit 1
  fi

fi
