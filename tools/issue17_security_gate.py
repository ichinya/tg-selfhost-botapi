"""Explicit Linux/Docker acceptance; never invoked implicitly by unit discovery.

Only sanitized manifests leave this runner. Raw request receipts and logs live in
an owned temporary directory and are not CI artifacts. Missing gates fail closed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import quote
import uuid
from doctor_checks import nginx_config, nginx_privacy
from issue17_security_checks import assert_private_absent

ROOT=Path(__file__).resolve().parents[1]
POLICY='issue17-v1'
CASES=json.loads((ROOT/'tools/fixtures/issue17_security/cases.json').read_text())
MARKERS=list(CASES['markers'].values())


class GateFailure(Exception): pass


class UnitGateFailure(GateFailure):
    def __init__(self, stage):
        self.stage = stage


def command(args, *, env=None, data=None, timeout=120, check=True):
    try:
        result=subprocess.run(args,cwd=ROOT,env=env,input=data,capture_output=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired): raise GateFailure('runner_unavailable') from None
    if check and result.returncode: raise GateFailure('command_failed')
    return result


def output(args,**kwargs): return command(args,**kwargs).stdout.decode('utf-8',errors='replace')


def require_clean_candidate():
    status=output(['git','status','--porcelain','--untracked-files=normal'])
    if status.strip(): raise GateFailure('clean_candidate_required')


def unit_gate():
    try:
        require_clean_candidate()
    except GateFailure:
        raise UnitGateFailure('clean_candidate') from None
    steps = [
        ('discovery', [sys.executable,'-m','unittest','discover','-s','tools','-p','test_*.py'], 900),
        ('embed_profile', ['node','tools/embed_webhook_profile.cjs','--check'], 120),
        ('security_browser', ['node','tools/test_issue17_security_browser.cjs'], 120),
        ('security_shell', ['node','tools/test_issue17_security_shell.cjs'], 120),
        ('profile_ui', ['node','tools/webhook_profile_ui_harness.cjs'], 120),
        ('migration_ui', ['node','tools/test_migration_ui.mjs'], 120),
    ]
    for index, script in enumerate(('tools/webhook_profile_runtime.sh','tools/migration_diagnostics_main.sh','migrate_off_to_self.sh','tools/migration_executor.sh')):
        steps.append(('bash_syntax_' + str(index + 1), ['bash','-n',script], 120))
    steps.extend([('entrypoint_syntax', ['sh','-n','docker-entrypoint.sh'], 120),
                  ('diff_check', ['git','diff','--check'], 120)])
    for stage, args, timeout in steps:
        try:
            command(args, timeout=timeout)
        except GateFailure:
            raise UnitGateFailure(stage) from None
    return {'clean_candidate':True}


def compose_models(compose):
    with tempfile.TemporaryDirectory(prefix='issue17-secrets-') as directory:
        root=Path(directory)
        for name in ('id','hash'):
            (root/name).write_text('synthetic_issue17_'+name);(root/name).chmod(0o600)
        env=dict(os.environ,API_ID='legacy_id_canary',API_HASH='legacy_hash_canary',
            TELEGRAM_API_ID_SECRET_PATH=str(root/'id'),TELEGRAM_API_HASH_SECRET_PATH=str(root/'hash'))
        build_env=root/'build.env'
        command([sys.executable,'tools/image_inputs.py','--inputs-file','image-inputs.lock.json','--build-env',str(build_env)])
        env.update(line.split('=',1) for line in build_env.read_text(encoding='utf8').splitlines())
        for build in ([],['-f','docker-compose.build.yml']):
            base=compose+['-f','docker-compose.yml']+build
            old=json.loads(output(base+['config','--format','json'],env=env))
            if old['services']['botapi']['environment']['TELEGRAM_API_HASH']!='legacy_hash_canary': raise GateFailure('legacy_model_changed')
            model=json.loads(output(base+['-f','docker-compose.secrets.yml','config','--format','json'],env=env))
            bot=model['services']['botapi'];environment=bot['environment']
            if any(k in environment for k in ('TELEGRAM_API_ID','TELEGRAM_API_HASH')): raise GateFailure('inline_credentials_present')
            if environment.get('TELEGRAM_API_ID_FILE')!='/run/secrets/telegram_api_id' or environment.get('TELEGRAM_API_HASH_FILE')!='/run/secrets/telegram_api_hash': raise GateFailure('file_mount_contract')
            if model['services']['gateway'].get('secrets'): raise GateFailure('gateway_secret_grant')
            assert_private_absent(json.dumps(model),['legacy_id_canary','legacy_hash_canary'])
    return {'models':4}


def entrypoint_gate():
    name='issue17-entrypoint-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='issue17-entrypoint-') as directory:
        root=Path(directory)
        for name_part,value in (('id',CASES['markers']['api_id']),('hash',CASES['markers']['api_hash'])):
            (root/name_part).write_text(value);(root/name_part).chmod(0o644)
        binaries=root/'bin';binaries.mkdir()
        binary=binaries/'telegram-bot-api'
        binary.write_text('#!/bin/sh\nset -eu\n[ "$TELEGRAM_API_ID" = "$(cat /run/secrets/id)" ]\n[ "$TELEGRAM_API_HASH" = "$(cat /run/secrets/hash)" ]\n[ "$(ulimit -c)" = 0 ]\necho entrypoint_child_pass\n', newline='\n')
        binary.chmod(0o755)
        (binaries/'chown').write_text('#!/bin/sh\nexit 0\n', newline='\n');(binaries/'chown').chmod(0o755)
        args=['docker','create','--name',name,'--label','io.tg-selfhost.issue17=synthetic','--network','none','--user','101:101',
              '--ulimit','core=0','--mount',f'type=bind,src={binaries},dst=/privacy-bin,readonly',
              '--mount',f'type=bind,src={ROOT/"docker-entrypoint.sh"},dst=/entrypoint,readonly',
              '--mount',f'type=bind,src={root},dst=/run/secrets,readonly','--entrypoint','/bin/sh',
              '-e','PATH=/privacy-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
              '-e','TELEGRAM_API_ID_FILE=/run/secrets/id','-e','TELEGRAM_API_HASH_FILE=/run/secrets/hash',
              '-e','TELEGRAM_WORK_DIR=/tmp/state','-e','TELEGRAM_TEMP_DIR=/tmp/work','alpine:3.22','/entrypoint']
        created=False
        try:
            command(args);created=True
            inspected=json.loads(output(['docker','inspect',name]))[0]
            assert_private_absent(json.dumps(inspected['Config']['Env']),MARKERS)
            result=output(['docker','start','-a',name])
            if 'entrypoint_child_pass' not in result: raise GateFailure('entrypoint_positive_control_missing')
            assert_private_absent(result+output(['docker','logs',name]),MARKERS)
        finally:
            if created: command(['docker','rm','-f',name])
    return {'child_checks':2,'containers':1}


def raw_request(port,path,method='GET',body=b'',headers=None):
    headers=headers or {}
    raw=(method+' '+path+' HTTP/1.0\r\nHost: synthetic.invalid\r\n'+
         ''.join(k+': '+v+'\r\n' for k,v in headers.items())+
         'Content-Length: '+str(len(body))+'\r\n\r\n').encode()+body
    with socket.create_connection(('127.0.0.1',port),timeout=8) as stream:
        stream.settimeout(8);stream.sendall(raw);response=b''
        while True:
            part=stream.recv(65536)
            if not part: break
            response+=part
    return response


def gateway_gate(compose):
    project='issue17-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        root=Path(directory);evidence=root/'evidence';evidence.mkdir()
        config=root/'gateway.conf'
        config.write_text((ROOT/'nginx.conf').read_text().replace('client_max_body_size 1m;', 'client_max_body_size 1k;')
            .replace('proxy_read_timeout 600s;', 'proxy_read_timeout 1s;')
            .replace('proxy_read_timeout 30s;', 'proxy_read_timeout 1s;'))
        env=dict(os.environ,ISSUE17_ROOT=str(ROOT),ISSUE17_EVIDENCE=str(evidence),ISSUE17_GATEWAY_CONFIG=str(config))
        base=compose+['-p',project,'-f',str(ROOT/'tools/fixtures/issue17_security/compose.yml')]
        started=False
        try:
            started=True;command(base+['up','-d','--wait'],env=env,timeout=240)
            identifier=output(base+['ps','-q','gateway'],env=env).strip()
            inspect=json.loads(output(['docker','inspect',identifier]))[0]
            port=int(inspect['NetworkSettings']['Ports']['80/tcp'][0]['HostPort'])
            policy=output(['docker','exec',identifier,'nginx','-T'])
            if not nginx_privacy(nginx_config(policy)): raise GateFailure('effective_nginx_policy_unverified')
            values=dict(CASES['markers']);values['encoded_token']=quote(values['token'],safe='');values['double_token']=quote(values['encoded_token'],safe='')
            responses=[]
            for _ in range(30):
                response=raw_request(port,'/ready')
                responses.append(response)
                if b' 200 ' in response.split(b'\r\n',1)[0]:break
                time.sleep(.2)
            else:raise GateFailure('mock_readiness_control_missing')
            for template in CASES['paths']:
                responses.append(raw_request(port,template.format(**values),headers={'X-Telegram-Bot-Api-Secret-Token':values['secret']}))
            body=('url=https%3A%2F%2Fexample.invalid%2F'+values['endpoint']+'&secret_token='+values['secret']).encode()
            responses.append(raw_request(port,'/bot'+values['token']+'/setWebhook','POST',body,{'Content-Type':'application/x-www-form-urlencoded'}))
            responses.append(raw_request(port,'/unknown/'+values['secret'],'PRIVATE'))
            responses.append(raw_request(port,'/unknown/'+values['secret'],'POST',b'x'*2048))
            responses.append(raw_request(port,'/bad%ZZ/'+values['secret']))
            statuses={int(re.match(rb'HTTP/\S+ ([0-9]+)',r)[1]) for r in responses}
            if not {200,400,413,502,504}<=statuses: raise GateFailure('http_matrix_positive_control_missing')
            records=[json.loads(line) for line in (evidence/'requests.jsonl').read_text().splitlines()]
            if not any(r['path']=='/bot'+values['token']+'/getMe' for r in records): raise GateFailure('original_request_not_observed')
            if not any(values['secret'] in r['body'] and values['endpoint'] in r['body'] for r in records): raise GateFailure('private_payload_changed')
            log=output(base+['logs','--no-color'],env=env)
            regular=output(['docker','exec',identifier,'sh','-c','find /var/log/nginx -type f -exec cat {} \\;'])
            assert_private_absent(log+regular,MARKERS)
            if not re.search(r'GET api 200 [0-9]+ [0-9.]+',log): raise GateFailure('access_log_positive_control_missing')
            return {'requests':len(responses),'upstream_receipts':len(records),'access_records':len(re.findall(r' (?:api|file|other) [1-5][0-9]{2} ',log)),
                    'gateway_image_id':inspect['Image'],'effective_config_sha256':hashlib.sha256(policy.encode()).hexdigest()}
        finally:
            if started: command(base+['down','--volumes','--remove-orphans'],env=env,timeout=90)


def image_gate(image,expected_key=None):
    inspected=json.loads(output(['docker','image','inspect',image]))[0]
    labels=inspected.get('Config',{}).get('Labels') or {}
    if labels.get('io.tg-selfhost.privacy-policy')!=POLICY: raise GateFailure('candidate_policy_missing')
    revision=labels.get('io.tg-selfhost.bot-api-revision','');key=labels.get('io.tg-selfhost.build-key','')
    if not re.fullmatch('[a-f0-9]{40}',revision): raise GateFailure('candidate_revision_missing')
    if expected_key and key!=expected_key: raise GateFailure('candidate_build_key_mismatch')
    driver=output(['docker','run','--rm','--network','none','--entrypoint','botapi-privacy-driver',image],timeout=60)
    assert_private_absent(driver,MARKERS)
    if 'privacy_driver_pass' not in driver: raise GateFailure('candidate_driver_control_missing')
    result=command(['docker','run','--rm','--network','none',image,'--version'])
    version=(result.stdout+result.stderr).decode(errors='replace')
    if not re.search(r'Bot API [0-9]',version): raise GateFailure('candidate_version_control_missing')
    name='issue17-native-'+uuid.uuid4().hex[:12];created=False
    with tempfile.TemporaryDirectory(prefix=name) as directory:
        root=Path(directory)
        for part,value in (('id',CASES['markers']['api_id']),('hash',CASES['markers']['api_hash'])):
            (root/part).write_text(value);(root/part).chmod(0o600)
        try:
            command(['docker','create','--name',name,'--label','io.tg-selfhost.issue17=synthetic','--network','none','--ulimit','core=0',
                '--mount',f'type=bind,src={root},dst=/run/privacy,readonly','-e','TELEGRAM_API_ID_FILE=/run/privacy/id',
                '-e','TELEGRAM_API_HASH_FILE=/run/privacy/hash','-e','TELEGRAM_VERBOSITY=3','-e','TELEGRAM_LOG_FILE=/tmp/privacy.log',image]);created=True
            command(['docker','start',name])
            request=('GET /botinvalid_'+CASES['markers']['token']+'/getMe HTTP/1.0\r\nHost: localhost\r\n\r\n').encode()
            response=b''
            for _ in range(30):
                result=command(['docker','exec','-i',name,'sh','-c','nc -w 2 127.0.0.1 8081'],data=request,timeout=6,check=False)
                if b'HTTP/' in result.stdout:response=result.stdout;break
                time.sleep(.2)
            if not response: raise GateFailure('candidate_http_control_missing')
            command(['docker','exec',name,'sh','-c','kill -35 1'])
            for _ in range(20):
                logs=output(['docker','logs',name])
                if 'Log dump' in logs:break
                time.sleep(.2)
            file_log=output(['docker','exec',name,'cat','/tmp/privacy.log'])
            assert_private_absent(logs+file_log,MARKERS)
            if 'botapi_event' not in file_log or 'Log dump' not in logs: raise GateFailure('candidate_log_control_missing')
            return {'image_id':inspected['Id'],'repo_digests':inspected.get('RepoDigests',[]),'revision':revision,'build_key':key,
                    'native_requests':1,'source_driver':True,'file_log_records':file_log.count('botapi_event')}
        finally:
            if created:command(['docker','rm','-f',name])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit',action='store_true');parser.add_argument('--runtime',action='store_true')
    parser.add_argument('--models',action='store_true');parser.add_argument('--image');parser.add_argument('--expected-build-key')
    parser.add_argument('--compose-bin');parser.add_argument('--manifest',type=Path)
    args=parser.parse_args(argv)
    if not any((args.unit,args.runtime,args.models,args.image)):parser.error('select an explicit gate')
    compose=[args.compose_bin] if args.compose_bin else ['docker','compose']
    manifest={'schema_version':1,'policy':POLICY,'commit':None,'tools':{'python':sys.version.split()[0]},'gates':{}}
    try:
        sha=output(['git','rev-parse','HEAD']).strip()
        if re.fullmatch('[0-9a-f]{40}',sha):manifest['commit']=sha
    except GateFailure:pass
    gates=[]
    if args.unit:gates.append(('unit',unit_gate))
    if args.models or args.runtime:gates.append(('compose_models',lambda:compose_models(compose)))
    if args.runtime:gates.extend([('entrypoint',entrypoint_gate),('gateway',lambda:gateway_gate(compose))])
    if args.image:gates.append(('candidate_image',lambda:image_gate(args.image,args.expected_build_key)))
    failed=False
    for name,run in gates:
        try:manifest['gates'][name]={'status':'PASS','evidence':run()}
        except UnitGateFailure as exc:
            failed=True;manifest['gates'][name]={'status':'FAIL','reason':'required_gate_failed','stage':exc.stage}
        except (GateFailure,AssertionError,ValueError,KeyError,OSError):
            failed=True;manifest['gates'][name]={'status':'FAIL','reason':'required_gate_failed'}
    if args.runtime or args.models:
        try:manifest['tools']['compose']=output(compose+['version','--short']).strip()[:40]
        except GateFailure:manifest['tools']['compose']='UNKNOWN'
    if args.runtime or args.image:
        try:
            version=output(['docker','version','--format','{{.Server.Version}}']).strip()
            manifest['tools']['docker']=version if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version) else 'UNKNOWN'
        except GateFailure:manifest['tools']['docker']='UNKNOWN'
    if args.unit:
        try:
            version=output(['node','--version']).strip()
            manifest['tools']['node']=version if re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',version) else 'UNKNOWN'
        except GateFailure:manifest['tools']['node']='UNKNOWN'
    assert_private_absent(json.dumps(manifest),MARKERS)
    if args.manifest:args.manifest.write_text(json.dumps(manifest,sort_keys=True)+'\n')
    print(json.dumps(manifest,sort_keys=True))
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
