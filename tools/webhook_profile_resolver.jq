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