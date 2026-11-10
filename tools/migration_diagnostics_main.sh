# Canonical diagnostics engine + schema-v1 request journal for the shipped helper.
# Composed after tools/webhook_profile_runtime.sh by embed_webhook_profile.cjs.
script_dir=$WP_SCRIPT_DIR

# Diagnostics are private evidence for a future #2 adapter, not a resume engine.
API_TMP= CURL_PID= REQUEST_ACTIVE=false LOCK_OWNED=false
RUN_COMPLETED=false PARTIAL_MIGRATION=false LAST_CONFIRMED= RUN_OUTCOME=in_flight
REQUEST_NUMBER=0 RAW_RETAINED=false BOT_ID= SOURCE_BOT_ID=
CURRENT_WEBHOOK= TARGET_WEBHOOK= CURRENT_OBSERVED_WEBHOOK= SET_ARGS=()
STORAGE_ROOT="$script_dir/logs/migration"
private_directory() {
  local directory="$1" permissions
  if [[ -e "$directory" || -L "$directory" ]]; then
    if [[ -L "$directory" || ! -d "$directory" || ! -O "$directory" ||
          ! -r "$directory" || ! -w "$directory" || ! -x "$directory" ]]; then
      echo 'Refusing unsafe or symlinked diagnostic directory' >&2; return 1
    fi
    permissions="$(stat -c '%a' -- "$directory")" || return 1
    if [[ "$permissions" != 700 ]]; then
      echo 'Diagnostic directory must be private (0700)' >&2; return 1
    fi
  elif ! mkdir -m 700 -- "$directory"; then
    echo 'Cannot create private diagnostic directory' >&2; return 1
  fi
}
private_record() {
  local permissions
  [[ ! -L "$1" && -f "$1" && -O "$1" && -r "$1" ]] || return 1
  permissions="$(stat -c '%a' -- "$1")" || return 1
  [[ "$permissions" == 600 ]]
}
cleanup() {
  local original_exit=$?
  trap - EXIT
  if [[ "$REQUEST_ACTIVE" == true && "${API_EFFECT_POSSIBLE:-false}" == true ]]; then
    RUN_OUTCOME=UNKNOWN
    original_exit=3
  fi
  if [[ -n "$CURL_PID" ]]; then
    kill -TERM "$CURL_PID" 2>/dev/null || :
    if wait "$CURL_PID"; then :; else :; fi
  fi
  if [[ -n "$API_TMP" ]]; then
    # Failed sanitization intentionally retains owner-only raw capture.
    if ! rm -f -- "$API_TMP/.raw-secrets" "$API_TMP/.preview.raw" 2>/dev/null; then
      RAW_RETAINED=true
      echo 'Warning: private redaction data retained after cleanup failure' >&2
    fi
    if [[ -f "$API_TMP/summary.json" ]]; then
      if [[ "$RUN_OUTCOME" == in_flight ]]; then RUN_OUTCOME=FAILED; fi
      if ! summary final >/dev/null 2>&1; then
        echo 'Cannot finalize private summary; reconciliation required' >&2
        if [[ "$PARTIAL_MIGRATION" == true || "$REQUEST_ACTIVE" == true ]]; then
          original_exit=3
        elif (( original_exit == 0 )); then original_exit=1; fi
      fi
    fi
  fi
  if [[ -n "${WP_TMP-}" ]]; then rm -rf -- "$WP_TMP" || :; fi
  if [[ "$LOCK_OWNED" == true ]]; then
    rmdir -- "$STORAGE_ROOT/.lock" 2>/dev/null || :
  fi
  exit "$original_exit"
}
check_previous_runs() {
  local previous request operation attempt effect mutating had_mutation complete
  for previous in "$STORAGE_ROOT"/run.*; do
    [[ -e "$previous" || -L "$previous" ]] || continue
    private_directory "$previous" || return 3
    operation="${previous##*/}"
    complete=false had_mutation=false
    if [[ -e "$previous/summary.json" || -L "$previous/summary.json" ]]; then
      private_record "$previous/summary.json" || return 3
      jq -e --arg operation "$operation" '
        type == "object" and .schema_version == 1 and .operation_id == $operation and
        (.completed | type == "boolean") and (.attempts | type == "array") and
        .partial_migration == false and
        (.continuation_requires_reconciliation == false or
          (.continuation_requires_reconciliation == true and
           all(.attempts[]; .effect_possible == false))) and
        all(.attempts[]; (.effect_possible | type == "boolean") and
          ((.effect_possible | not) or (.outcome != "UNKNOWN" and .outcome != "in_flight")))
      ' "$previous/summary.json" >/dev/null 2>&1 || return 3
      complete="$(jq -r '.completed' "$previous/summary.json")" || return 3
    fi
    for request in "$previous"/request-*; do
      [[ -e "$request" || -L "$request" ]] || continue
      private_directory "$request" || return 3
      attempt="${request##*/}"
      if ! private_record "$request/intent.json" ||
         ! jq -e --arg operation "$operation" --arg attempt "$attempt" '
           .schema_version == 1 and .operation_id == $operation and .attempt_id == $attempt and
           .outcome == "in_flight" and (.effect_possible | type == "boolean") and
           (.mutating | type == "boolean")
         ' "$request/intent.json" >/dev/null 2>&1; then return 3; fi
      effect="$(jq -r '.effect_possible' "$request/intent.json")" || return 3
      mutating="$(jq -r '.mutating' "$request/intent.json")" || return 3
      if [[ ! -e "$request/receipt.json" && ! -L "$request/receipt.json" ]]; then
        [[ "$effect" == false ]] || return 3
        continue
      fi
      private_record "$request/receipt.json" || return 3
      jq -e --arg operation "$operation" --arg attempt "$attempt" \
        --argjson effect "$effect" --argjson mutating "$mutating" '
        type == "object" and .schema_version == 1 and .operation_id == $operation and
        .attempt_id == $attempt and .effect_possible == $effect and .mutating == $mutating and
        (.outcome == "CONFIRMED_SUCCESS" or .outcome == "CONFIRMED_REJECTION" or
         (.outcome == "UNKNOWN" and .effect_possible == false))
      ' "$request/receipt.json" >/dev/null 2>&1 || return 3
      if [[ "$mutating" == true ]] && jq -e '.outcome == "CONFIRMED_SUCCESS"' \
          "$request/receipt.json" >/dev/null 2>&1; then had_mutation=true; fi
    done
    [[ "$had_mutation" == false || "$complete" == true ]] || return 3
  done
}
summary() {
  local mode="$1" outcome="${2:-in_flight}"
  jq --arg mode "$mode" --arg id "${REQUEST_ID:-}" --arg step "${STEP_ID:-}" \
    --arg outcome "$outcome" --arg last "$LAST_CONFIRMED" --arg run_outcome "$RUN_OUTCOME" \
    --argjson effect "${API_EFFECT_POSSIBLE:-false}" --argjson mutating "${API_MUTATING:-false}" \
    --argjson partial "$PARTIAL_MIGRATION" --argjson complete "$RUN_COMPLETED" --argjson raw "$RAW_RETAINED" '
      .last_confirmed_step = (if $last == "" then null else $last end) |
      .completed = $complete | .run_outcome = $run_outcome |
      .raw_capture_may_remain = $raw |
      .partial_migration = ($partial and ($complete | not)) |
      if $mode == "intent" then
        .attempts += [{attempt_id:$id,step_id:$step,effect_possible:$effect,mutating:$mutating,
                      intent:($id+"/intent.json"),receipt:null,outcome:"in_flight"}]
      elif $mode == "receipt" then
        .attempts |= map(if .attempt_id == $id then
          .receipt = ($id+"/receipt.json") | .outcome = $outcome else . end)
      else . end |
      .confirmed_effects = [.attempts[] | select(.mutating and .outcome == "CONFIRMED_SUCCESS") | .step_id] |
      .unfinished_attempt = ([.attempts[] | select(.receipt == null) | .attempt_id] | last // null) |
      .continuation_requires_reconciliation = (($complete | not) and
        ($partial or any(.attempts[]; .outcome == "in_flight" or
                       (.effect_possible and .outcome == "UNKNOWN"))))
    ' "$API_TMP/summary.json" > "$API_TMP/.summary.tmp" &&
    mv -- "$API_TMP/.summary.tmp" "$API_TMP/summary.json"
}
write_secrets() {
  local name
  {
    printf '%s\0' "$BOT_TOKEN" "${WEBHOOK_URL:-}" "${WP_HOOK:-}" \
      "${CURRENT_WEBHOOK:-}" "${TARGET_WEBHOOK:-}" "${CURRENT_OBSERVED_WEBHOOK:-}" || return 1
    for name in secret certificate; do
      if [[ -s "$WP_TMP/$name" ]]; then cat -- "$WP_TMP/$name" && printf '\0' || return 1; fi
    done
    while IFS= read -r name; do
      case "$name" in
        *TOKEN*|*SECRET*|*PASSWORD*|*API_HASH*|*token*|*secret*|*password*|*api_hash*)
          if [[ -v "$name" ]]; then printf '%s\0' "${!name}" || return 1; fi;;
      esac
    done < <(compgen -v)
  } > "$API_TMP/.raw-secrets"
}
redact_file() {
  local input="$1" output="$2"
  jq -Rs --rawfile secrets "$API_TMP/.raw-secrets" --argjson authority_preview "${3:-false}" '
    def replace($needle):
      if ($needle | length) == 0 then . else split($needle) | join("[REDACTED]") end;
    def hexnum:
      ascii_downcase | explode | reduce .[] as $c (0; . * 16 +
        (if $c <= 57 then $c - 48 else $c - 87 end));
    def decode_text:
      gsub("\\\\u(?<hex>[0-9a-fA-F]{4})";
        (.hex | hexnum | if . >= 55296 and . <= 57343 then 65533 else . end | [.] | implode)) |
      gsub("\\\\/"; "/") |
      gsub("%(?<hex>[0-7][0-9a-fA-F])"; (.hex | hexnum | [.] | implode));
    ($secrets | split(" ") | map(select(length > 0))) as $values |
    def clean_text:
      decode_text |
      gsub("[\\u0000-\\u0009\\u000b-\\u001f\\u007f]"; "") |
      reduce $values[] as $secret (. ; replace($secret) | replace($secret|@uri) |
        replace($secret|@json|.[1:-1])) |
      (if $authority_preview then . else gsub("(?i)https?://[^\\s\"<>]+"; "[REDACTED_URL]") end) |
      gsub("(?i)(token|secret|password|api_hash)([\"\\s:=]+)[^\\s,}\"&]+"; "[REDACTED_SECRET]");
    def clean:
      if type == "string" then clean_text
      elif type == "array" then map(clean)
      elif type == "object" then with_entries(
        (if (.key | test("(?i)token|secret|password|api_hash")) then .value = "[REDACTED]"
         else .value |= clean end) | .key |= clean_text)
      else . end;
    . as $text | (try {value:fromjson} catch null) as $parsed |
    if $parsed != null then ($parsed.value | clean | tojson)
    else ($text | clean_text | @json | .[1:-1]) end
  ' "$input" | jq -rj . > "$output"
}
endpoint_preview() {
  local url="$1" authority scheme
  scheme="${url%%://*}"
  authority="${url#*://}"
  authority="${authority%%[/?#]*}"
  authority="${authority##*@}"
  printf '%s' "${scheme}://${authority}" > "$API_TMP/.preview.raw" &&
    redact_file "$API_TMP/.preview.raw" "$API_TMP/.preview.txt" true &&
    jq -Rs -r '.[0:2048]|@json' "$API_TMP/.preview.txt"
}
write_record() {
  local phase="$1" outcome="$2" reason="$3"
  jq -n --arg phase "$phase" --arg operation "$RUN_ID" --arg step "$STEP_ID" \
    --arg attempt "$REQUEST_ID" --arg method "$API_METHOD" --arg role "$ENDPOINT_ROLE" \
    --arg verb "$HTTP_METHOD" --arg started "$STARTED_AT" --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson elapsed "$(( $(date +%s) - STARTED_SECONDS ))" --arg bot "${BOT_ID:-}" \
    --arg code "${API_HTTP_CODE:-}" --argjson curl_exit "${API_CURL_EXIT:-0}" \
    --argjson mutating "$API_MUTATING" --argjson effect "$API_EFFECT_POSSIBLE" \
    --arg outcome "$outcome" --arg reason "$reason" --arg parse "${API_JSON_STATUS:-not_received}" \
    --arg schema "${API_SCHEMA_STATUS:-not_received}" --arg last "$LAST_CONFIRMED" \
    --argjson connect "$EFFECTIVE_CONNECT" --argjson deadline "$EFFECTIVE_DEADLINE" \
    --argjson drop "$DROP_PENDING_UPDATES" --argjson observations "${API_OBSERVATIONS:-[]}" \
    --rawfile safe_body "$REQUEST_DIR/body.txt" '
      def integer: type == "number" and . >= 0 and . <= 9007199254740991 and floor == .;
      ($safe_body | (try fromjson catch null) | if type == "object" then . else {} end) as $body |
      (try $body.parameters.retry_after catch null) as $retry |
      {schema_version:1,operation_id:$operation,step_id:$step,attempt_id:$attempt,
       method:$method,http_method:$verb,endpoint_role:$role,endpoint_identifier:($role+":"+$method),
       bot_id:(if $bot == "" then null else ($bot|tonumber) end),mutating:$mutating,
       effect_possible:$effect,session_effect_possible:$effect,drop_pending_updates:$drop,
       started_at:$started,finished_at:(if $phase == "intent" then null else $finished end),
       connect_timeout:$connect,request_deadline:$deadline,
       http_status:(if ($code|test("^[1-5][0-9][0-9]$")) then ($code|tonumber) else null end),
       curl_exit_code:(if $phase == "intent" then null else $curl_exit end),
       transport_status:(if $phase == "intent" then "not_sent" elif $curl_exit == 0 then "complete" else "error" end),
       api_ok:(if ($body.ok|type) == "boolean" then $body.ok else null end),
       api_error_code:(if ($body.error_code | type == "number" and
                           . >= -9007199254740991 and . <= 9007199254740991 and floor == .)
                       then $body.error_code else null end),
       description:(if ($body.description|type) == "string" then $body.description else null end),
       retry_after:(if ($retry|integer) then $retry else null end),
       retry_after_status:(if ($body|has("parameters")|not) then "absent"
         elif ($body.parameters|type) != "object" then "invalid"
         elif ($body.parameters|has("retry_after")|not) then "absent"
         elif ($retry|integer) then "valid" else "invalid" end),
       response_complete:($phase != "intent" and $curl_exit == 0),parse_status:$parse,schema_status:$schema,
       duration:(if $phase == "intent" then null else $elapsed end),
       outcome:$outcome,reason:$reason,observations:$observations,
       last_confirmed_step:(if $last == "" then null else $last end),
       body:(if $phase == "intent" then null else ($attempt+"/body.txt") end),
       transport_stderr:(if $phase == "intent" then null else ($attempt+"/transport-error.txt") end),
       http_status_artifact:(if $phase == "intent" then null else ($attempt+"/http-status.txt") end),
       body_present:($safe_body|length > 0),body_may_be_partial:($curl_exit != 0),
       sanitization_status:"complete",raw_retained:false,
       artifact_encoding:"UTF-8; invalid bytes replaced; JSON, controls and escapes normalized"}
    ' > "$REQUEST_DIR/.$phase.tmp" &&
    mv -- "$REQUEST_DIR/.$phase.tmp" "$REQUEST_DIR/$phase.json"
}
finish_request() {
  local interruption="${1:-}" valid_result=false valid_rejection=false outcome=UNKNOWN reason=invalid_response
  API_HTTP_CODE= API_JSON_STATUS=invalid_json API_SCHEMA_STATUS=invalid API_OBSERVATIONS='[]'
  API_BOT_ID= API_WEBHOOK_URL=
  IFS= read -r API_HTTP_CODE < "$REQUEST_DIR/.raw-status" || :
  [[ "$API_HTTP_CODE" =~ ^[1-5][0-9][0-9]$ ]] || API_HTTP_CODE=
  if jq -e -s 'length == 1' "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then
    API_JSON_STATUS=valid
    if jq -e 'type == "object" and (.ok|type == "boolean")' "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then
      if [[ "$API_METHOD" == probe ]]; then
        if jq -e '.ok == false and .error_code == 404 and .description == "Not Found"' \
           "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then valid_result=true; fi
      elif jq -e '.ok == true and (has("error_code")|not) and (has("description")|not) and (has("parameters")|not)' \
           "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then
        case "$API_METHOD" in
          getMe) if jq -e '.result | type == "object" and
            (.id | type == "number" and . > 0 and . <= 9007199254740991 and floor == .)' \
            "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then valid_result=true; fi;;
          getWebhookInfo) if jq -e '.result | type == "object" and (.url|type == "string")' \
            "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then valid_result=true; fi;;
          *) if jq -e '.result == true' "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then valid_result=true; fi;;
        esac
      elif jq -e '
        def integer: type == "number" and . >= 0 and . <= 9007199254740991 and floor == .;
        .ok == false and (has("result")|not) and (.description|type == "string") and
        (.error_code|type == "number" and . >= -9007199254740991 and . <= 9007199254740991 and floor == .) and
        ((has("parameters")|not) or (.parameters|type == "object" and
          ((has("retry_after")|not) or (.retry_after|integer))))
        ' "$REQUEST_DIR/.raw-body" >/dev/null 2>&1; then valid_rejection=true; fi
    fi
  fi
  if [[ "$valid_result" == true || "$valid_rejection" == true ]]; then API_SCHEMA_STATUS=valid; fi
  if [[ "$API_CURL_EXIT" != 0 || -n "$interruption" ]]; then
    reason=transport_unknown
    [[ -n "$interruption" ]] && reason=interrupted
  elif [[ "$API_METHOD" == probe && "$API_HTTP_CODE" == 404 && "$valid_result" == true ]] ||
       [[ "$API_METHOD" != probe && "$API_HTTP_CODE" =~ ^2[0-9][0-9]$ && "$valid_result" == true ]]; then
    outcome=CONFIRMED_SUCCESS; reason=api_confirmed
  elif [[ "$API_HTTP_CODE" =~ ^[24][0-9][0-9]$ && "$valid_rejection" == true ]]; then
    outcome=CONFIRMED_REJECTION; reason=api_rejected
    [[ "$API_HTTP_CODE" == 429 ]] && reason=rate_limited
  fi
  API_OBSERVATIONS="$(jq -n --argjson rc "$API_CURL_EXIT" --arg code "$API_HTTP_CODE" \
    --arg parse "$API_JSON_STATUS" --arg schema "$API_SCHEMA_STATUS" --arg method "$API_METHOD" \
    --rawfile text "$REQUEST_DIR/.raw-body" '
      (try ($text|fromjson) catch null) as $body |
      [if $rc != 0 then "transport_error" else empty end,
       if ($code|test("^[345]")) and ($method != "probe" or $code != "404") then "http_error" else empty end,
       if $parse != "valid" then "invalid_json" else empty end,
       if $schema != "valid" then "invalid_schema" else empty end,
       if (if ($body|type) == "object" then $body.ok == false else false end)
          and $method != "probe" then "api_error" else empty end]'
    2>/dev/null)" || API_OBSERVATIONS='["invalid_json"]'
  if [[ "$outcome" == CONFIRMED_SUCCESS ]]; then
    if [[ "$API_METHOD" == getMe ]]; then
      API_BOT_ID="$(jq -r '.result.id' "$REQUEST_DIR/.raw-body")" || return 3
      BOT_ID="$API_BOT_ID"
    elif [[ "$API_METHOD" == getWebhookInfo ]]; then
      API_WEBHOOK_URL="$(jq -r '.result.url' "$REQUEST_DIR/.raw-body")" || return 3
      CURRENT_OBSERVED_WEBHOOK="$API_WEBHOOK_URL"
      jq '.' "$REQUEST_DIR/.raw-body" > "$WP_TMP/info-$STEP_ID.json" || return 3
    fi
  fi
  # Add the observed webhook before sanitization, including inherited secrets.
  if ! write_secrets || ! redact_file "$REQUEST_DIR/.raw-body" "$REQUEST_DIR/body.txt" ||
     ! redact_file "$REQUEST_DIR/.raw-stderr" "$REQUEST_DIR/transport-error.txt" ||
     ! printf '%s' "${API_HTTP_CODE:-null}" > "$REQUEST_DIR/http-status.txt" ||
     ! write_record receipt "$outcome" "$reason"; then
    RUN_OUTCOME=UNKNOWN
    echo 'Cannot persist sanitized receipt; private raw retained; reconciliation required' >&2
    [[ "$API_EFFECT_POSSIBLE" == true ]] && return 3
    return 1
  fi
  REQUEST_ACTIVE=false
  if ! rm -f -- "$REQUEST_DIR"/.raw-*; then
    echo 'Private raw retained after cleanup failure; reconciliation required' >&2
    jq '.raw_retained = true | .cleanup_error = true' "$REQUEST_DIR/receipt.json" \
      > "$REQUEST_DIR/.receipt.tmp" && mv -- "$REQUEST_DIR/.receipt.tmp" "$REQUEST_DIR/receipt.json" || :
    RUN_OUTCOME=UNKNOWN
    return 3
  fi
  RAW_RETAINED=false
  if [[ "$outcome" == CONFIRMED_SUCCESS ]]; then
    LAST_CONFIRMED="$STEP_ID"
    [[ "$API_MUTATING" == true ]] && PARTIAL_MIGRATION=true
  fi
  RUN_OUTCOME="$outcome"
  if ! summary receipt "$outcome"; then
    echo 'Cannot persist summary; reconciliation required' >&2
    [[ "$API_EFFECT_POSSIBLE" == true ]] && return 3
    return 1
  fi
  if [[ "$outcome" == CONFIRMED_SUCCESS ]]; then return 0; fi
  echo "Error: phase=$STEP_ID method=$API_METHOD role=$ENDPOINT_ROLE: HTTP ${API_HTTP_CODE:-none}, curl $API_CURL_EXIT, outcome $outcome ($reason)" >&2
  jq -r '"Telegram: description=\((.description // "(absent)")[:2048]|@json) error_code=\(.api_error_code // "(absent/invalid)") retry_after=\(.retry_after // "(absent/invalid)")"' \
    "$REQUEST_DIR/receipt.json" >&2 || return 3
  echo "Inspect private dossier beside script: logs/migration/$RUN_ID" >&2
  if [[ "$API_EFFECT_POSSIBLE" == true && "$outcome" == UNKNOWN ]]; then
    echo 'Unknown possible effect; do not retry blindly; reconciliation required' >&2; return 3
  fi
  return 1
}
capture_request() {
  local directory="$1" connect="$2" deadline="$3"
  shift 3
  curl -q --retry 0 -sS --connect-timeout "$connect" --max-time "$deadline" \
    --globoff --proto '=http,https' \
    --output "$directory/.raw-body" --write-out '%{http_code}' "$@" \
    > "$directory/.raw-status" 2> "$directory/.raw-stderr" &
  CURL_PID=$!
  if wait "$CURL_PID"; then API_CURL_EXIT=0; else API_CURL_EXIT=$?; fi
  CURL_PID=
}
api_request() {
  ENDPOINT_ROLE="$1"; STEP_ID="$2"; API_METHOD="$3"; HTTP_METHOD="$4"
  API_MUTATING="$5"; shift 5
  API_EFFECT_POSSIBLE=true EFFECTIVE_CONNECT="$MIGRATION_CONNECT_TIMEOUT" EFFECTIVE_DEADLINE="$MIGRATION_REQUEST_DEADLINE"
  local base="$SELF_BOT_URL" url
  [[ "$ENDPOINT_ROLE" == source ]] && base="$OFFICIAL_BOT_URL"
  url="$base/bot$BOT_TOKEN/$API_METHOD"
  if [[ "$API_METHOD" == probe ]]; then
    API_EFFECT_POSSIBLE=false EFFECTIVE_CONNECT="$PROBE_CONNECT" EFFECTIVE_DEADLINE="$PROBE_DEADLINE"
    url="$base/"
  fi
  REQUEST_NUMBER=$((REQUEST_NUMBER + 1))
  REQUEST_DIR="$(mktemp -d "$API_TMP/request-$REQUEST_NUMBER.XXXXXXXX")" || return 1
  REQUEST_ID="${REQUEST_DIR##*/}"
  STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" || return 1
  STARTED_SECONDS="$(date +%s)" || return 1
  API_CURL_EXIT=0 API_HTTP_CODE= API_JSON_STATUS=not_received API_SCHEMA_STATUS=not_received API_OBSERVATIONS='[]'
  RAW_RETAINED=true
  if ! printf '' > "$REQUEST_DIR/body.txt" || ! printf '' > "$REQUEST_DIR/.raw-body" ||
     ! printf '' > "$REQUEST_DIR/.raw-stderr" || ! printf '' > "$REQUEST_DIR/.raw-status" ||
     ! write_record intent in_flight not_sent || ! summary intent; then
    echo 'Cannot record intent; NOT_SENT; reconciliation required' >&2; return 1
  fi
  REQUEST_ACTIVE=true
  # The endpoint URL carries the token only inside the private curl config file.
  if ! printf '%s' "$url" | jq -Rsr '"url = " + tojson' > "$WP_TMP/request.conf"; then
    echo 'Cannot prepare private request; NOT_SENT' >&2; return 1
  fi
  capture_request "$REQUEST_DIR" "$EFFECTIVE_CONNECT" "$EFFECTIVE_DEADLINE" -X "$HTTP_METHOD" --config "$WP_TMP/request.conf" "$@"
  finish_request
}
interrupted() {
  trap '' INT TERM
  if [[ -n "$CURL_PID" ]]; then
    kill -TERM "$CURL_PID" 2>/dev/null || :
    if wait "$CURL_PID"; then API_CURL_EXIT=0; else API_CURL_EXIT=$?; fi
    CURL_PID=
  fi
  if [[ "$REQUEST_ACTIVE" == true ]]; then
    API_CURL_EXIT=143
    if finish_request interrupted; then :; else :; fi
    [[ "$API_EFFECT_POSSIBLE" == true ]] && exit 3
  fi
  exit 1
}
wp_set_args() {
  local key cert_mode secret_mode ip_mode
  SET_ARGS=()
  cert_mode=$(wp_jq -r '.profile.certificate_mode' <<< "$WP_PROFILE")
  secret_mode=$(wp_jq -r '.profile.secret_mode' <<< "$WP_PROFILE")
  ip_mode=$(wp_jq -r '.profile.ip_mode' <<< "$WP_PROFILE")
  for key in url allowed_updates max_connections; do
    wp_jq -rj --arg key "$key" '.profile[$key]|if type=="array" then tojson else tostring end' <<< "$WP_PROFILE" > "$WP_TMP/$key"
    if [[ $cert_mode == provided ]]; then SET_ARGS+=(--form "$key=<\"$WP_TMP/$key\"")
    else SET_ARGS+=(--data-urlencode "$key@$WP_TMP/$key"); fi
  done
  if [[ $cert_mode == provided ]]; then SET_ARGS+=(--form-string "drop_pending_updates=$DROP_PENDING_UPDATES")
  else SET_ARGS+=(--data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"); fi
  if [[ $ip_mode == pinned ]]; then
    wp_jq -rj '.profile.ip_address' <<< "$WP_PROFILE" > "$WP_TMP/ip"
    if [[ $cert_mode == provided ]]; then SET_ARGS+=(--form "ip_address=<\"$WP_TMP/ip\"")
    else SET_ARGS+=(--data-urlencode "ip_address@$WP_TMP/ip"); fi
  fi
  if [[ $cert_mode == provided ]]; then
    SET_ARGS+=(--form "certificate=@\"$WP_TMP/certificate\";filename=certificate.pem")
    [[ $secret_mode != provided ]] || SET_ARGS+=(--form "secret_token=<\"$WP_TMP/secret\"")
  elif [[ $secret_mode == provided ]]; then SET_ARGS+=(--data-urlencode "secret_token@$WP_TMP/secret"); fi
}
profile_verify() {
  local result
  result=$(jq -n --slurpfile s "$WP_TMP/info-source_webhook.json" \
    --slurpfile f "$WP_TMP/info-final_webhook.json" \
    --argjson p "$WP_PROFILE" --argjson set_time "${WP_SET_TIME:-0}" \
    --argjson accepted "${WP_SET_ACCEPTED:-null}" '
    $s[0].result as $s | $f[0].result as $r | $p.profile as $p |
    def uint: type == "number" and . >= 0 and floor == .;
    (($r|type == "object") and ($r.url|type == "string") and
      (($r|has("pending_update_count")|not) or ($r.pending_update_count|uint)) and
      (($r|has("has_custom_certificate")|not) or ($r.has_custom_certificate|type == "boolean")) and
      (($r|has("allowed_updates")|not) or ($r.allowed_updates|type == "array" and all(.[]; type == "string"))) and
      (($r|has("max_connections")|not) or ($r.max_connections|uint and . >= 1)) and
      (($r|has("ip_address")|not) or ($r.ip_address|type == "string")) and
      (($r|has("last_error_date")|not) or ($r.last_error_date|uint)) and
      (($r|has("last_synchronization_error_date")|not) or ($r.last_synchronization_error_date|uint)) and
      (($r|has("last_error_message")|not) or ($r.last_error_message|type == "string"))) as $valid |
    {profile_input_complete:true, set_webhook_accepted:$accepted,
     observable_profile_matches:($valid and $r.url == $p.url and
       (if $p.url == "" then true else
         (($r|has("max_connections")|not) or $r.max_connections == $p.max_connections) and
         (($r|has("allowed_updates")|not) or (($r.allowed_updates // [] | unique) == ($p.allowed_updates | unique))) and
         (($r|has("has_custom_certificate")|not) or $r.has_custom_certificate == ($p.certificate_mode == "provided")) and
         (if $p.ip_mode == "pinned" then (($r|has("ip_address")|not) or $r.ip_address == $p.ip_address) else true end) end)),
     delivery_confirmed:false, private_material:"not-readback-verifiable",
     new_error:(($r.last_error_date // 0) >= $set_time),
     new_synchronization_error:(($r.last_synchronization_error_date // 0) > ($s.last_synchronization_error_date // 0)),
     queue:(if ($r.pending_update_count // 0) > ($s.pending_update_count // 0) then "growing"
            elif ($r.pending_update_count // 0) < ($s.pending_update_count // 0) then "falling" else "stable" end),
     historical_error:(($s.last_error_date // 0) > 0 or ($s.last_synchronization_error_date // 0) > 0)} |
     .delivery_observation = (if .new_error or .new_synchronization_error or .queue == "growing" then "degraded"
       elif ($p.url != "" and (($r|has("max_connections")|not) or ($p.ip_mode == "pinned" and ($r|has("ip_address")|not)))) then "unknown"
       else "unverified" end)') || return 1
  printf '%s\n' "$(jq -c '.' <<< "$result")"
  jq -e '.observable_profile_matches == true and (.new_error|not) and
         (.new_synchronization_error|not) and .queue != "growing"' <<< "$result" >/dev/null
}
wp_migration_main() {
  set +x
  set +v
  set -euo pipefail
  wp_load "$@"
  local cmd
  for cmd in mktemp date stat mkdir rm mv chmod cat rmdir; do
    command -v "$cmd" >/dev/null 2>&1 || wp_fail "Missing prerequisite: $cmd"
  done
  if [[ $MIGRATION_MODE == target-stage ]]; then
    [[ -n ${WEBHOOK_URL-} && -n ${WEBHOOK_ALLOWED_UPDATES+x} && -n ${WEBHOOK_MAX_CONNECTIONS+x} && -n ${WEBHOOK_CERTIFICATE_MODE-} ]] || wp_fail 'Target-stage requires explicit saved URL, updates, connections and certificate mode'
  fi
  # Unset profile modes default to the no-private-material baseline, matching the
  # pre-profile helper contract; explicit values keep full fail-closed validation.
  WEBHOOK_SECRET_MODE=${WEBHOOK_SECRET_MODE-none}
  WEBHOOK_IP_MODE=${WEBHOOK_IP_MODE-dns}
  WEBHOOK_CERTIFICATE_MODE=${WEBHOOK_CERTIFICATE_MODE-none}
  PROBE_DEADLINE=$(( MIGRATION_REQUEST_DEADLINE < 10 ? MIGRATION_REQUEST_DEADLINE : 10 ))
  PROBE_CONNECT=$(( MIGRATION_CONNECT_TIMEOUT < PROBE_DEADLINE ? MIGRATION_CONNECT_TIMEOUT : PROBE_DEADLINE ))
  private_directory "$script_dir/logs" || exit 1
  private_directory "$STORAGE_ROOT" || exit 1
  if ! mkdir -m 700 -- "$STORAGE_ROOT/.lock" 2>/dev/null; then
    echo 'Diagnostic root is locked; reconciliation required before any HTTP' >&2; exit 3
  fi
  LOCK_OWNED=true
  trap cleanup EXIT
  if ! check_previous_runs; then
    echo 'Previous operation requires reconciliation; inspect private logs/migration' >&2; exit 3
  fi
  API_TMP="$(mktemp -d "$STORAGE_ROOT/run.$(date -u +%Y%m%dT%H%M%SZ).$$.XXXXXXXX")" || exit 1
  RUN_ID="${API_TMP##*/}"
  if ! jq -n --arg operation "$RUN_ID" '{schema_version:1,operation_id:$operation,
    last_confirmed_step:null,attempts:[],confirmed_effects:[],unfinished_attempt:null,
    partial_migration:false,completed:false,run_outcome:"in_flight",
    continuation_requires_reconciliation:false}' > "$API_TMP/.summary.tmp" ||
     ! mv -- "$API_TMP/.summary.tmp" "$API_TMP/summary.json"; then
    echo 'Cannot prepare run summary; NOT_SENT' >&2; exit 1
  fi
  trap interrupted INT TERM
  if ! write_secrets; then echo 'Cannot prepare redaction data; NOT_SENT' >&2; exit 1; fi
  echo "Diagnostics beside script: logs/migration/$RUN_ID"

  if [[ $MIGRATION_MODE == official-to-self ]]; then
    echo "== 0/7 Token-free target probe =="
    api_request target preflight probe GET false
    echo "Probe does not authenticate the host. Verify the endpoint independently."
  fi
  if [[ $MIGRATION_MODE == official-to-self ]]; then
    printf 'Source: '; endpoint_preview "$OFFICIAL_BOT_URL" || exit 1
  fi
  printf 'Target: '; endpoint_preview "$SELF_BOT_URL" || exit 1
  if [[ -n "${WEBHOOK_URL-}" ]]; then
    printf 'Webhook: '; endpoint_preview "$WEBHOOK_URL" || exit 1
  else
    echo 'Webhook: inherit source if present'
  fi
  echo "Drop updates: $DROP_PENDING_UPDATES"
  local c
  if ! read -r -p "Continue with token-bearing requests? [y/N]: " c; then
    RUN_OUTCOME=CANCELLED; exit 0
  fi
  case "$c" in y|Y|yes|YES) ;; *) RUN_OUTCOME=CANCELLED; exit 0 ;; esac

  local source_role=source
  [[ $MIGRATION_MODE == official-to-self ]] || source_role=target

  echo
  echo "== 1/7 Identity =="
  api_request "$source_role" official_identity getMe GET false
  SOURCE_BOT_ID="$BOT_ID"
  echo "Bot:"
  echo "ID: $BOT_ID"
  echo "Name: (hidden)"
  echo "User: (hidden)"

  echo
  echo "== 2/7 Webhook status =="
  api_request "$source_role" source_webhook getWebhookInfo GET false
  CURRENT_WEBHOOK="$API_WEBHOOK_URL"
  if [[ "$CURRENT_WEBHOOK" != "" ]]; then
    echo "Current webhook:"
    echo "(configured)"
  else
    echo "No webhook"
  fi

  wp_preflight "$WP_TMP/info-source_webhook.json"
  TARGET_WEBHOOK="$WP_HOOK"

  echo
  echo "Plan:"
  if [[ $MIGRATION_MODE == official-to-self ]]; then
    echo "Old API: source"
    echo "New API: target"
  else
    echo "API: target ($MIGRATION_MODE)"
  fi
  if [[ -n "$TARGET_WEBHOOK" ]]; then
    echo "Webhook: configured"
  else
    echo "Webhook: polling mode"
  fi
  echo "Drop updates: $DROP_PENDING_UPDATES"
  echo

  if [[ $MIGRATION_MODE == official-to-self ]]; then
    echo "== 3/7 deleteWebhook =="
    api_request source delete_webhook deleteWebhook POST true \
      --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
    echo "deleteWebhook confirmed"

    echo
    echo "== 4/7 logOut =="
    api_request source logout logOut POST true
    echo "logOut confirmed"

    echo
    echo "== 5/7 self getMe =="
    api_request target target_identity getMe GET false
    echo "getMe confirmed"
    [[ "$BOT_ID" == "$SOURCE_BOT_ID" ]] || {
      echo 'Error: Bot identity mismatch; source login forbidden' >&2
      RUN_OUTCOME=FAILED
      exit 1
    }
  fi

  WP_SET_ACCEPTED=null
  if [[ -n "$TARGET_WEBHOOK" ]]; then
    echo
    echo "== 6/7 setWebhook =="
    WP_SET_TIME=$(date +%s)
    wp_set_args
    api_request target set_webhook setWebhook POST true "${SET_ARGS[@]}"
    WP_SET_ACCEPTED=true
    echo "setWebhook confirmed"
    printf 'set_webhook_accepted=true; private_material=sent-not-readback-verified\n'
  elif [[ $MIGRATION_MODE == hook-only ]]; then
    echo
    echo "== 6/7 deleteWebhook =="
    WP_SET_TIME=$(date +%s)
    api_request target delete_webhook deleteWebhook POST true \
      --data-urlencode "drop_pending_updates=$DROP_PENDING_UPDATES"
    echo "deleteWebhook confirmed"
  else
    echo
    echo "== 6/7 polling mode =="
    WP_SET_TIME=$(date +%s)
  fi

  echo
  echo "== 7/7 check =="
  api_request target final_webhook getWebhookInfo GET false
  echo "getWebhookInfo confirmed"
  local FINAL_URL="$API_WEBHOOK_URL"

  if [[ -n "$TARGET_WEBHOOK" ]]; then
    if profile_verify; then
      echo
      RUN_COMPLETED=true
      RUN_OUTCOME=CONFIRMED_SUCCESS
      summary final || exit 3
      echo "DONE"
      echo "Webhook OK"
    else
      RUN_OUTCOME=FAILED
      echo "Webhook mismatch" >&2
      exit 1
    fi
  else
    if [[ "$FINAL_URL" == "" ]]; then
      echo
      RUN_COMPLETED=true
      RUN_OUTCOME=CONFIRMED_SUCCESS
      summary final || exit 3
      echo "DONE polling mode"
    else
      RUN_OUTCOME=FAILED
      echo "Webhook still exists" >&2
      exit 1
    fi
  fi
}
