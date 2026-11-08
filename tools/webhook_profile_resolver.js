// Canonical resolver. Embedded inline; no browser runtime import.
function resolveWebhookProfile(input) {
  const s=input.source || {},d=input.desired || {},own=(o,k)=>Object.hasOwn(o,k);
  const valid=!!s && typeof s==='object' && typeof s.url==='string';
  const r={version:1,profile:{},provenance:{},missing:[],invalid:[]},p=r.profile;
  for(const k of ['url','allowed_updates','max_connections']) {
    if(own(d,k)) {p[k]=d[k];r.provenance[k]='explicit';}
    else if(valid && own(s,k)) {p[k]=s[k];r.provenance[k]='source';}
    else if(valid && k==='allowed_updates') {p[k]=[];r.provenance[k]='documented-default';}
    else r.missing.push(k);
  }
  p.secret_mode=d.secret?.mode ?? 'unknown'; p.ip_mode=d.ip?.mode ?? 'unknown';
  p.certificate_mode=d.certificate?.mode ?? (valid && s.has_custom_certificate===false?'none':'unknown');
  r.provenance.secret_mode='explicit';r.provenance.ip_mode='explicit';r.provenance.certificate_mode=d.certificate?.mode?'explicit':'source';
  if(p.secret_mode==='provided') {
    if(typeof d.secret?.value!=='string'||!/^[A-Za-z0-9_-]{1,256}$/.test(d.secret.value)||/[\r\n]/.test(d.secret.value)) r.invalid.push('secret_token');
  } else if(p.secret_mode==='none') {if((d.secret?.value ?? '')!=='') r.invalid.push('secret_token');}
  else if(p.secret_mode==='unknown') r.missing.push('secret_mode'); else r.invalid.push('secret_mode');
  const ipv4=v=>typeof v==='string' && /^(0|[1-9][0-9]{0,2})(\.(0|[1-9][0-9]{0,2})){3}$/.test(v) && v.split('.').every(n=>Number(n)<=255);
  if(p.ip_mode==='fixed'||p.ip_mode==='pinned') {p.ip_mode='pinned';p.ip_address=d.ip?.address;if(!ipv4(p.ip_address))r.invalid.push('ip_address');}
  else if(p.ip_mode==='dns') {if((d.ip?.address ?? '')!=='')r.invalid.push('ip_address');}
  else if(p.ip_mode==='unknown')r.missing.push('ip_mode');else r.invalid.push('ip_mode');
  if(p.certificate_mode==='provided') {
    const v=d.certificate?.value;
    if(typeof v!=='string'||v.length>1048576||!/-----BEGIN CERTIFICATE-----\r?\n(?:[A-Za-z0-9+/]{1,64}={0,2}\r?\n)+-----END CERTIFICATE-----/.test(v)||v.includes('PRIVATE KEY'))r.invalid.push('certificate');
  }else if(p.certificate_mode==='none') {if((d.certificate?.value ?? '')!=='')r.invalid.push('certificate');}
  else if(p.certificate_mode==='unknown')r.missing.push('certificate_mode');else r.invalid.push('certificate_mode');
  if(own(p,'url') && typeof p.url!=='string')r.invalid.push('url');
  if(own(p,'allowed_updates') && (!Array.isArray(p.allowed_updates)||!p.allowed_updates.every(x=>typeof x==='string')))r.invalid.push('allowed_updates');
  if(own(p,'max_connections') && (!Number.isInteger(p.max_connections)||p.max_connections<1||p.max_connections>(input.target_local===true?100000:100)))r.invalid.push('max_connections');
  for(const k of Object.keys(r.provenance))if(r.provenance[k]==='explicit'&&input.provenance?.[k])r.provenance[k]=input.provenance[k];
  r.complete=!r.missing.length&&!r.invalid.length;return r;
}
