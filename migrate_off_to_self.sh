#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
fail() { echo "Error: $1" >&2; exit 1; }
keys=(SELF_BOT_URL TELEGRAM_BOT_URL WEBHOOK_URL WEB_HOOK DROP_PENDING_UPDATES WEBHOOK_ACTION WEBHOOK_TARGET_LOCAL WEBHOOK_SECRET_MODE WEBHOOK_SECRET_TOKEN WEBHOOK_SECRET_TOKEN_FILE WEBHOOK_ALLOWED_UPDATES WEBHOOK_MAX_CONNECTIONS WEBHOOK_IP_MODE WEBHOOK_IP_ADDRESS WEBHOOK_CERTIFICATE_MODE WEBHOOK_CERTIFICATE_FILE)
declare -A process_values file_values
for key in "${keys[@]}"; do
  if [[ -v $key ]]; then process_values[$key]="${!key}"; fi
done
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${ENV_FILE+x} ]]; then
  env_path="$ENV_FILE"
  [[ -n "$env_path" && -f "$env_path" && -r "$env_path" && -s "$env_path" ]] || fail 'invalid ENV_FILE'
else env_path="$script_dir/.env"; fi
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
if [[ -e "$env_path" ]]; then
  [[ -f "$env_path" && -r "$env_path" ]] && bash -n "$env_path" 2>/dev/null || fail 'cannot load environment file'
  # Trusted shell input, isolated from parent configuration. Only the exact whitelist returns.
  bash -e -c '
    file=$1; shift
    for key in "$@"; do unset "$key"; done
    source "$file" >/dev/null 2>&1
    for key in "$@"; do if [[ -v $key ]]; then printf "%s\0%s\0" "$key" "${!key}"; fi; done
  ' _ "$env_path" "${keys[@]}" >"$work/settings" 2>/dev/null || fail 'cannot load environment file'
  while IFS= read -r -d '' key && IFS= read -r -d '' value; do file_values[$key]="$value"; done <"$work/settings"
fi
setting() {
  local key=$1 fallback=${2-}
  if [[ -v process_values[$key] ]]; then printf '%s' "${process_values[$key]}"
  elif [[ -v file_values[$key] ]]; then printf '%s' "${file_values[$key]}"
  else printf '%s' "$fallback"; fi
}
url_setting() {
  local canonical=$1 alias=$2
  if [[ -v process_values[$canonical] ]]; then printf '%s' "${process_values[$canonical]}"
  elif [[ -v process_values[$alias] ]]; then printf '%s' "${process_values[$alias]}"
  elif [[ -v file_values[$canonical] ]]; then printf '%s' "${file_values[$canonical]}"
  elif [[ -v file_values[$alias] ]]; then printf '%s' "${file_values[$alias]}"; fi
}
BOT_TOKEN=${1-}
if (( $# >= 2 )); then SELF_BOT_URL=$2; else SELF_BOT_URL=$(url_setting SELF_BOT_URL TELEGRAM_BOT_URL); fi
if (( $# >= 3 )); then WEBHOOK_URL_ARG=$3; else WEBHOOK_URL_ARG=$(url_setting WEBHOOK_URL WEB_HOOK); fi
if (( $# >= 4 )); then WEBHOOK_ACTION=$4; else WEBHOOK_ACTION=$(setting WEBHOOK_ACTION); fi
case "$WEBHOOK_ACTION" in preserve|set|polling) ;; *) fail 'WEBHOOK_ACTION required: preserve|set|polling (fourth argument or environment)' ;; esac
OFFICIAL_BOT_URL=${OFFICIAL_BOT_URL-https://api.telegram.org}
DROP_PENDING_UPDATES=$(setting DROP_PENDING_UPDATES false)
WEBHOOK_TARGET_LOCAL=$(setting WEBHOOK_TARGET_LOCAL false)
for key in WEBHOOK_SECRET_MODE WEBHOOK_SECRET_TOKEN WEBHOOK_SECRET_TOKEN_FILE WEBHOOK_IP_MODE WEBHOOK_IP_ADDRESS WEBHOOK_CERTIFICATE_MODE WEBHOOK_CERTIFICATE_FILE; do
  printf -v "$key" '%s' "$(setting "$key")"
done
WEBHOOK_ALLOWED_UPDATES=$(setting WEBHOOK_ALLOWED_UPDATES '[]')
WEBHOOK_MAX_CONNECTIONS=$(setting WEBHOOK_MAX_CONNECTIONS 40)
for key in DROP_PENDING_UPDATES WEBHOOK_TARGET_LOCAL; do case "${!key}" in true|false) ;; *) fail "$key must be true/false" ;; esac; done
[[ "$BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || fail 'BOT_TOKEN required in Bot API format'
[[ -n "$SELF_BOT_URL" ]] || fail 'SELF_BOT_URL required'
SELF_BOT_URL=${SELF_BOT_URL%/}; OFFICIAL_BOT_URL=${OFFICIAL_BOT_URL%/}
for endpoint in "$SELF_BOT_URL" "$OFFICIAL_BOT_URL"; do
  [[ "$endpoint" =~ ^https?://[^/@?#[:space:]\\]+(/[^?#[:space:]\\]*)?$ ]] || fail 'Invalid API endpoint'
done
target_host=${SELF_BOT_URL#*://}; target_host=${target_host%%/*}; target_host=${target_host%%:*}; target_host=${target_host%.}; target_host=${target_host,,}
[[ "$SELF_BOT_URL" != "$OFFICIAL_BOT_URL" && "$target_host" != api.telegram.org ]] || fail 'SELF_BOT_URL must not be api.telegram.org'
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "need command '$1'"; }
need_cmd curl; need_cmd jq
valid_ip() {
  local value=$1 part left right; local -a groups
  if [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    IFS=. read -r -a groups <<<"$value"
    for part in "${groups[@]}"; do (( 10#$part <= 255 )) || return 1; done
  else
    [[ "$value" =~ ^[0-9a-fA-F:]+$ && "$value" == *:* && "$value" != *:::* ]] || return 1
    if [[ "$value" == *::* ]]; then
      left=${value%%::*}; right=${value#*::}
      [[ "$right" != *::* ]] || return 1
      read -r -a groups <<<"${left//:/ } ${right//:/ }"
      (( ${#groups[@]} < 8 )) || return 1
    else
      [[ "$value" != :* && "$value" != *: ]] || return 1
      IFS=: read -r -a groups <<<"$value"
      (( ${#groups[@]} == 8 )) || return 1
    fi
    for part in "${groups[@]}"; do [[ "$part" =~ ^[0-9a-fA-F]{1,4}$ ]] || return 1; done
  fi
}
valid_receiver() {
  local value=$1 authority host port= label; local -a labels
  [[ "$value" =~ ^https?://([^/?#[:space:]\\]+)([/?][^#[:space:]\\]*)?$ ]] || return 1
  authority=${BASH_REMATCH[1]}
  if [[ "$authority" == \[* ]]; then
    [[ "$authority" =~ ^\[([0-9a-fA-F:]+)\](:([0-9]{1,5}))?$ ]] || return 1
    host=${BASH_REMATCH[1]}; port=${BASH_REMATCH[3]-}; valid_ip "$host" || return 1
  else
    [[ "$authority" =~ ^([A-Za-z0-9.-]+)(:([0-9]{1,5}))?$ ]] || return 1
    host=${BASH_REMATCH[1]}; port=${BASH_REMATCH[3]-}; host=${host%.}
    [[ -n "$host" && "$host" != *..* && ${#host} -le 253 ]] || return 1
    IFS=. read -r -a labels <<<"$host"
    for label in "${labels[@]}"; do [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]] || return 1; done
    if [[ "$host" =~ ^[0-9.]+$ ]]; then valid_ip "$host" || return 1; fi
  fi
  [[ -z "$port" ]] || (( 10#$port >= 1 && 10#$port <= 65535 )) || return 1
}
validate_profile() {
  valid_receiver "$TARGET_WEBHOOK" || fail 'Invalid webhook URL'
  [[ "$TARGET_WEBHOOK" == https://* || "$WEBHOOK_TARGET_LOCAL" == true ]] || fail 'HTTP webhook requires WEBHOOK_TARGET_LOCAL=true'
  [[ "$WEBHOOK_MAX_CONNECTIONS" =~ ^[1-9][0-9]{0,5}$ ]] || fail 'Invalid WEBHOOK_MAX_CONNECTIONS'
  local limit=100
  [[ "$WEBHOOK_TARGET_LOCAL" == true ]] && limit=100000
  (( WEBHOOK_MAX_CONNECTIONS <= limit )) || fail 'WEBHOOK_MAX_CONNECTIONS exceeds capability'
  jq -e 'type == "array" and all(.[]; type == "string")' >/dev/null 2>&1 <<<"$WEBHOOK_ALLOWED_UPDATES" || fail 'Invalid WEBHOOK_ALLOWED_UPDATES'
  case "$WEBHOOK_SECRET_MODE" in
    none) WEBHOOK_SECRET_TOKEN= ;;
    provided)
      [[ -z "$WEBHOOK_SECRET_TOKEN" || -z "$WEBHOOK_SECRET_TOKEN_FILE" ]] || fail 'Choose token or token file'
      if [[ -n "$WEBHOOK_SECRET_TOKEN_FILE" ]]; then
        [[ -f "$WEBHOOK_SECRET_TOKEN_FILE" && -r "$WEBHOOK_SECRET_TOKEN_FILE" ]] || fail 'Unreadable secret file'
        WEBHOOK_SECRET_TOKEN=$(cat -- "$WEBHOOK_SECRET_TOKEN_FILE")
      fi
      [[ "$WEBHOOK_SECRET_TOKEN" =~ ^[A-Za-z0-9_-]{1,256}$ ]] || fail 'Invalid webhook secret' ;;
    *) fail 'Choose WEBHOOK_SECRET_MODE=provided|none' ;;
  esac
  case "$WEBHOOK_IP_MODE" in
    dns) WEBHOOK_IP_ADDRESS= ;;
    fixed) valid_ip "$WEBHOOK_IP_ADDRESS" || fail 'Invalid fixed IP' ;;
    *) fail 'Choose WEBHOOK_IP_MODE=dns|fixed' ;;
  esac
  case "$WEBHOOK_CERTIFICATE_MODE" in
    none) ;;
    provided)
      [[ -f "$WEBHOOK_CERTIFICATE_FILE" && -r "$WEBHOOK_CERTIFICATE_FILE" && -s "$WEBHOOK_CERTIFICATE_FILE" ]] || fail 'Unreadable public certificate'
      local pem; pem=$(cat -- "$WEBHOOK_CERTIFICATE_FILE")
      [[ "$pem" == *'-----BEGIN CERTIFICATE-----'* && "$pem" != *'PRIVATE KEY'* ]] || fail 'Expected public PEM, never private key'
      need_cmd openssl
      openssl x509 -in "$WEBHOOK_CERTIFICATE_FILE" -noout >/dev/null 2>&1 || fail 'Invalid public PEM' ;;
    *) fail 'Choose WEBHOOK_CERTIFICATE_MODE=provided|none' ;;
  esac
}
if [[ "$WEBHOOK_ACTION" == set ]]; then TARGET_WEBHOOK=$WEBHOOK_URL_ARG; validate_profile; fi

# Token and form values are read by curl from protected files, never interpolated into shell code.
config_line() { local value=$2; value=${value//\\/\\\\}; value=${value//\"/\\\"}; printf '%s = "%s"\n' "$1" "$value" >>"$work/request"; }
request() {
  local base=$1 method=$2 mutation=false response status; shift 2
  case "$method" in getMe|getWebhookInfo) ;; *) mutation=true ;; esac
  [[ "$base$BOT_TOKEN" != *$'\n'* && "$base$BOT_TOKEN" != *$'\r'* ]] || fail 'Invalid request input'
  : >"$work/request"
  config_line url "$base/bot$BOT_TOKEN/$method"
  if [[ "$mutation" == true ]]; then config_line request POST; fi
  local key value index=0
  while (( $# )); do
    key=$1; value=$2; shift 2
    printf '%s' "$value" >"$work/field$index"
    if [[ "$method" == setWebhook && "$WEBHOOK_CERTIFICATE_MODE" == provided ]]; then
      config_line form "$key=<\"$work/field$index\""
    else config_line data-urlencode "$key@$work/field$index"; fi
    ((index+=1))
  done
  if [[ "$method" == setWebhook && "$WEBHOOK_CERTIFICATE_MODE" == provided ]]; then
    cp -- "$WEBHOOK_CERTIFICATE_FILE" "$work/certificate.pem"
    config_line form "certificate=@\"$work/certificate.pem\";type=application/x-pem-file"
  fi
  response=$(curl -q -sS --proto '=http,https' --max-redirs 0 --connect-timeout 5 --max-time 30 --config "$work/request" -w '\n%{http_code}' 2>/dev/null) || fail 'UNKNOWN: response lost; stop and reconcile, never retry automatically'
  status=${response##*$'\n'}; response=${response%$'\n'*}
  [[ "$status" =~ ^2[0-9][0-9]$ ]] || fail "Request failed with HTTP $status; stop and reconcile"
  jq -e '.ok == true' >/dev/null 2>&1 <<<"$response" || fail 'UNKNOWN: invalid API response; stop and reconcile'
  case "$method" in
    getMe) jq -e '.result.id | type == "number"' >/dev/null 2>&1 <<<"$response" ;;
    getWebhookInfo) jq -e '.result.url | type == "string"' >/dev/null 2>&1 <<<"$response" ;;
    *) jq -e '.result == true' >/dev/null 2>&1 <<<"$response" ;;
  esac || fail 'UNKNOWN: invalid typed result; stop and reconcile'
  printf '%s' "$response"
}
echo '== Token-free target probe =='
PREFLIGHT=$(curl -q -sS --proto '=http,https' --max-redirs 0 --connect-timeout 5 --max-time 10 -w '\n%{http_code}' "$SELF_BOT_URL/" 2>/dev/null) || fail 'Target probe failed'
[[ "${PREFLIGHT##*$'\n'}" == 404 ]] && jq -e '.ok == false and .error_code == 404 and .description == "Not Found"' >/dev/null 2>&1 <<<"${PREFLIGHT%$'\n'*}" || fail 'Target did not return the expected Bot API response'
echo "Action: $WEBHOOK_ACTION; source detach drop=false; target drop=$DROP_PENDING_UPDATES"
echo "Source: $OFFICIAL_BOT_URL"
echo "Target: $SELF_BOT_URL"
echo 'Probe does not authenticate the host. Verify the endpoint independently.'
read -r -p 'Continue with token-bearing requests? [y/N]: ' answer || exit 0
case "$answer" in y|Y|yes|YES) ;; *) exit 0 ;; esac
GETME=$(request "$OFFICIAL_BOT_URL" getMe)
BOT_ID=$(jq -r '.result.id' <<<"$GETME")
HOOK_INFO=$(request "$OFFICIAL_BOT_URL" getWebhookInfo)
CURRENT_WEBHOOK=$(jq -r '.result.url' <<<"$HOOK_INFO")
TARGET_WEBHOOK=
case "$WEBHOOK_ACTION" in
  set) TARGET_WEBHOOK=$WEBHOOK_URL_ARG ;;
  preserve)
    TARGET_WEBHOOK=$CURRENT_WEBHOOK
    if [[ -n "$TARGET_WEBHOOK" ]]; then
      jq -e '.result.has_custom_certificate | type == "boolean"' >/dev/null 2>&1 <<<"$HOOK_INFO" || fail 'Unknown source certificate policy'
      WEBHOOK_ALLOWED_UPDATES=$(jq -c '.result | if has("allowed_updates") then .allowed_updates else [] end' <<<"$HOOK_INFO")
      if jq -e '.result | has("max_connections")' >/dev/null <<<"$HOOK_INFO"; then
        jq -e '.result.max_connections | type == "number"' >/dev/null <<<"$HOOK_INFO" || fail 'Invalid source max_connections'
        WEBHOOK_MAX_CONNECTIONS=$(jq -r '.result.max_connections' <<<"$HOOK_INFO")
      elif [[ ! -v process_values[WEBHOOK_MAX_CONNECTIONS] && ! -v file_values[WEBHOOK_MAX_CONNECTIONS] ]]; then
        fail 'Source max_connections missing; supply an explicit value'
      fi
      if [[ $(jq -r '.result.has_custom_certificate' <<<"$HOOK_INFO") == true ]]; then WEBHOOK_CERTIFICATE_MODE=provided; else WEBHOOK_CERTIFICATE_MODE=none; fi
      if [[ "$WEBHOOK_IP_MODE" == fixed ]]; then
        [[ $(jq -r '.result.ip_address' <<<"$HOOK_INFO") == "$WEBHOOK_IP_ADDRESS" ]] || fail 'Fixed IP does not match source'
      fi
      validate_profile
    fi ;;
  polling) ;;
esac
TARGET_METHOD=deleteWebhook
[[ -z "$TARGET_WEBHOOK" ]] || TARGET_METHOD=setWebhook
echo "Resolved target: $TARGET_METHOD; source drop=false; target drop=$DROP_PENDING_UPDATES"
echo 'true intentionally discards target backlog; false does not guarantee queue transfer.'
read -r -p 'Apply resolved migration? [y/N]: ' answer || exit 0
case "$answer" in y|Y|yes|YES) ;; *) exit 0 ;; esac
echo '== Source detach =='
request "$OFFICIAL_BOT_URL" deleteWebhook drop_pending_updates false >/dev/null
request "$OFFICIAL_BOT_URL" logOut >/dev/null
echo '== First target token request =='
SELF_GETME=$(request "$SELF_BOT_URL" getMe)
[[ $(jq -r '.result.id' <<<"$SELF_GETME") == "$BOT_ID" ]] || fail 'Bot identity mismatch; reconcile'
echo "== Target $TARGET_METHOD =="
if [[ "$TARGET_METHOD" == setWebhook ]]; then
  args=(url "$TARGET_WEBHOOK" drop_pending_updates "$DROP_PENDING_UPDATES" allowed_updates "$WEBHOOK_ALLOWED_UPDATES" max_connections "$WEBHOOK_MAX_CONNECTIONS" secret_token "$WEBHOOK_SECRET_TOKEN")
  [[ "$WEBHOOK_IP_MODE" != fixed ]] || args+=(ip_address "$WEBHOOK_IP_ADDRESS")
  request "$SELF_BOT_URL" setWebhook "${args[@]}" >/dev/null
else request "$SELF_BOT_URL" deleteWebhook drop_pending_updates "$DROP_PENDING_UPDATES" >/dev/null; fi
FINAL=$(request "$SELF_BOT_URL" getWebhookInfo)
jq -e --arg expected "$TARGET_WEBHOOK" '.result.url == $expected' >/dev/null 2>&1 <<<"$FINAL" || fail 'UNKNOWN: webhook readback mismatch; reconcile'
if [[ "$TARGET_METHOD" == setWebhook ]]; then
  jq -e --argjson allowed "$WEBHOOK_ALLOWED_UPDATES" --argjson max "$WEBHOOK_MAX_CONNECTIONS" --argjson cert "$([[ "$WEBHOOK_CERTIFICATE_MODE" == provided ]] && echo true || echo false)" --arg ip "$WEBHOOK_IP_ADDRESS" '
    .result | (if has("allowed_updates") then .allowed_updates else [] end) as $observed
    | ($observed | type == "array" and all(.[]; type == "string"))
    and ($observed | sort | unique) == ($allowed | sort | unique)
    and .max_connections == $max and .has_custom_certificate == $cert
    and ($ip == "" or .ip_address == $ip)' >/dev/null 2>&1 <<<"$FINAL" || fail 'UNKNOWN: profile readback mismatch; reconcile'
fi
echo 'DONE: configuration readback confirmed; delivery requires a separate test update.'
