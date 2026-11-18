"""Bounded independent Compose collector; never infers a remote mutation."""
import argparse
from datetime import datetime
import hashlib, hmac, re, subprocess, time
from migration_contract import canonical, normalize_endpoint, validate_plan, plan_digest
from migration_probe import private_json
from migration_store import StateStore,Journal,StateError

class Collector:
    def __init__(self, config, inspect=None):
        fields={'provider','key_hex','fixture','project','containers','application','endpoint','endpoint_variable','target_fingerprint'}
        if not isinstance(config,dict) or set(config)!=fields:
            raise ValueError('closed provider configuration required')
        if (not re.fullmatch('[A-Za-z0-9_-]{1,64}',config['provider'])
                or not re.fullmatch('[0-9a-f]{64}',config['key_hex'])
                or type(config['fixture']) is not bool or not config['project']
                or not isinstance(config['containers'],dict) or not config['containers']
                or config['application'] not in config['containers']):
            raise ValueError('invalid provider configuration')
        for identity,policy in config['containers'].items():
            if (not re.fullmatch('[0-9a-f]{64}',identity) or set(policy)!={'service','image'}
                    or not re.fullmatch('sha256:[0-9a-f]{64}',policy['image'])):
                raise ValueError('exact container and image IDs required')
        normalize_endpoint(config['endpoint'])
        self.config=config
        self.inspect=inspect or self.docker_inspect

    @staticmethod
    def docker_inspect(identity):
        import json
        result=subprocess.run(['docker','inspect','--type','container',identity],capture_output=True,timeout=15,check=True)
        value=json.loads(result.stdout)
        if len(value)!=1: raise ValueError('one container required')
        return value[0]

    def collect(self, kind, state):
        if kind not in ('quiescence','endpoint_change','application_start'):
            raise ValueError('independent collector required for remote effect, state transfer or delivery')
        validate_plan(state['plan'])
        if (plan_digest(state['plan'])!=state['digest'] or self.config['fixture']!=state['plan']['fixture']
                or self.config['target_fingerprint']!=state['plan']['target_fingerprint']):
            raise ValueError('operation/deployment binding mismatch')
        observations={}
        for identity,policy in self.config['containers'].items():
            item=self.inspect(identity)
            labels=item['Config'].get('Labels') or {}
            if (item['Id']!=identity or item['Image']!=policy['image']
                    or labels.get('com.docker.compose.project')!=self.config['project']
                    or labels.get('com.docker.compose.service')!=policy['service']):
                raise ValueError('container topology changed')
            observations[identity]=item
        app=observations[self.config['application']]
        if kind=='quiescence':
            if any(i['State'].get('Running') is not False or i['State'].get('Status') not in ('exited','created') for i in observations.values()):
                raise ValueError('all allowlisted writers must be stopped')
        else:
            env=dict(entry.split('=',1) for entry in app['Config'].get('Env',[]) if '=' in entry)
            if normalize_endpoint(env.get(self.config['endpoint_variable'],''))!=normalize_endpoint(self.config['endpoint']):
                raise ValueError('effective application endpoint differs')
            if kind=='application_start':
                started=datetime.fromisoformat(app['State'].get('StartedAt','').replace('Z','+00:00')).timestamp()
                verified=state['checkpoints'].get('target_verified',{}).get('time')
                changed=state['checkpoints'].get('endpoint_change',{}).get('time')
                if (app['State'].get('Running') is not True or verified is None or changed is None
                        or not max(verified,changed)<=started<=time.time()):
                    raise ValueError('controlled application generation is unverified')
            elif app['State'].get('Running') is not False:
                raise ValueError('change endpoint while application is stopped')
        payload=dict(version=1,kind=kind,operation_id=state['plan']['operation_id'],digest=state['digest'],
                     target_deployment=state.get('deployment'),
                     observed_at=time.time(),source_fingerprint=state['plan']['source_fingerprint'],
                     target_fingerprint=state['plan']['target_fingerprint'],token_fingerprint=state['plan']['token_fingerprint'],
                     topology_sha256=hashlib.sha256(canonical({k:dict(image=v['Image'],started=v['State'].get('StartedAt')) for k,v in observations.items()}).encode()).hexdigest())
        if kind=='quiescence': payload['no_writers']=True
        else: payload['endpoint_fingerprint']=state['plan']['target_fingerprint']
        return dict(provider=self.config['provider'],payload=payload,
                    signature=hmac.new(bytes.fromhex(self.config['key_hex']),canonical(payload).encode(),hashlib.sha256).hexdigest())

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True); p.add_argument('--state-dir',required=True); p.add_argument('--operation',required=True)
    p.add_argument('--kind',choices=('quiescence','endpoint_change','application_start'),required=True)
    args=p.parse_args()
    try:
        store=StateStore(args.state_dir,create=False)
        try:
            state=Journal(store,read_only=True).load(args.operation)
            result=Collector(private_json(args.config)).collect(args.kind,state)
        finally:
            store.close()
        print(canonical(result)); return 0
    except (StateError,ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
        print(canonical({'status':'BLOCKED','reason':'independent_checkpoint_unverified'})); return 2

if __name__=='__main__': raise SystemExit(main())
