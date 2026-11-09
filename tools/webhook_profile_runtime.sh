# Canonical standalone Bash runtime; embedded by embed_webhook_profile.cjs.
wp_fail() { printf '%s\n' "$1" >&2; exit "${2:-1}"; }
wp_jq() { command jq "$@" 2>/dev/null; }
wp_load() {
  set +x
  set +v
  umask 077
  local key file_values env_path
  local -a names=(BOT_TOKEN BOT_TOKEN_FILE SELF_BOT_URL TELEGRAM_BOT_URL OFFICIAL_BOT_URL WEBHOOK_URL WEB_HOOK DROP_PENDING_UPDATES MIGRATION_MODE MIGRATION_CONNECT_TIMEOUT MIGRATION_REQUEST_DEADLINE WEBHOOK_SECRET_MODE WEBHOOK_SECRET_TOKEN WEBHOOK_SECRET_TOKEN_FILE WEBHOOK_ALLOWED_UPDATES WEBHOOK_MAX_CONNECTIONS WEBHOOK_TARGET_LOCAL WEBHOOK_IP_MODE WEBHOOK_IP_ADDRESS WEBHOOK_CERTIFICATE_MODE WEBHOOK_CERTIFICATE_FILE)
  local -A process_values=() process_present=() file_present=() file_inputs=()
  for key in "${names[@]}"; do
    if [[ -v $key ]]; then process_present[$key]=1; process_values[$key]="${!key}"; fi
    unset "$key"
  done
  if [[ ${ENV_FILE+x} ]]; then
    env_path=$ENV_FILE
    [[ -n $env_path && -f $env_path && -r $env_path && -s $env_path ]] || wp_fail 'Invalid ENV_FILE'
  else env_path="$WP_SCRIPT_DIR/.env"; fi
  if [[ -e $env_path ]]; then
    [[ -f $env_path && -r $env_path ]] && bash -n "$env_path" 2>/dev/null || wp_fail 'Cannot load trusted environment file'
    file_values=$(bash -e -c '
      source "$1" >/dev/null 2>&1
      set +x; set +v
      shift
      for key; do
        if [[ -v $key ]]; then printf "file_present[%q]=1\nfile_inputs[%q]=%q\n" "$key" "$key" "${!key}"; fi
      done
    ' _ "$env_path" "${names[@]}") || wp_fail 'Cannot load trusted environment file'
    eval "$file_values"
  fi
  for key in "${names[@]}"; do
    if [[ ${process_present[$key]+x} ]]; then printf -v "$key" '%s' "${process_values[$key]}"
    elif [[ ${file_present[$key]+x} ]]; then printf -v "$key" '%s' "${file_inputs[$key]}"; fi
    export -n "$key" 2>/dev/null || :
  done
  # A process value/file pair replaces the file pair as one unit, including empties.
  for key in BOT_TOKEN WEBHOOK_SECRET_TOKEN; do
    if [[ ${process_present[$key]+x} || ${process_present[${key}_FILE]+x} ]]; then
      unset "$key" "${key}_FILE"
      [[ ! ${process_present[$key]+x} ]] || printf -v "$key" '%s' "${process_values[$key]}"
      [[ ! ${process_present[${key}_FILE]+x} ]] || printf -v "${key}_FILE" '%s' "${process_values[${key}_FILE]}"
    fi
  done
  # Alias priorities are resolved inside each configuration tier.
  if (( $# >= 2 )); then SELF_BOT_URL=$2
  elif [[ ${process_present[SELF_BOT_URL]+x} || ${process_present[TELEGRAM_BOT_URL]+x} ]]; then SELF_BOT_URL=${process_values[SELF_BOT_URL]-${process_values[TELEGRAM_BOT_URL]-}}
  else SELF_BOT_URL=${file_inputs[SELF_BOT_URL]-${file_inputs[TELEGRAM_BOT_URL]-}}; fi
  if (( $# >= 3 )); then WEBHOOK_URL=$3
  elif [[ ${process_present[WEBHOOK_URL]+x} || ${process_present[WEB_HOOK]+x} ]]; then WEBHOOK_URL=${process_values[WEBHOOK_URL]-${process_values[WEB_HOOK]-}}
  else WEBHOOK_URL=${file_inputs[WEBHOOK_URL]-${file_inputs[WEB_HOOK]-}}; fi
  if (( $# >= 1 )) && [[ -n $1 ]]; then BOT_TOKEN=$1; unset BOT_TOKEN_FILE; fi
  OFFICIAL_BOT_URL=${OFFICIAL_BOT_URL-https://api.telegram.org}
  MIGRATION_MODE=${MIGRATION_MODE-official-to-self}
  DROP_PENDING_UPDATES=${DROP_PENDING_UPDATES-false}
  MIGRATION_CONNECT_TIMEOUT=${MIGRATION_CONNECT_TIMEOUT-5}
  MIGRATION_REQUEST_DEADLINE=${MIGRATION_REQUEST_DEADLINE-30}
  local value maximum name
  for name in MIGRATION_CONNECT_TIMEOUT MIGRATION_REQUEST_DEADLINE; do
    value=${!name}; maximum=300
    [[ $name != MIGRATION_CONNECT_TIMEOUT ]] || maximum=60
    [[ $value =~ ^[0-9]{1,10}$ ]] || wp_fail "Invalid $name"
    while [[ ${#value} -gt 1 && ${value:0:1} == 0 ]]; do value=${value:1}; done
    [[ ${#value} -le 3 ]] && (( 10#$value >= 1 && 10#$value <= maximum )) || wp_fail "Invalid $name"
    printf -v "$name" '%s' "$((10#$value))"
  done
  (( MIGRATION_CONNECT_TIMEOUT <= MIGRATION_REQUEST_DEADLINE )) || wp_fail 'Connect timeout exceeds request deadline'
  WEBHOOK_TARGET_LOCAL=${WEBHOOK_TARGET_LOCAL-false}
  [[ $DROP_PENDING_UPDATES == true || $DROP_PENDING_UPDATES == false ]] || wp_fail 'Invalid drop policy'
  [[ $WEBHOOK_TARGET_LOCAL == true || $WEBHOOK_TARGET_LOCAL == false ]] || wp_fail 'Invalid local capability'
  SELF_BOT_URL=${SELF_BOT_URL%/}; OFFICIAL_BOT_URL=${OFFICIAL_BOT_URL%/}
  [[ $SELF_BOT_URL != https://api.telegram.org || $WEBHOOK_TARGET_LOCAL != true ]] || wp_fail 'Official target does not have local capability'
  [[ -n $SELF_BOT_URL ]] || wp_fail 'SELF_BOT_URL required'
  for key in "$SELF_BOT_URL" "$OFFICIAL_BOT_URL"; do
    [[ $key =~ ^https?://[^/@?#[:space:]]+(/[^?#[:space:]]*)?$ ]] || wp_fail 'Invalid API endpoint'
  done
  case $MIGRATION_MODE in
    official-to-self) [[ $SELF_BOT_URL != "$OFFICIAL_BOT_URL" ]] || wp_fail 'Source and target must differ' ;;
    hook-only|target-stage) ;;
    *) wp_fail 'Manual lifecycle/state transition required; use a separate target-stage' ;;
  esac
  for key in curl jq; do command -v "$key" >/dev/null || wp_fail "Missing prerequisite: $key"; done
  WP_TMP=$(mktemp -d /tmp/webhook-profile.XXXXXXXX) || wp_fail 'Cannot create private temporary directory'
  trap 'rm -rf -- "$WP_TMP"' EXIT
  trap 'exit 2' HUP INT TERM
  if [[ ${BOT_TOKEN_FILE+x} ]]; then
    [[ ! ${BOT_TOKEN+x} ]] || wp_fail 'Conflicting bot token inputs'
    wp_private_file "$BOT_TOKEN_FILE" "$WP_TMP/token"
    BOT_TOKEN=$(wp_jq -Rsrj 'sub("\r?\n$";"")' "$WP_TMP/token") || wp_fail 'Cannot read bot token'
  fi
  [[ ${BOT_TOKEN-} =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || wp_fail 'Invalid bot token'
}
wp_private_file() {
  local input=$1 output=$2 resolved checkout
  [[ -n $input && -f $input && -r $input && -s $input ]] || wp_fail 'Protected input file unavailable'
  command -v realpath >/dev/null || wp_fail 'realpath required for protected input files'
  resolved=$(realpath -- "$input") || wp_fail 'Cannot resolve protected input file'
  checkout=$(realpath -- "$WP_SCRIPT_DIR") || wp_fail 'Cannot resolve helper directory'
  case $resolved in "$checkout"|"$checkout"/*) wp_fail 'Protected inputs must be outside checkout/webroot' ;; esac
  [[ $(wc -c < "$resolved") -le 1048576 ]] || wp_fail 'Protected input too large'
  cat -- "$resolved" > "$output" || wp_fail 'Cannot snapshot protected input'
}
wp_snapshot_valid() {
  wp_jq -e '
    def uint: type=="number" and .>=0 and floor==.;
    .ok==true and (.result|type=="object") and (.result|
      (.url|type=="string") and (.pending_update_count|uint) and
      (.has_custom_certificate|type=="boolean") and
      (if has("allowed_updates") then (.allowed_updates|type=="array" and all(.[];type=="string")) else true end) and
      (if has("max_connections") then (.max_connections|uint and .>=1) else true end) and
      (if has("ip_address") then (.ip_address|type=="string") else true end) and
      (if has("last_error_date") then (.last_error_date|uint) else true end) and
      (if has("last_synchronization_error_date") then (.last_synchronization_error_date|uint) else true end) and
      (if has("last_error_message") then (.last_error_message|type=="string") else true end))' "$1" >/dev/null
}
# BEGIN RESOLVER
wp_resolve() { wp_jq '
    def own($o;$k): $o | type == "object" and has($k);
    def ipv4: type == "string" and test("^([0-9]{1,3}\\.){3}[0-9]{1,3}$") and
      (split(".") | all(.[]; (tonumber <= 255) and (tostring == (tonumber|tostring))));
    . as $i | (.source // {}) as $s | (.desired // {}) as $d |
    ($s|type == "object" and (.url|type == "string")) as $valid |
    {version:1,profile:{},provenance:{},missing:[],invalid:[]} |
    reduce ["url","allowed_updates","max_connections"][] as $k (.;
      if own($d;$k) then .profile[$k]=$d[$k] | .provenance[$k]="explicit"
      elif $valid and own($s;$k) then .profile[$k]=$s[$k] | .provenance[$k]="source"
      elif $valid and $k=="allowed_updates" then .profile[$k]=[] | .provenance[$k]="documented-default"
      else .missing += [$k] end) |
    .profile.secret_mode=($d.secret.mode // "unknown") |
    .profile.ip_mode=($d.ip.mode // "unknown") |
    .profile.certificate_mode=($d.certificate.mode //
      (if $valid and $s.has_custom_certificate==false then "none" else "unknown" end)) |
    .provenance.secret_mode="explicit" | .provenance.ip_mode="explicit" |
    .provenance.certificate_mode=(if $d.certificate.mode then "explicit" else "source" end) |
    if .profile.secret_mode=="provided" then
      if ($d.secret.value|type=="string" and test("^[A-Za-z0-9_-]{1,256}$") and (test("[\r\n]")|not)) then . else .invalid += ["secret_token"] end
    elif .profile.secret_mode=="none" then
      if ($d.secret.value // "")!="" then .invalid += ["secret_token"] else . end
    elif .profile.secret_mode=="unknown" then .missing += ["secret_mode"] else .invalid += ["secret_mode"] end |
    if .profile.ip_mode=="fixed" or .profile.ip_mode=="pinned" then
      .profile.ip_mode="pinned" |
      .profile.ip_address=$d.ip.address | if (.profile.ip_address|ipv4) then . else .invalid += ["ip_address"] end
    elif .profile.ip_mode=="dns" then
      if ($d.ip.address // "")!="" then .invalid += ["ip_address"] else . end
    elif .profile.ip_mode=="unknown" then .missing += ["ip_mode"] else .invalid += ["ip_mode"] end |
    if .profile.certificate_mode=="provided" then
      if ($d.certificate.value|type=="string" and test("-----BEGIN CERTIFICATE-----\\r?\\n(?:[A-Za-z0-9+/]{1,64}={0,2}\\r?\\n)+-----END CERTIFICATE-----") and (test("PRIVATE KEY")|not)) then . else .invalid += ["certificate"] end
    elif .profile.certificate_mode=="none" then
      if ($d.certificate.value // "")!="" then .invalid += ["certificate"] else . end
    elif .profile.certificate_mode=="unknown" then .missing += ["certificate_mode"] else .invalid += ["certificate_mode"] end |
    if own(.profile;"url") and (.profile.url|type!="string") then .invalid += ["url"] else . end |
    if own(.profile;"allowed_updates") and (.profile.allowed_updates|type=="array" and all(.[];type=="string")|not) then .invalid += ["allowed_updates"] else . end |
    if own(.profile;"max_connections") and (.profile.max_connections|type=="number" and .==floor and .>=1 and .<=(if $i.target_local==true then 100000 else 100 end)|not) then .invalid += ["max_connections"] else . end |
    reduce (.provenance|keys[]) as $k (.; if .provenance[$k]=="explicit" and $i.provenance[$k] then .provenance[$k]=$i.provenance[$k] else . end) |
    .complete=((.missing|length)==0 and (.invalid|length)==0)
'; }
# END RESOLVER
wp_preflight() {
  local source=$1 secret='' cert=''
  WP_HOOK=$(wp_jq -r '.result.url' "$source") || wp_fail 'Invalid source snapshot'
  [[ -z $WEBHOOK_URL ]] || WP_HOOK=$WEBHOOK_URL
  if [[ -z $WP_HOOK ]]; then WP_PROFILE='{"profile":{"url":""},"complete":true}'; return; fi
  [[ $WP_HOOK =~ ^https?://[^/@?#[:space:]]+([^[:space:]#]*)?$ ]] || wp_fail 'Invalid webhook URL'
  [[ $SELF_BOT_URL != https://api.telegram.org || $WP_HOOK == https://* ]] || wp_fail 'Cloud webhook requires HTTPS'
  if [[ ${WEBHOOK_SECRET_TOKEN_FILE+x} ]]; then
    [[ ! ${WEBHOOK_SECRET_TOKEN+x} ]] || wp_fail 'Conflicting secret sources'
    wp_private_file "$WEBHOOK_SECRET_TOKEN_FILE" "$WP_TMP/secret.input"
    wp_jq -Rsrj 'sub("\r?\n$";"")' "$WP_TMP/secret.input" > "$WP_TMP/secret" || wp_fail 'Cannot read secret file'
  else printf '%s' "${WEBHOOK_SECRET_TOKEN-}" > "$WP_TMP/secret"; fi
  if [[ ${WEBHOOK_CERTIFICATE_FILE+x} ]]; then
    wp_private_file "$WEBHOOK_CERTIFICATE_FILE" "$WP_TMP/certificate"
  else : > "$WP_TMP/certificate"; fi
  wp_jq -n --slurpfile source "$source" --rawfile secret "$WP_TMP/secret" --rawfile cert "$WP_TMP/certificate" \
    --arg url "$WP_HOOK" --arg explicit_url "${WEBHOOK_URL:+yes}" --arg sm "${WEBHOOK_SECRET_MODE-unknown}" --arg im "${WEBHOOK_IP_MODE-unknown}" \
    --arg ip "${WEBHOOK_IP_ADDRESS-}" --arg cm "${WEBHOOK_CERTIFICATE_MODE-auto}" --arg local "$WEBHOOK_TARGET_LOCAL" \
    --arg au "${WEBHOOK_ALLOWED_UPDATES-}" --arg mc "${WEBHOOK_MAX_CONNECTIONS-}" \
    --arg ap "${WEBHOOK_ALLOWED_UPDATES+x}" --arg mp "${WEBHOOK_MAX_CONNECTIONS+x}" '
      {source:$source[0].result,target_local:($local=="true"),desired:{url:$url,secret:{mode:$sm,value:$secret},ip:{mode:$im,address:$ip},certificate:{value:$cert}},
       provenance:{secret_mode:"protected-config",ip_mode:"protected-config",certificate_mode:"protected-config",allowed_updates:"protected-config",max_connections:"protected-config"}} |
      if $explicit_url!="yes" then del(.desired.url) else . end |
      if $cm!="auto" then .desired.certificate.mode=$cm else . end |
      if $ap=="x" then .desired.allowed_updates=($au|fromjson) else . end |
      if $mp=="x" then .desired.max_connections=(if ($mc|test("^[1-9][0-9]*$")) then ($mc|tonumber) else null end)
      elif ($source[0].result|has("max_connections")|not) then .desired.max_connections=40 else . end' \
      > "$WP_TMP/input" || wp_fail 'Invalid profile inputs'
  WP_PROFILE=$(wp_resolve < "$WP_TMP/input") || wp_fail 'Cannot resolve profile'
  wp_jq -e '.complete==true' >/dev/null <<< "$WP_PROFILE" || wp_fail 'Profile incomplete or invalid; source unchanged'
  if [[ $(wp_jq -r '.profile.certificate_mode' <<< "$WP_PROFILE") == provided ]]; then
    command -v openssl >/dev/null || wp_fail 'openssl required to validate public certificate'
    openssl x509 -in "$WP_TMP/certificate" -noout >/dev/null 2>&1 || wp_fail 'Invalid X.509 certificate'
  fi
  unset WEBHOOK_SECRET_TOKEN

  printf 'profile_input_complete=true; private_material=provided-or-none; delivery_confirmed=false\n'
}
wp_request() {
  local base=$1 method=$2 status
  shift 2
  printf '%s' "$base/bot$BOT_TOKEN/$method" | wp_jq -Rsr '"url = " + tojson' > "$WP_TMP/request.conf" || wp_fail 'Cannot prepare private request'
  status=$(curl -q -sS --connect-timeout "$MIGRATION_CONNECT_TIMEOUT" --max-time "${WP_REQUEST_TIMEOUT:-$MIGRATION_REQUEST_DEADLINE}" --globoff --proto '=http,https' \
    --output "$WP_TMP/response" --write-out '%{http_code}' --config "$WP_TMP/request.conf" "$@" 2>/dev/null) || wp_fail 'UNKNOWN: response unavailable; reconcile without retry' 2
  [[ $status =~ ^2[0-9][0-9]$ ]] || wp_fail 'API HTTP rejection; stop and reconcile'
  wp_jq -e '.ok==true and has("result")' "$WP_TMP/response" >/dev/null || wp_fail 'API rejected or invalid response; stop and reconcile' 2
  case $method in
    getMe) wp_jq -e '.result.id|type=="number" and .>0 and floor==.' "$WP_TMP/response" >/dev/null || wp_fail 'Invalid bot identity' 2 ;;
    getWebhookInfo) wp_snapshot_valid "$WP_TMP/response" || wp_fail 'Invalid WebhookInfo' 2 ;;
    *) wp_jq -e '.result==true' "$WP_TMP/response" >/dev/null || wp_fail 'Mutation result not true; stop and reconcile' 2 ;;
  esac
}
wp_transport_ready() { :; }
wp_set() {
  local key cert_mode secret_mode ip_mode
  local -a args=(-X POST)
  cert_mode=$(wp_jq -r '.profile.certificate_mode' <<< "$WP_PROFILE")
  secret_mode=$(wp_jq -r '.profile.secret_mode' <<< "$WP_PROFILE")
  ip_mode=$(wp_jq -r '.profile.ip_mode' <<< "$WP_PROFILE")
  for key in url allowed_updates max_connections; do
    wp_jq -rj --arg key "$key" '.profile[$key]|if type=="array" then tojson else tostring end' <<< "$WP_PROFILE" > "$WP_TMP/$key"
    if [[ $cert_mode == provided ]]; then args+=(--form "$key=<\"$WP_TMP/$key\"")
    else args+=(--data-urlencode "$key@$WP_TMP/$key"); fi
  done
  if [[ $cert_mode == provided ]]; then args+=(--form-string "drop_pending_updates=$DROP_PENDING_UPDATES")
  else args+=(--data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"); fi
  if [[ $ip_mode == pinned ]]; then
    wp_jq -rj '.profile.ip_address' <<< "$WP_PROFILE" > "$WP_TMP/ip"
    if [[ $cert_mode == provided ]]; then args+=(--form "ip_address=<\"$WP_TMP/ip\"")
    else args+=(--data-urlencode "ip_address@$WP_TMP/ip"); fi
  fi
  if [[ $cert_mode == provided ]]; then
    args+=(--form "certificate=@\"$WP_TMP/certificate\";filename=certificate.pem")
    [[ $secret_mode != provided ]] || args+=(--form "secret_token=<\"$WP_TMP/secret\"")
  elif [[ $secret_mode == provided ]]; then args+=(--data-urlencode "secret_token@$WP_TMP/secret"); fi
  wp_request "$SELF_BOT_URL" setWebhook "${args[@]}"
  WP_SET_ACCEPTED=true
  printf 'set_webhook_accepted=true; private_material=sent-not-readback-verified\n'
}

wp_observe() {
  local deadline=$((SECONDS + 10)) remaining sample first='' last='' readable=true observation=unverified code=0
  for sample in 1 2; do
    if (( sample > 1 )); then sleep 2; fi
    remaining=$((deadline - SECONDS))
    if (( remaining <= 0 )); then readable=null; observation=unknown; code=2; break; fi
    if ( WP_REQUEST_TIMEOUT=$remaining wp_request "$SELF_BOT_URL" getWebhookInfo ); then
      wp_jq '.result += {observed_at:now}' "$WP_TMP/response" > "$WP_TMP/sample$sample"
      last=$sample
      [[ -n $first ]] || first=$sample
      if [[ -n $WP_HOOK ]] && ! wp_jq -e --argjson p "$WP_PROFILE" '
        (.result|has("max_connections")) and
        (if $p.profile.ip_mode=="pinned" then (.result|has("ip_address")) else true end)' "$WP_TMP/response" >/dev/null; then
        [[ $readable == false ]] || readable=null
        observation=unknown; (( code == 1 )) || code=2
        continue
      fi
      if ! wp_jq -e --argjson p "$WP_PROFILE" '
        .result as $r | $p.profile as $p |
        $r.url==$p.url and (if $p.url=="" then true else
          $r.max_connections==$p.max_connections and ($r.allowed_updates//[]|unique)==($p.allowed_updates|unique) and
          $r.has_custom_certificate==($p.certificate_mode=="provided") and
          (if $p.ip_mode=="pinned" then $r.ip_address==$p.ip_address else true end) end)' "$WP_TMP/response" >/dev/null; then
        readable=false; code=1
      fi
    else
      [[ $readable == false ]] || readable=null
      observation=unknown; (( code == 1 )) || code=2
    fi
  done
  if [[ -n $first && -n $last ]]; then
    wp_jq -n --slurpfile s "$WP_TMP/source" --slurpfile a "$WP_TMP/sample$first" --slurpfile b "$WP_TMP/sample$last" \
      --argjson readable "$readable" --argjson accepted "$WP_SET_ACCEPTED" --argjson set_time "$WP_SET_TIME" --arg observation "$observation" '
      $s[0].result as $s | $a[0].result as $a | $b[0].result as $b |
      {profile_input_complete:true,set_webhook_accepted:$accepted,observable_profile_matches:$readable,
       delivery_confirmed:false,private_material:"not-readback-verifiable",delivery_observation:$observation,
       samples:[{time:$a.observed_at,pending:$a.pending_update_count},{time:$b.observed_at,pending:$b.pending_update_count}],
       queue:(if $b.pending_update_count>$a.pending_update_count then "growing" elif $b.pending_update_count<$a.pending_update_count then "falling" else "stable" end),
       historical_error:(($s.last_error_date//0)>0 or ($s.last_synchronization_error_date//0)>0),
       new_error:(([$a.last_error_date//0,$b.last_error_date//0]|max)>=$set_time),
       new_synchronization_error:(([$a.last_synchronization_error_date//0,$b.last_synchronization_error_date//0]|max)>($s.last_synchronization_error_date//0))} |
       if .delivery_observation!="unknown" and (.new_error or .new_synchronization_error or .queue=="growing") then .delivery_observation="degraded" else . end' > "$WP_TMP/result"
    # No raw last_error_message, URLs, secret or PEM in this allowlisted result.
    wp_jq -c '.' "$WP_TMP/result"
    if wp_jq -e '.new_error or .new_synchronization_error' "$WP_TMP/result" >/dev/null; then code=1; fi
  else
    printf 'observable_profile_matches=unknown; delivery_observation=unknown; delivery_confirmed=false\n'
  fi
  return "$code"
}

wp_configuration() { wp_jq -c '.result|{url,allowed_updates:(.allowed_updates//[]|unique),max_connections,has_custom_certificate,ip_address}' "$1"; }
wp_main() {
  set +x
  set +v
  set -euo pipefail
  wp_load "$@"
  if [[ $MIGRATION_MODE == target-stage ]]; then
    [[ -n ${WEBHOOK_URL-} && -n ${WEBHOOK_ALLOWED_UPDATES+x} && -n ${WEBHOOK_MAX_CONNECTIONS+x} && -n ${WEBHOOK_CERTIFICATE_MODE-} ]] || wp_fail 'Target-stage requires explicit saved URL, updates, connections and certificate mode'
  fi
  local source=$OFFICIAL_BOT_URL status answer source_id target_id
  [[ $MIGRATION_MODE == official-to-self ]] || source=$SELF_BOT_URL
  if [[ $MIGRATION_MODE == official-to-self ]]; then
    local probe_deadline=$MIGRATION_REQUEST_DEADLINE probe_connect=$MIGRATION_CONNECT_TIMEOUT
    (( probe_deadline <= 10 )) || probe_deadline=10
    (( probe_connect <= probe_deadline )) || probe_connect=$probe_deadline
    status=$(curl -q -sS --connect-timeout "$probe_connect" --max-time "$probe_deadline" --output "$WP_TMP/probe" --write-out '%{http_code}' "$SELF_BOT_URL/" 2>/dev/null) || wp_fail 'phase=preflight outcome=UNKNOWN reason=transport_error: Token-free probe failed'
    [[ $status == 404 ]] && wp_jq -e '.ok==false and .error_code==404 and .description=="Not Found"' "$WP_TMP/probe" >/dev/null || wp_fail 'phase=preflight outcome=UNKNOWN reason=unexpected_response: Unexpected token-free probe'
  fi
  printf 'Probe does not authenticate the host. Stop old clients; permit token requests?\n'
  read -r answer || return 0
  case $answer in y|Y|yes|YES) ;; *) return 0 ;; esac
  wp_request "$source" getMe
  source_id=$(wp_jq -r '.result.id' "$WP_TMP/response")
  wp_request "$source" getWebhookInfo
  wp_jq '. + {snapshot_at:now}' "$WP_TMP/response" > "$WP_TMP/source"
  wp_preflight "$WP_TMP/source"
  # T1 fail closed until the full transport exists; never detach using URL-only transport.
  [[ -z $WP_HOOK ]] || declare -F wp_transport_ready >/dev/null || wp_fail 'Full profile transport unavailable; source unchanged'
  wp_request "$source" getWebhookInfo
  [[ $(wp_configuration "$WP_TMP/source") == "$(wp_configuration "$WP_TMP/response")" ]] || wp_fail 'Source profile changed; restart preflight'
  if [[ $MIGRATION_MODE == official-to-self ]]; then
    wp_request "$source" deleteWebhook -X POST --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
    wp_request "$source" logOut -X POST
    wp_request "$SELF_BOT_URL" getMe
    target_id=$(wp_jq -r '.result.id' "$WP_TMP/response")
    [[ $target_id == "$source_id" ]] || wp_fail 'Bot identity mismatch; source login forbidden'
  fi
  WP_SET_ACCEPTED=null
  WP_SET_TIME=$(date +%s)
  if [[ -n $WP_HOOK ]]; then wp_set
  elif [[ $MIGRATION_MODE == hook-only ]]; then wp_request "$SELF_BOT_URL" deleteWebhook -X POST --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"; fi
  wp_observe
}
