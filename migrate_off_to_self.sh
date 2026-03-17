#!/usr/bin/env bash
set -euo pipefail

# =========================
# Load .env if exists
# =========================

if [[ -f .env ]]; then
  echo "Loading environment variables from .env"
  set -a
  source .env
  set +a
fi

OFFICIAL_BOT_URL="https://api.telegram.org"

BOT_TOKEN="${1:-}"
SELF_BOT_URL="${2:-${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}}"
WEBHOOK_URL_ARG="${3:-${WEBHOOK_URL:-${WEB_HOOK:-}}}"
DROP_PENDING_UPDATES="${DROP_PENDING_UPDATES:-false}"

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

api_get() {
  curl -fsS "$1/bot$BOT_TOKEN/$2"
}

api_post() {
  local base="$1"
  local method="$2"
  shift 2

  curl -fsS -X POST "$base/bot$BOT_TOKEN/$method" "$@"
}

assert_ok() {
  local json="$1"
  local name="$2"

  local ok
  ok="$(jq -r '.ok' <<<"$json")"

  if [[ "$ok" != "true" ]]; then
    echo "Error: $name failed"
    echo "$json"
    exit 1
  fi
}

# =========================
# 0 Preflight self
# =========================

echo "== 0/7 Preflight self =="

if PREFLIGHT="$(api_get "$SELF_BOT_URL" getMe 2>/dev/null)"; then

  if [[ "$(jq -r '.ok' <<<"$PREFLIGHT")" == "true" ]]; then
    echo "Self-hosted API OK"
  else
    echo "Warning: self API reachable but not ready"
  fi

else

  echo "Warning: self API not responding yet"

fi


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

read -r -p "Continue? [y/N]: " c

case "$c" in
  y|Y|yes|YES) ;;
  *) exit 0 ;;
esac


# =========================
# 3 delete webhook
# =========================

echo
echo "== 3/7 deleteWebhook =="

DEL="$(api_post "$OFFICIAL_BOT_URL" deleteWebhook \
  --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
)"

assert_ok "$DEL" deleteWebhook

echo "$DEL"


# =========================
# 4 logout
# =========================

echo
echo "== 4/7 logOut =="

LOGOUT="$(api_post "$OFFICIAL_BOT_URL" logOut)"
assert_ok "$LOGOUT" logOut

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