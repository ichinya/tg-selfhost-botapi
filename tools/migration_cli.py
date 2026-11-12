"""Public, redacted CLI. No implicit dotenv execution or source discovery."""
import argparse
import getpass
import os
import re
import stat
import sys
import warnings
from migration_contract import canonical, normalize_endpoint
from migration_engine import Engine,Runtime,Stop
from migration_http import Client
from migration_probe import Readiness,CloudReadiness,DockerEvidence,private_json
from migration_reconcile import apply_external,apply_delivery,TrustedReceipts
from migration_export import export_operation
from migration_store import StateStore,Journal,StateError


ENV_KEYS={'BOT_TOKEN','BOT_TOKEN_FILE','OLD_BOT_URL','SELF_BOT_URL','WEBHOOK_URL',
          'MIGRATION_ACTION','DROP_PENDING_UPDATES','MIGRATION_STATE_DIR','MIGRATION_EVIDENCE_FILE',
          'TELEGRAM_BOT_URL','WEB_HOOK','MIGRATION_DIRECTION','MIGRATION_LOCAL_MODE',
          'MIGRATION_PROFILE_FILE','MIGRATION_TRUST_FILE','MIGRATION_QUEUE_ACK','MIGRATION_CLOUD_NOT_BEFORE'}


def private_text(path):
    if os.name!='posix':
        raise ValueError('private input requires POSIX; use Linux/WSL')
    signature=lambda s: (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    before=os.lstat(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    with os.fdopen(fd,'r',encoding='utf-8',newline='') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode) not in (0o400,0o600) or st.st_nlink!=1 or signature(st) != signature(before):
            raise ValueError('private input must be owned by operator with mode 0600')
        value=f.read(262145)
        if signature(os.fstat(f.fileno())) != signature(st) or signature(os.lstat(path)) != signature(st):
            raise ValueError('private input changed while reading')
    if len(value)>262144:
        raise ValueError('private input too large')
    return value


def parse_env(text):
    values={}
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith('#'):
            continue
        key,sep,value=line.partition('=')
        if not sep or not re.fullmatch('[A-Z][A-Z0-9_]*',key):
            raise ValueError('invalid helper env key')
        if key not in ENV_KEYS:
            if key not in {'API_ID','API_HASH','TELEGRAM_API_ID','TELEGRAM_API_HASH','DOWNLOAD_BASE_URL','PORT','HOST'}:
                raise ValueError('unknown helper env key')
            continue  # production configuration is data; never execute expansions
        if key in values:
            raise ValueError('duplicate helper env key')
        if value[:1] in ('"',"'"):
            if len(value)<2 or value[-1]!=value[0]:
                raise ValueError('invalid helper env quote')
            value=value[1:-1]
        if any(c in value for c in ('$','`','\x00','\r','\n')):
            raise ValueError('helper env expansion is not supported')
        values[key]=value
    return values


class Parser(argparse.ArgumentParser):
    def error(self,message):
        # Default argparse errors can include rejected tokens/URLs.
        raise ValueError('invalid CLI arguments; positional tokens are no longer accepted')


def parser():
    p=Parser(description='Safe cloud to local migration; secrets via environment/private files.')
    sub=p.add_subparsers(dest='command',required=True,parser_class=Parser)
    for name in ('plan','apply','status','resume','reconcile','export'):
        s=sub.add_parser(name)
        s.add_argument('--operation',required=True)
        s.add_argument('--state-dir')
        s.add_argument('--env-file')
        s.add_argument('--trust-file')
        s.add_argument('--forbidden-state-root',action='append',default=[],help='host data/temp/nginx webroot paths')
        if name=='export':
            continue
        if name=='status':
            s.add_argument('--refresh',action='store_true')
        if name=='reconcile':
            s.add_argument('--evidence-file')
            s.add_argument('--delivery-evidence-file')
            continue
        s.add_argument('--source')
        s.add_argument('--target')
        s.add_argument('--action',choices=('preserve','set','polling'))
        s.add_argument('--direction',choices=('cloud_to_local','local_to_local','local_to_cloud','webhook_only'))
        s.add_argument('--target-local-mode',choices=('true','false'))
        s.add_argument('--queue-limitation-ack',action='store_true',default=None)
        s.add_argument('--cloud-not-before',type=float)
        s.add_argument('--profile-file')
        s.add_argument('--drop-pending-updates',action='store_true',default=None)
        s.add_argument('--token-file')
        s.add_argument('--evidence-file')
        s.add_argument('--docker-container')
        s.add_argument('--expected-image-id')
        s.add_argument('--fixture-loopback',action='store_true',help='test only: literal loopback endpoints exclusively')
        s.add_argument('--quiescence-receipt')
        s.add_argument('--ack-url-only',action='store_true')
        if name=='plan':
            s.add_argument('--supersede-operation',help='replace only a plan with no mutation attempts')
        if name!='plan':
            s.add_argument('--confirm-digest')
            s.add_argument('--endpoint-change-receipt')
            s.add_argument('--application-start-receipt')
            s.add_argument('--state-transfer-file')
            s.add_argument('--quiescence-file')
            s.add_argument('--endpoint-change-file')
            s.add_argument('--application-start-file')
        else:
            s.add_argument('--quiescence-file')
    return p


def runtime(args,env,saved=None):
    source=args.source or env.get('OLD_BOT_URL')
    target=args.target or env.get('SELF_BOT_URL') or env.get('TELEGRAM_BOT_URL')
    if not source or not target:
        raise ValueError('explicit OLD_BOT_URL and SELF_BOT_URL required')
    token_file=args.token_file or env.get('BOT_TOKEN_FILE')
    token=env.get('BOT_TOKEN')
    if token_file and token:
        raise ValueError('select one token input')
    if token_file:
        token=private_text(token_file)
        token=re.sub(r'\r?\n\Z', '', token, count=1)
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
            raise ValueError('invalid token input')
    if not token:
        if not sys.stdin.isatty():
            raise ValueError('BOT_TOKEN or explicit private token file required')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            try:
                token=getpass.getpass('Bot token: ')
            except (getpass.GetPassWarning, EOFError) as exc:
                raise ValueError('hidden token input unavailable') from exc
    action=args.action or env.get('MIGRATION_ACTION') or (saved['plan']['action'] if saved else None)
    if not action:
        raise ValueError('explicit delivery action required')
    drop=args.drop_pending_updates
    if drop is None and 'DROP_PENDING_UPDATES' in env:
        if env['DROP_PENDING_UPDATES'] not in ('true','false'):
            raise ValueError('queue policy must be true or false')
        drop=env['DROP_PENDING_UPDATES']=='true'
    if drop is None:
        drop=saved['plan']['drop'] if saved else False
    profile_path=args.profile_file or env.get('MIGRATION_PROFILE_FILE')
    profile=private_json(profile_path) if profile_path else {'mode':'polling'} if action=='polling' else {'mode':'url_only','url':env.get('WEBHOOK_URL') or env.get('WEB_HOOK')}
    saved_plan=saved['plan'] if saved else {}
    direction=args.direction or env.get('MIGRATION_DIRECTION') or saved_plan.get('direction','cloud_to_local')
    mode=args.target_local_mode or env.get('MIGRATION_LOCAL_MODE')
    if mode is not None and mode not in ('true','false'):
        raise ValueError('explicit local mode required')
    local_mode=mode=='true' if mode else saved_plan.get('local_mode',direction!='local_to_cloud')
    ack=args.queue_limitation_ack
    if ack is None:
        ack=env.get('MIGRATION_QUEUE_ACK')=='true' or saved_plan.get('queue_ack',False)
    cooldown=args.cloud_not_before
    if cooldown is None:
        cooldown=float(env['MIGRATION_CLOUD_NOT_BEFORE']) if 'MIGRATION_CLOUD_NOT_BEFORE' in env else saved_plan.get('cloud_not_before')
    return Runtime(source,target,token,profile,action,drop,args.fixture_loopback,direction,local_mode,ack,cooldown)


def view(j,s):
    steps={name:j.outcome(s,name) for name in s['steps']}
    steps={name:'unknown' if outcome=='in_flight' else outcome for name,outcome in steps.items()}
    results=dict(s['results'])
    detach='source_close' if 'source_close' in steps else 'source_logout' if 'source_logout' in steps else None
    if detach and steps[detach]=='unknown':
        results['migration_outcome']='unknown'
    elif detach and steps[detach]=='confirmed' and results['migration_outcome']!='confirmed':
        results['migration_outcome']='partial'
    aggregate='blocked' if 'unknown' in steps.values() else 'confirmed' if results['migration_outcome']=='confirmed' else 'partial' if detach and steps[detach]=='confirmed' else 'pending'
    if 'superseded' in s['checkpoints'] or results['service_readiness']=='blocked':
        aggregate='blocked'
    return dict(operation_id=s['plan']['operation_id'],digest=s['digest'],steps=steps,
                aggregate=aggregate,results=results,checkpoints=list(s['checkpoints']),plan=s['plan'],
                attempts={name:a[-1]['id'] if a else None for name,a in s['steps'].items()},
                receipts={name:a[-1]['events'] if a else [] for name,a in s['steps'].items()},
                profile_scope=s['plan']['profile_scope'],freshness='saved_receipts_only')


def receipt(args, name):
    path=getattr(args,name+'_file',None)
    return private_json(path) if path else getattr(args,name+'_receipt',None)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'legacy':
        return legacy(argv[1:])
    args=j=store=s=None
    try:
        if sys.version_info<(3,11):
            raise ValueError('Python 3.11+ required')
        args=parser().parse_args(argv)
        if not re.fullmatch('[A-Za-z0-9_-]{1,128}',args.operation):
            raise ValueError('invalid operation identifier')
        env=parse_env(private_text(args.env_file)) if args.env_file else {}
        # CLI > process environment > explicit env file; no implicit cwd .env.
        env.update({k:v for k,v in os.environ.items() if k in ENV_KEYS})
        root=args.state_dir or env.get('MIGRATION_STATE_DIR')
        excluded=list(args.forbidden_state_root)
        online = args.command in ('plan','apply','resume') or args.command=='status' and args.refresh
        if online:
            evidence_path=args.evidence_file or env.get('MIGRATION_EVIDENCE_FILE')
            if evidence_path:
                record=private_json(evidence_path)
                if not isinstance(record,dict) or not isinstance(record.get('local_forbidden_roots'),list):
                    raise ValueError('local mount/webroot exclusions required before journal creation')
                from pathlib import Path
                if any(not isinstance(p,str) or not Path(p).is_absolute() for p in record['local_forbidden_roots']):
                    raise ValueError('invalid local mount exclusions')
                excluded.extend(record['local_forbidden_roots'])
            elif args.docker_container:
                adapter=DockerEvidence(args.docker_container,args.target or env.get('SELF_BOT_URL'),args.expected_image_id,b'0'*32)
                managed=adapter.inspect('inspect',adapter.container)
                excluded.extend(m['Source'] for m in managed['Mounts'])
        store=StateStore(root,create=args.command=='plan',data_dirs=excluded)
        j=Journal(store,read_only=args.command!='plan')
        verifier_path=args.trust_file or env.get('MIGRATION_TRUST_FILE')
        needs_verifier=online or args.command=='reconcile'
        verifier=TrustedReceipts(private_json(verifier_path)) if verifier_path and needs_verifier else None
        if args.command=='status' and not args.refresh:
            print(canonical(view(j,j.load(args.operation))))
            return 0
        if args.command=='export':
            print(canonical(export_operation(j.load(args.operation))))
            return 0
        if args.command=='reconcile':
            s=j.load(args.operation)
            with j.lock(s['plan']['bot_id']):
                s=j.load(args.operation)
                j.recover(s)
                if bool(args.evidence_file)==bool(args.delivery_evidence_file):
                    raise ValueError('select one evidence file')
                if args.evidence_file:
                    apply_external(j,s,private_json(args.evidence_file),verifier=verifier)
                else:
                    apply_delivery(j,s,private_json(args.delivery_evidence_file),verifier=verifier)
                detach=Engine.detach(s)
                if detach and j.outcome(s,detach)=='confirmed' and s['results']['migration_outcome']!='confirmed':
                    s['results']['migration_outcome']='partial'
                    j.save(s)
                print(canonical(view(j,s)))
                return 0
        if args.command!='plan':
            s=j.load(args.operation)
        r=runtime(args,env,s)
        r.plan(args.operation,j.key)
        client=Client(fixture=r.fixture)
        evidence=args.evidence_file or env.get('MIGRATION_EVIDENCE_FILE')
        if args.docker_container:
            if evidence or not args.expected_image_id:
                raise ValueError('managed target requires one expected image ID')
            provider=DockerEvidence(args.docker_container,r.target,args.expected_image_id,j.key)
        elif evidence:
            provider=lambda:private_json(evidence)
        elif r.direction=='local_to_cloud' and normalize_endpoint(r.target)=='https://api.telegram.org' and not r.fixture:
            provider=None
        else:
            raise ValueError('deployment evidence required')
        readiness=CloudReadiness(client,j.key) if provider is None else Readiness(client,provider,j.key,state_root=store.root)
        e=Engine(j,client,readiness,r,verifier=verifier)
        with j.lock(r.bot_id):
            if args.command=='plan':
                s=e.prepare(args.operation,quiescence=receipt(args,'quiescence'),url_only_ack=args.ack_url_only,
                            supersede=args.supersede_operation)
            else:
                s=j.load(args.operation)
                if args.command=='status':
                    e.refresh(s)
                    print(canonical(view(j,s)))
                    return 0
                e.run(s,confirm_digest=args.confirm_digest,quiescence=receipt(args,'quiescence'),
                      endpoint_change=receipt(args,'endpoint_change'),application_start=receipt(args,'application_start'),
                      state_transfer=private_json(args.state_transfer_file) if args.state_transfer_file else None,
                      resume=args.command=='resume')
            print(canonical(view(j,s)))
        return 0
    except Stop as exc:
        error={'reason':exc.reason,'exit_code':exc.code}
        if j and s:
            try:
                error['state']=view(j,j.load(s['plan']['operation_id']))
            except (StateError,ValueError,OSError):
                pass
        print(canonical(error))
        return exc.code
    except (StateError,ValueError,OSError,KeyError,EOFError,TypeError,RecursionError):
        error={'reason':'invalid_input_or_state','exit_code':4}
        if j and s:
            try:
                error['state']=view(j,j.load(s['plan']['operation_id']))
            except (StateError,ValueError,OSError,KeyError):
                pass
        print(canonical(error))
        return 4
    except KeyboardInterrupt:
        print(canonical({'reason':'operator_cancelled','exit_code':2}))
        return 2
    finally:
        if store:
            store.close()


def legacy(argv):
    """Translate legacy inputs to a reviewed sealed plan, then the same CLI."""
    import contextlib
    import io
    import json
    import uuid
    operation='legacy-'+uuid.uuid4().hex
    extra=list(argv)
    if not any(arg == '--operation' or arg.startswith('--operation=') for arg in extra):
        extra += ['--operation',operation]
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        code=main(['plan',*extra])
    if code:
        print(output.getvalue(),end='')
        return code
    # Never infer an action from an empty webhook or apply without digest review.
    state=json.loads(output.getvalue())
    state.update(reason='plan_confirmation_required', exit_code=2)
    print(canonical(state))
    return 2


if __name__=='__main__':
    raise SystemExit(main())
