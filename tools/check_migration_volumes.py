"""Required Docker lifecycle fixture; deletion requires exact IDs/labels/mounts.

Only synthetic credentials and the fake executable enter the container. Its
real entrypoint, empty-root initialization and su-exec to 101:101 are exercised.
Nonempty roots are not re-owned. The fixture keeps its default 101:101 contract;
custom identities are qualified separately by check_nonroot.py. No Telegram session.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

LABEL='io.tg.migration.run'
DATA='/var/lib/telegram-bot-api'
TEMP='/tmp/telegram-bot-api'
FAKE='/usr/local/bin/telegram-bot-api'
FIXTURE=Path(__file__).resolve().parent/'fixtures'/'migration'/'docker-compose.volumes.yml'


class GateError(Exception):
    pass


def checked_resource(info,kind,identity,run,project):
    key='Name' if kind=='volume' else 'Id'
    if info.get(key)!=identity:
        raise GateError('resource identity mismatch')
    labels=info.get('Config',{}).get('Labels',{}) if kind=='container' else info.get('Labels',{})
    if not isinstance(labels,dict) or labels.get(LABEL)!=run or labels.get('com.docker.compose.project')!=project:
        raise GateError('resource ownership mismatch')
    return info


def checked_mounts(info,volumes,fake):
    mounts=info.get('Mounts',[])
    if len(mounts)!=3 or {m.get('Destination') for m in mounts}!={DATA,TEMP,FAKE}:
        raise GateError('unexpected fixture mounts')
    for m in mounts:
        destination=m['Destination']
        if destination==FAKE:
            if m.get('Type')!='bind' or Path(m.get('Source','')).resolve()!=Path(fake).resolve() or m.get('RW') is not False:
                raise GateError('unapproved bind mount')
        elif m.get('Type')!='volume' or m.get('Name')!=volumes[destination] or m.get('RW') is not True:
            raise GateError('unapproved named volume')
    return info


class Gate:
    def __init__(self,image,receipt):
        self.run='migvol-'+secrets.token_hex(8)
        self.project=self.run
        self.image=image
        self.receipt=Path(receipt)
        self.env={**os.environ,'MIGRATION_RUN_ID':self.run,'MIGRATION_FIXTURE_IMAGE':image}
        # Never load the user's .env, even when this tool runs from the repo root.
        self.compose=['compose','--env-file',os.devnull,'--project-name',self.project,'--file',str(FIXTURE)]
        self.volumes={DATA:self.project+'_data',TEMP:self.project+'_temp'}
        self.fake=FIXTURE.parent/'fake-bot-api.sh'
        self.containers=set()
        self.networks=set()
        self.created=False
        self.scenarios=[]

    def docker(self,*args,check=True):
        result=subprocess.run(['docker',*args],env=self.env,capture_output=True,text=True,timeout=60)
        if check and result.returncode:
            raise GateError('docker command failed')
        return result

    def inspect(self,kind,identity):
        args=['inspect',identity] if kind=='container' else [kind,'inspect',identity]
        return json.loads(self.docker(*args).stdout)[0]

    def container(self,identity):
        return checked_mounts(checked_resource(self.inspect('container',identity),'container',identity,
                                               self.run,self.project),self.volumes,self.fake)

    def capture(self):
        ids=self.docker('ps','--all','--quiet','--no-trunc','--filter',f'label={LABEL}={self.run}').stdout.split()
        for identity in ids:
            self.container(identity)
            self.containers.add(identity)
        networks=self.docker('network','ls','--quiet','--no-trunc','--filter',f'label={LABEL}={self.run}').stdout.split()
        for identity in networks:
            info=checked_resource(self.inspect('network',identity),'network',identity,self.run,self.project)
            if info['Name']!=self.project+'_default' or info.get('Internal') is not True:
                raise GateError('fixture network is not isolated')
            self.networks.add(identity)
        for name in self.volumes.values():
            checked_resource(self.inspect('volume',name),'volume',name,self.run,self.project)

    def create(self,mode='stay',api_id='12345'):
        for identity in list(self.containers):
            self.container(identity)
            self.docker('rm','--force',identity)
            self.containers.remove(identity)
        self.env['MIGRATION_FIXTURE_MODE']=mode
        self.env['MIGRATION_TEST_API_ID']=api_id
        self.created=True
        self.docker(*self.compose,'create','target')
        self.capture()
        if len(self.containers)!=1:
            raise GateError('one fixture target required')
        identity=next(iter(self.containers))
        self.docker('start',identity)
        return identity

    def wait_exit(self,identity,expected):
        result=self.docker('wait',identity)
        if int(result.stdout.strip())!=expected:
            raise GateError('unexpected fixture exit')

    def exec(self,identity,*args,user='101:101',check=True):
        self.container(identity)
        return self.docker('exec','--user',user,identity,*args,check=check)

    def sentinel(self,identity):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            value=self.exec(identity,'sh','-ec',
                            'test "$(id -u):$(id -g)" = 101:101; sha256sum "$1/persistent-sentinel"; stat -c "%u:%g:%a" "$1/persistent-sentinel"',
                            'sh',DATA,check=False)
            if value.returncode==0:
                return value.stdout.strip()
            time.sleep(.2)
        raise GateError('runtime cannot read persistent sentinel')

    def cleanup(self):
        if self.created:
            self.capture()
        for identity in list(self.containers):
            self.container(identity)
            self.docker('rm','--force',identity)
            self.containers.remove(identity)
        for name in self.volumes.values():
            if not self.created:
                continue
            checked_resource(self.inspect('volume',name),'volume',name,self.run,self.project)
            self.docker('volume','rm',name)
        for identity in self.networks:
            checked_resource(self.inspect('network',identity),'network',identity,self.run,self.project)
            self.docker('network','rm',identity)

    def execute(self):
        from migration_contract import build_plan
        from migration_store import StateStore,Journal
        diagnostic={'run_id':self.run,'scenarios':self.scenarios,'cleanup':'pending','result':'failed'}
        canary=self.run+'-canary'
        canary_created=False
        succeeded=False
        cleanup_ok=False
        try:
            image=json.loads(self.docker('image','inspect',self.image).stdout)[0]
            if image['Config']['Entrypoint']!=['/docker-entrypoint.sh']:
                raise GateError('candidate entrypoint mismatch')
            self.image=image['Id']
            self.env['MIGRATION_FIXTURE_IMAGE']=self.image
            diagnostic['image_id']=self.image
            self.docker('volume','create','--label',f'{LABEL}={self.run}-canary',canary)
            canary_created=True
            before=self.inspect('volume',canary)
            identity=self.create('fail')
            self.wait_exit(identity,73)
            self.scenarios.append('failure_after_runtime_write')
            identity=self.create()
            original=self.sentinel(identity)
            expected_entrypoint=hashlib.sha256((FIXTURE.parents[3]/'docker-entrypoint.sh').read_bytes()).hexdigest()
            actual=self.exec(identity,'sha256sum','/docker-entrypoint.sh').stdout.split()[0]
            if actual!=expected_entrypoint:
                raise GateError('candidate does not contain current entrypoint')
            self.exec(identity,'sh','-ec','mkdir /fixture-denied; chmod 500 /fixture-denied',user='0:0')
            denied=self.exec(identity,'sh','-ec','printf denied > /fixture-denied/new',check=False)
            if denied.returncode==0:
                raise GateError('denied write unexpectedly succeeded')
            self.scenarios.append('runtime_denied_write')
            self.exec(identity,'sh','-ec','printf changed > "$1/temp-sentinel"','sh',TEMP)
            if self.sentinel(identity)!=original:
                raise GateError('temp mutation affected data')
            self.scenarios.append('independent_temp_mount')
            with TemporaryDirectory(prefix='migvol-journal-') as temp:
                store=StateStore(Path(temp)/'private')
                try:
                    j=Journal(store)
                    plan=build_plan(operation_id='fixture',bot_id='123',source='https://api.telegram.org',
                                    target='https://fixture.example',token='123:synthetic',profile={'mode':'polling'},
                                    action='polling',drop=False,key=j.key)
                    with j.lock('123'):
                        s=j.create(plan,None)
                        for step in ('source_delete','source_logout'):
                            j.intent(s,step)
                            j.finish(s,step,'confirmed','fixture_success')
                    self.container(identity)
                    self.docker('stop','--time','3',identity)
                    if j.outcome(j.load('fixture'),'source_logout')!='confirmed':
                        raise GateError('host journal did not preserve source disable')
                    self.scenarios.append('target_stop_after_source_disable_host_journal')
                    self.docker('start',identity)
                    if self.sentinel(identity)!=original:
                        raise GateError('sentinel changed across SIGTERM/restart')
                    self.scenarios.append('sigterm_restart_resume')
                finally:
                    store.close()
            identity=self.create(api_id='')
            self.wait_exit(identity,1)
            self.scenarios.append('missing_credentials_before_startup')
            identity=self.create()
            if self.sentinel(identity)!=original:
                raise GateError('persistent data changed after startup failure')
            self.scenarios.append('persistent_hash_owner_mode_preserved')
            diagnostic['sentinel']=original
            succeeded=True
        except (GateError,OSError,ValueError,KeyError,subprocess.SubprocessError):
            diagnostic['reason']='fixture_failed'
        finally:
            try:
                self.cleanup()
                if canary_created:
                    after=self.inspect('volume',canary)
                    if before!=after:
                        raise GateError('canary modified')
                    diagnostic['canary']='preserved'
                    # This separate canary is removed only after the preservation
                    # assertion and exact identity/label recheck.
                    if after['Name']!=canary or after['Labels'].get(LABEL)!=self.run+'-canary':
                        raise GateError('canary identity changed')
                    self.docker('volume','rm',canary)
                cleanup_ok=True
            except (GateError,OSError,ValueError,KeyError,subprocess.SubprocessError):
                diagnostic['cleanup']='failed_resources_retained'
            diagnostic['cleanup']='confirmed' if cleanup_ok else 'failed_resources_retained'
            diagnostic['result']='confirmed' if succeeded and cleanup_ok else 'failed'
            self.receipt.parent.mkdir(parents=True,exist_ok=True)
            self.receipt.write_text(json.dumps(diagnostic,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(diagnostic))
        return 0 if succeeded and cleanup_ok else 1


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--require-docker',action='store_true')
    p.add_argument('--image',required=True)
    p.add_argument('--receipt',default='.migration-private/volume-gate.json')
    args=p.parse_args()
    if os.name!='posix' or not shutil.which('docker'):
        print('Required volume gate unavailable: Linux/POSIX and Docker are required',file=sys.stderr)
        return 1
    return Gate(args.image,args.receipt).execute()


if __name__=='__main__':
    raise SystemExit(main())
