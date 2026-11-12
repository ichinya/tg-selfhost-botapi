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
    try {
      const match=typeof v==='string'&&v.length<=1048576&&!v.includes('PRIVATE KEY')&&v.match(/-----BEGIN CERTIFICATE-----\r?\n((?:[A-Za-z0-9+/]{1,64}={0,2}\r?\n)+)-----END CERTIFICATE-----/);
      if(!match)throw Error();
      const bytes=atob(match[1].replace(/\r?\n/g,''));
      const tlv=(pos,tag,limit)=>{if(bytes.charCodeAt(pos++)!==tag||pos>=limit)throw Error();let n=bytes.charCodeAt(pos++);if(n&128){const count=n&127;if(!count||count>4||pos+count>limit||bytes.charCodeAt(pos)===0)throw Error();n=0;for(let i=0;i<count;i++)n=n*256+bytes.charCodeAt(pos++);if(n<128)throw Error();}if(pos+n>limit)throw Error();return [pos,pos+n];};
      const outer=tlv(0,0x30,bytes.length);if(outer[1]!==bytes.length)throw Error();const tbs=tlv(outer[0],0x30,outer[1]);let pos=tbs[0];if(bytes.charCodeAt(pos)===0xa0)pos=tlv(pos,0xa0,tbs[1])[1];const serial=tlv(pos,0x02,tbs[1]);if(serial[0]===serial[1])throw Error();pos=serial[1];
      pos=tlv(pos,0x30,tbs[1])[1];pos=tlv(pos,0x30,tbs[1])[1];
      const validity=tlv(pos,0x30,tbs[1]);pos=validity[0];for(let i=0;i<2;i++){const tag=bytes.charCodeAt(pos);if(tag!==0x17&&tag!==0x18)throw Error();pos=tlv(pos,tag,validity[1])[1];}if(pos!==validity[1])throw Error();
      pos=tlv(validity[1],0x30,tbs[1])[1];const spki=tlv(pos,0x30,tbs[1]);pos=tlv(spki[0],0x30,spki[1])[1];pos=tlv(pos,0x03,spki[1])[1];if(pos!==spki[1])throw Error();pos=spki[1];
      for(const tag of [0x81,0x82,0xa3])if(bytes.charCodeAt(pos)===tag)pos=tlv(pos,tag,tbs[1])[1];if(pos!==tbs[1])throw Error();
      pos=tlv(tbs[1],0x30,outer[1])[1];pos=tlv(pos,0x03,outer[1])[1];if(pos!==outer[1])throw Error();
    } catch {r.invalid.push('certificate');}
  }else if(p.certificate_mode==='none') {if((d.certificate?.value ?? '')!=='')r.invalid.push('certificate');}
  else if(p.certificate_mode==='unknown')r.missing.push('certificate_mode');else r.invalid.push('certificate_mode');
  if(own(p,'url') && (typeof p.url!=='string' || /[\x00-\x20\x7f]/.test(p.url)))r.invalid.push('url');
  if(own(p,'allowed_updates') && (!Array.isArray(p.allowed_updates)||!p.allowed_updates.every(x=>typeof x==='string')))r.invalid.push('allowed_updates');
  if(own(p,'max_connections') && (!Number.isInteger(p.max_connections)||p.max_connections<1||p.max_connections>(input.target_local===true?100000:100)))r.invalid.push('max_connections');
  for(const k of Object.keys(r.provenance))if(r.provenance[k]==='explicit'&&input.provenance?.[k])r.provenance[k]=input.provenance[k];
  r.complete=!r.missing.length&&!r.invalid.length;return r;
}
