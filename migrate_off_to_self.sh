#!/usr/bin/env bash
set -euo pipefail

# =========================
# Load a trusted shell file without overriding process configuration.
# =========================

process_self="${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}"
process_hook="${WEBHOOK_URL:-${WEB_HOOK:-}}"
process_drop="${DROP_PENDING_UPDATES:-}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${ENV_FILE+x} ]]; then
  env_path="$ENV_FILE"
  [[ -n "$env_path" && -f "$env_path" && -r "$env_path" && -s "$env_path" ]] || {
    echo "Error: invalid ENV_FILE" >&2; exit 1;
  }
else
  env_path="$script_dir/.env"
fi
file_self= file_hook= file_drop=
if [[ -e "$env_path" ]]; then
  [[ -f "$env_path" && -r "$env_path" ]] && bash -n "$env_path" 2>/dev/null || {
    echo "Error: cannot load environment file" >&2; exit 1;
  }
  # The file is trusted Bash. Capture only supported helper settings.
  if ! file_values="$(bash -e -c '
    unset SELF_BOT_URL TELEGRAM_BOT_URL WEBHOOK_URL WEB_HOOK DROP_PENDING_UPDATES
    source "$1" >/dev/null 2>&1
    printf "file_self=%q\nfile_hook=%q\nfile_drop=%q\n" \
      "${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}" "${WEBHOOK_URL:-${WEB_HOOK:-}}" "${DROP_PENDING_UPDATES:-}"
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
if [[ -n "$WEBHOOK_URL_ARG" && ! "$WEBHOOK_URL_ARG" =~ ^https?://[^/@?#[:space:]]+([^[:space:]]*)?$ ]]; then
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

request() {
  local response status
  response="$(curl -sS --connect-timeout 5 --max-time 30 -w '\n%{http_code}' "$@")" || return 1
  status="${response##*$'\n'}"
  [[ "$status" =~ ^2[0-9][0-9]$ ]] || return 1
  printf '%s' "${response%$'\n'*}"
}

api_get() {
  request "$1/bot$BOT_TOKEN/$2"
}

api_post() {
  local base="$1"
  local method="$2"
  shift 2

  request -X POST "$base/bot$BOT_TOKEN/$method" "$@"
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
if ! PREFLIGHT="$(curl -sS --connect-timeout 5 --max-time 10 -w '\n%{http_code}' "$SELF_BOT_URL/" 2>/dev/null)" ||
   [[ "${PREFLIGHT##*$'\n'}" != 404 ]] ||
   ! jq -e '.ok == false and .error_code == 404 and .description == "Not Found"' >/dev/null 2>&1 <<<"${PREFLIGHT%$'\n'*}"; then
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

GETME="$(api_get "$OFFICIAL_BOT_URL" getMe)"
assert_ok "$GETME" "getMe official"

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

HOOK_INFO="$(api_get "$OFFICIAL_BOT_URL" getWebhookInfo)"
assert_ok "$HOOK_INFO" "getWebhookInfo official"

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

DEL="$(api_post "$OFFICIAL_BOT_URL" deleteWebhook \
  --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
)"

assert_ok "$DEL" deleteWebhook
jq -e '.result == true' >/dev/null <<<"$DEL" || { echo "deleteWebhook result is not true" >&2; exit 1; }

echo "$DEL"


# =========================
# 4 logout
# =========================

echo
echo "== 4/7 logOut =="

LOGOUT="$(api_post "$OFFICIAL_BOT_URL" logOut)"
assert_ok "$LOGOUT" logOut
jq -e '.result == true' >/dev/null <<<"$LOGOUT" || { echo "logOut result is not true" >&2; exit 1; }

echo "$LOGOUT"


# =========================
# 5 getMe self
# =========================

echo
echo "== 5/7 self getMe =="

SELF_GETME="$(api_get "$SELF_BOT_URL" getMe)"
assert_ok "$SELF_GETME" "getMe self"

echo "$SELF_GETME"


# =========================
# 6 set webhook
# =========================

if [[ -n "$TARGET_WEBHOOK" ]]; then

  echo
  echo "== 6/7 setWebhook =="

  SET="$(api_post "$SELF_BOT_URL" setWebhook \
    --data-urlencode "url=$TARGET_WEBHOOK" \
    --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
  )"

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

FINAL="$(api_get "$SELF_BOT_URL" getWebhookInfo)"
assert_ok "$FINAL" final

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
