"""Explicit isolated candidate-pair Docker smoke; no production mounts or bots."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'SYNTHETIC_PRIVATE_MARKER_16'


def command(argv, timeout=60, input=None, combined=False):
    result = subprocess.run(argv, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode: raise ValueError('smoke_command_failed')
    if len(result.stdout)+len(result.stderr) > 1024*1024: raise ValueError('smoke_output_limit')
    return result.stdout+result.stderr if combined else result.stdout


def smoke(botapi_image, observer_image, nginx_image):
    prefix = 'obs16-' + uuid.uuid4().hex[:12]
    network = prefix+'-network'
    names=[]
    stage = 'network'
    def launch(name, args, image, extra=()):
        name=prefix+'-'+name
        command(['docker','run','-d','--name',name,*args,image,*extra]); names.append(name)
        return name
    def read(observer,path,host='127.0.0.1',port=8090):
        script = ('import http.client,json; c=http.client.HTTPConnection('+repr(host)+','+str(port)+',timeout=4); '
                  'c.request("GET",'+repr(path)+'); r=c.getresponse(); print(json.dumps([r.status,r.read().decode()]))')
        return json.loads(command(['docker','exec',observer,'python3','-c',script]))
    def wait(observer,path,code=200,host='127.0.0.1',port=8090):
        for _ in range(30):
            try:
                result=read(observer,path,host,port)
                if result[0]==code:
                    if MARKER in result[1]: raise ValueError('privacy_failure')
                    return result
            except (ValueError, subprocess.SubprocessError): pass
            time.sleep(1)
        raise ValueError('candidate_runtime_gate_failed')
    try:
        command(['docker','network','create','--internal',network])
        # The gateway must start even before either upstream resolves.
        stage = 'gateway-start'
        gateway=launch('gateway',['--network',network,'--network-alias','gateway','--mount',
            'type=bind,src='+str(ROOT/'nginx.conf')+',dst=/etc/nginx/conf.d/default.conf,readonly',
            '--mount', 'type=bind,src='+str(ROOT/'nginx.observability.conf')+',dst=/etc/nginx/conf.d/observability.conf,readonly'],nginx_image)
        stage = 'gateway-without-upstream'
        script='import http.client,time; time.sleep(2); c=http.client.HTTPConnection("gateway",81,timeout=4); c.request("GET","/health/ready"); r=c.getresponse(); raise SystemExit(0 if r.status==503 else 1)'
        command(['docker','run','--rm','--network',network,'--entrypoint','python3',observer_image,'-c',script])
        for kind in ['mock','actual-off','actual-on']:
            stage = kind + '-start'
            target_args=['--network',network,'--network-alias','botapi']
            if kind=='mock':
                target=launch(kind,target_args+['--entrypoint','python3','--mount',
                    'type=bind,src='+str(ROOT/'tools/observability_mock_target.py')+',dst=/mock.py,readonly'],observer_image,['/mock.py'])
            else:
                target=launch(kind,target_args+['-e','TELEGRAM_API_ID=12345','-e','TELEGRAM_API_HASH='+'f'*32,
                    '-e','TELEGRAM_LOCAL=true','-e','TELEGRAM_STAT='+('true' if kind.endswith('on') else 'false')],botapi_image)
            observer=launch(kind+'-observer',['--network','container:'+target,'--read-only','--user','101:101',
                '--cap-drop','ALL','--security-opt','no-new-privileges','-e','TELEGRAM_STAT='+('false' if kind.endswith('off') else 'true')],observer_image)
            stage = kind + '-health'
            wait(observer,'/health/live'); wait(observer,'/health/ready')
            stage = kind + '-status-and-routes'
            document=wait(observer,'/status')
            status=json.loads(document[1])
            if status['queue']['sampled']['coverage']!='sampled': raise ValueError('coverage_failure')
            wait(observer,'/health/ready',host='gateway',port=81)
            for path in ['/selfz','/stats','/inputs/credentials','/status?'+MARKER]:
                result=read(observer,path,'gateway',81)
                if result[0] not in [400,403,404] or MARKER in result[1]: raise ValueError('route_failure')
            # A sibling must never reach raw stats on the owner's bridge address.
            script='import socket; s=socket.socket(); s.settimeout(1); rc=s.connect_ex(("botapi",8082)); raise SystemExit(0 if rc else 1)'
            command(['docker','run','--rm','--network',network,'--entrypoint','python3',observer_image,'-c',script])
            if kind == 'mock':
                stage = 'mock-ownership'
                # Recreate the pair with a simulated inherited runtime snapshot.
                from datetime import datetime, timezone
                observed = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                command(['docker','rm','-f',observer,target]); names.remove(observer); names.remove(target)
                time.sleep(2)
                target=launch('mock-recreated',target_args+['--entrypoint','python3','--mount',
                    'type=bind,src='+str(ROOT/'tools/observability_mock_target.py')+',dst=/mock.py,readonly'],observer_image,['/mock.py'])
                observer=launch('mock-recreated-observer',['--network','container:'+target,'--read-only','--user','101:101',
                    '--cap-drop','ALL','--security-opt','no-new-privileges','-e','TELEGRAM_STAT=true'],observer_image)
                wait(observer,'/health/ready')
                script = ('from unittest.mock import patch\nfrom observability.server import Collector\n'
                    'from observability.webhook import collect_webhooks\n'
                    'r=dict(schema_version=1,enabled=True,instance="a"*64,allow_unobserved_migration=True,'
                    'bots=[dict(alias="test",credential_file="test.json")])\n'
                    'image=dict(state="ready",instance="a"*64,observed_at='+repr(observed)+')\n'
                    'with patch("observability.runtime.read_runtime",return_value=(None,image)), '
                    'patch("observability.webhook.read_json",return_value=r), '
                    'patch("observability.probes.request") as request:\n'
                    ' result=collect_webhooks(Collector(),"registry.json")\n'
                    ' assert result["reason"]=="ownership_required"\n request.assert_not_called()\n')
                command(['docker','exec','-i',observer,'python3','-'],input=script.encode())
            if kind.startswith('actual'):
                stage = kind + '-healthcheck-and-privacy'
                output=command(['docker','exec',target,'/usr/local/bin/botapi-healthcheck'],combined=True)
                if output: raise ValueError('health_diagnostics_failure')
                # Intentionally invalid synthetic credential, no real authorization.
                # Deliver it through stdin, never command-line arguments.
                script=('from observability.probes import request\ntry:\n request("127.0.0.1",8081,"/bot123456:'+MARKER+'/getWebhookInfo")\nexcept Exception:\n pass\n')
                output=command(['docker','exec','-i',observer,'python3','-'],input=script.encode(),combined=True)
                if output: raise ValueError('token_probe_diagnostics_failure')
                if kind.endswith('off'):
                    script='import socket; s=socket.socket(); s.settimeout(1); raise SystemExit(0 if s.connect_ex(("127.0.0.1",8082)) else 1)'
                    command(['docker','exec',observer,'python3','-c',script])
            stage = kind + '-shutdown-and-logs'
            command(['docker','stop','--time','2',target])
            wait(observer,'/health/live',503)
            for name in [target,observer,gateway]:
                output=command(['docker','logs',name],combined=True)
                if MARKER.encode() in output: raise ValueError('log_privacy_failure')
            command(['docker','rm','-f',observer,target]); names.remove(observer); names.remove(target)
        return dict(mock='PASS', actual_pair='PASS', production='NOTRUN', kuma='NOTRUN')
    except Exception:
        # Only fixed internal stage names leave the harness; never print subprocess output.
        raise RuntimeError(stage) from None
    finally:
        # Names are random and created by this invocation; no host data is mounted.
        for name in reversed(names):
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--botapi-image',required=True); parser.add_argument('--observer-image',required=True)
    parser.add_argument('--nginx-image', required=True)
    args=parser.parse_args()
    try: print(json.dumps(smoke(args.botapi_image,args.observer_image,args.nginx_image)))
    except RuntimeError as error:
        print('observability_candidate_gate_failed: ' + str(error),file=sys.stderr); raise SystemExit(1)
