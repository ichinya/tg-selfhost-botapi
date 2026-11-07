"""Phase-aware cloud -> local executor. All durable writes use Journal."""
from dataclasses import dataclass
import re
import time
from migration_contract import (build_plan, canonical, fingerprint,
                                normalize_endpoint, validate_binding)
from migration_store import StateError


class Stop(Exception):
    def __init__(self, reason, code=2):
        self.reason,self.code=reason,code
        super().__init__(reason)


@dataclass(frozen=True)
class Runtime:
    source: str
    target: str
    token: str
    profile: dict
    action: str
    drop: bool = False
    fixture: bool = False
    direction: str = 'cloud_to_local'
    local_mode: bool = True
    queue_ack: bool = False
    cloud_not_before: float | None = None

    @property
    def bot_id(self):
        if not isinstance(self.token,str) or not re.fullmatch(r'[1-9][0-9]*:[A-Za-z0-9_-]+',self.token):
            raise ValueError('invalid bot token format')
        return self.token.split(':',1)[0]

    def plan(self, operation, key, deployment=None):
        return build_plan(operation_id=operation,bot_id=self.bot_id,source=self.source,target=self.target,
                          token=self.token,profile=self.profile,action=self.action,drop=self.drop,
                          fixture=self.fixture,key=key,direction=self.direction,local_mode=self.local_mode,
                          queue_ack=self.queue_ack,cloud_not_before=self.cloud_not_before,deployment=deployment)

    def bind(self, state, key):
        # Rebuild also enforces the supported direction and fixture boundary.
        candidate=self.plan(state['plan']['operation_id'],key,state['deployment'])
        if candidate!=state['plan']:
            raise ValueError('runtime bindings changed')
        validate_binding(state['plan'],state['digest'],dict(source=self.source,target=self.target,
                         token=self.token,profile=self.profile,action=self.action,drop=self.drop),key)


def snapshot_value(info):
    if not isinstance(info,dict) or not isinstance(info.get('url'),str):
        raise Stop('invalid_webhook_observation',1)
    return {k:info.get(k) for k in ('url','has_custom_certificate','max_connections','allowed_updates','ip_address')}


class Engine:
    def __init__(self,journal,client,readiness,runtime,verifier=None):
        self.j,self.client,self.readiness,self.r=journal,client,readiness,runtime
        self.verifier = verifier

    @staticmethod
    def ids(s):
        return tuple(step['id'] for step in s['plan']['steps'])

    @staticmethod
    def detach(s):
        return 'source_close' if 'source_close' in s['steps'] else 'source_logout' if 'source_logout' in s['steps'] else None

    def checkpoint(self, s, kind, receipt):
        if self.r.fixture and kind in ('endpoint_change', 'application_start') and kind in s['checkpoints']:
            return None
        if self.r.fixture and isinstance(receipt, str) and receipt:
            value = {'kind': kind, 'operation_id': s['plan']['operation_id'], 'digest': s['digest'],
                     'observed_at': time.time(), 'provenance': 'fixture', 'reference': receipt}
        else:
            if not isinstance(receipt, dict) or self.verifier is None:
                raise Stop('trusted_checkpoint_required')
            value = self.verifier(receipt, kind=kind, state=s)
        if kind == 'quiescence' and self.r.direction == 'local_to_cloud' and not self.r.fixture:
            if (value.get('cloud_not_before') != self.r.cloud_not_before or self.r.cloud_not_before is None
                    or value.get('cloud_availability_verified') is not True or value.get('queue_limitation_ack') is not True):
                raise Stop('cloud_cooldown_evidence_required')
        if kind == 'application_start' and kind not in s['checkpoints'] and value['observed_at'] < s['checkpoints']['target_verified']['time']:
            raise Stop('application_start_predates_target_verification')
        self.j.checkpoint(s, kind, canonical(value))
        return value

    def observe(self,endpoint,method):
        result=self.client.request(endpoint,method,token=self.r.token,effect=False)
        if result.outcome!='confirmed':
            raise Stop('observation_'+result.reason,3 if result.outcome=='waiting' else 1)
        return result.data

    def identity(self,endpoint):
        data=self.observe(endpoint,'getMe')
        if not isinstance(data,dict) or type(data.get('id')) is not int or str(data['id'])!=self.r.bot_id or data.get('is_bot') is not True:
            raise Stop('bot_identity_mismatch',1)
        return data

    def gate(self,s=None):
        try:
            deployment=self.readiness.check(self.r.target)
            from migration_probe import validate_webhook_mode
            mode = getattr(self.readiness, 'local_mode', None)
            if not self.r.fixture and mode != self.r.local_mode:
                raise ValueError('unverified deployment capability')
            validate_webhook_mode(self.r.profile, self.r.local_mode)
            if s is not None and (s['deployment'] is None or s['deployment']!=deployment):
                raise ValueError('deployment changed from the reviewed plan')
        except (ValueError,OSError):
            if s is not None:
                s['results']['service_readiness']='blocked'
                self.j.save(s)
            raise Stop('target_not_ready') from None
        if s is not None:
            s['results']['service_readiness']='confirmed'
            self.j.save(s)
        return deployment

    def prepare(self,operation,*,quiescence,url_only_ack=False,supersede=None):
        plan=self.r.plan(operation,self.j.key)  # validation before any API
        if self.j.bot!=self.r.bot_id:
            raise StateError('per-bot lock required')
        if (not quiescence and self.r.fixture) or self.r.profile.get('mode') == 'url_only' and not url_only_ack:
            raise Stop('quiescence_and_profile_ack_required')
        # Reserve exclusivity before even a source snapshot.
        previous=None
        for p in self.j.store.root.glob('*.json'):
            old=self.j.load(p.stem)
            if old['plan']['operation_id']==supersede:
                if old['plan']['bot_id']!=self.r.bot_id or any(old['steps'].values()):
                    raise StateError('only an untouched plan for the same bot may be superseded')
                previous=old
                continue
            if old['plan']['operation_id']==operation or (old['plan']['bot_id']==self.r.bot_id and old['results']['migration_outcome']!='confirmed' and 'superseded' not in old['checkpoints']):
                raise StateError('existing operation requires resume')
        if supersede and previous is None:
            raise StateError('superseded plan was not found')
        deployment=self.gate()
        plan=self.r.plan(operation,self.j.key,deployment)
        if previous:
            self.j.supersede(previous,operation)
        # Durable reservation precedes all bot-bearing observations.
        state=self.j.create(plan,None,deployment=deployment)
        if not quiescence:
            return state  # sealed reviewable plan; source observations wait for a signed checkpoint
        self.checkpoint(state,'quiescence',quiescence)
        self.prepare_snapshot(state)
        return state

    def prepare_snapshot(self, state):
        self.identity(self.r.source)
        snapshot=snapshot_value(self.observe(self.r.source,'getWebhookInfo'))
        if self.r.action=='preserve' and snapshot['url']!=self.r.profile['url']:
            raise Stop('preserve_profile_does_not_match_source')
        if self.r.action == 'preserve' and self.r.profile.get('mode') == 'full':
            raise Stop('full_preserve_requires_original_private_profile_verification')
        state['snapshot'] = fingerprint(self.j.key,canonical(snapshot))
        self.j.save(state)

    def _receipt(self,s,step,result):
        self.j.finish(s,step,result.outcome,result.reason,http_status=result.status,
                      api_code=result.api_code,not_before=result.not_before)
        if result.outcome!='confirmed':
            self.summary(s)
            raise Stop(step+'_'+result.reason,3 if result.outcome=='waiting' else 1 if result.outcome=='failed' else 2)

    def mutate(self,s,step,endpoint,method,params=None):
        self.j.intent(s,step)
        result=self.client.request(endpoint,method,token=self.r.token,params=params,effect=True)
        if step=='target_authorize' and result.outcome=='confirmed':
            data=result.data
            if not isinstance(data,dict) or type(data.get('id')) is not int or str(data['id'])!=self.r.bot_id or data.get('is_bot') is not True:
                from migration_http import Result
                result=Result('failed','bot_identity_mismatch',result.status)
        self._receipt(s,step,result)

    def summary(self,s):
        detach = self.detach(s)
        disabled=bool(detach and self.j.outcome(s,detach)=='confirmed')
        configured=self.j.outcome(s,'target_configure')=='confirmed'
        s['results']['migration_outcome']='partial' if disabled else 'unknown' if detach and self.j.outcome(s,detach)=='unknown' else 'pending'
        if not configured:
            s['results']['webhook_configuration']=self.j.outcome(s,'target_configure') if self.j.outcome(s,'target_configure') in ('failed','unknown') else 'pending'
        checkpoints = ('target_verified',) if self.r.direction == 'webhook_only' else ('target_verified','endpoint_change','application_start')
        if configured and s['results']['webhook_configuration']=='confirmed' and all(k in s['checkpoints'] for k in checkpoints):
            s['results']['migration_outcome']='confirmed'
        self.j.save(s)
        return dict(operation_id=s['plan']['operation_id'],digest=s['digest'],
                    steps={x:self.j.outcome(s,x) for x in self.ids(s)},results=s['results'],
                    checkpoints=list(s['checkpoints']),profile_scope=self.r.profile['mode'])

    def run(self,s,*,confirm_digest=None,quiescence=None,endpoint_change=None,application_start=None,
            state_transfer=None,resume=False):
        self.r.bind(s,self.j.key)  # input changes block even token-free probes
        if 'superseded' in s['checkpoints']:
            raise Stop('plan_was_superseded')
        self.j.recover(s)
        if confirm_digest is not None:
            if confirm_digest!=s['digest']:
                raise ValueError('plan confirmation digest mismatch')
            self.j.checkpoint(s,'confirmed',confirm_digest)
        if 'confirmed' not in s['checkpoints']:
            raise Stop('plan_confirmation_required')
        # Unknown logout is never resolved through another token-bearing call.
        detach = self.detach(s)
        if detach and self.j.outcome(s,detach)=='unknown':
            raise Stop('logout_evidence_required')
        for step in self.ids(s):
            if self.j.outcome(s,step)=='waiting':
                until=s['steps'][step][-1]['events'][-1]['not_before']
                if until is None or time.time()<until:
                    raise Stop('retry_not_before',3)
        if (not detach or self.j.outcome(s,detach)!='confirmed' or self.j.outcome(s,'target_authorize')!='confirmed'
                or 'endpoint_change' not in s['checkpoints'] and not endpoint_change):
            if not quiescence:
                raise Stop('fresh_quiescence_required')
            self.checkpoint(s,'quiescence',quiescence)
        self.gate(s)
        self.reconcile_unknown(s)
        if s['snapshot'] is None and not any(s['steps'].values()):
            self.prepare_snapshot(s)
        if 'source_delete' in s['steps'] and self.j.outcome(s,'source_delete') in ('pending','failed','waiting'):
            self.identity(self.r.source)
            observed=snapshot_value(self.observe(self.r.source,'getWebhookInfo'))
            if fingerprint(self.j.key,canonical(observed))!=s['snapshot']:
                raise Stop('source_snapshot_changed_new_plan_required')
        for step in self.ids(s):
            outcome=self.j.outcome(s,step)
            if outcome=='confirmed':
                continue
            if outcome=='unknown':
                raise Stop('independent_evidence_required')
            if outcome in ('failed','waiting') and not resume:
                raise Stop('explicit_resume_required',3 if outcome=='waiting' else 1)
            if outcome=='waiting':
                until=s['steps'][step][-1]['events'][-1]['not_before']
                if until is None or time.time()<until:
                    raise Stop('retry_not_before',3)
            if step=='source_delete':
                self.gate(s)
                self.mutate(s,step,self.r.source,'deleteWebhook',{'drop_pending_updates':'false'})
            elif step in ('source_logout', 'source_close'):
                self.gate(s)
                info=snapshot_value(self.observe(self.r.source,'getWebhookInfo'))
                if info['url']:
                    raise Stop('source_webhook_changed')
                self.mutate(s,step,self.r.source,'close' if step == 'source_close' else 'logOut')
                self.summary(s)  # distinct durable source_disabled result
            elif step=='target_authorize':
                if self.r.direction == 'local_to_cloud':
                    until = self.r.cloud_not_before
                    if until is None and not self.r.fixture:
                        raise Stop('cloud_cooldown_evidence_required')
                    if until is not None and time.time() < until:
                        raise Stop('cloud_cooldown_waiting', 3)
                self.gate(s)
                self.mutate(s,step,self.r.target,'getMe')
            elif step=='state_transfer':
                if not state_transfer:
                    raise Stop('state_transfer_checkpoint_required')
                self.transfer(s, state_transfer)
            else:
                if self.r.direction == 'webhook_only' and self.r.action == 'preserve' and not self.r.drop:
                    self.verify_target(s)
                    self.j.intent(s,step)
                    self.j.finish(s,step,'confirmed','target_configuration_observed',evidence=s['snapshot'])
                    continue
                params={'drop_pending_updates':'true' if self.r.drop else 'false'}
                method='deleteWebhook' if self.r.action=='polling' else 'setWebhook'
                if method=='setWebhook':
                    params.update({k:v for k,v in self.r.profile.items() if k != 'mode'})
                self.mutate(s,step,self.r.target,method,params)
        self.verify_target(s)
        if self.r.direction == 'webhook_only':
            return self.summary(s)
        if endpoint_change:
            self.checkpoint(s,'endpoint_change',endpoint_change)
        if 'endpoint_change' not in s['checkpoints']:
            raise Stop('endpoint_change_checkpoint_required')
        if application_start:
            self.checkpoint(s,'application_start',application_start)
        if 'application_start' not in s['checkpoints']:
            raise Stop('controlled_application_start_required')
        return self.summary(s)

    def transfer(self, s, receipt):
        if not isinstance(receipt, dict):
            raise Stop('typed_transfer_receipt_required')
        value = receipt if self.r.fixture else self.verifier(receipt, kind='state_transfer', state=s) if self.verifier else None
        if not value:
            raise Stop('trusted_transfer_receipt_required')
        expected = {'operation_id':s['plan']['operation_id'], 'digest':s['digest'],
                    'close_attempt':s['steps']['source_close'][-1]['id'],
                    'source_fingerprint':s['plan']['source_fingerprint'],
                    'target_fingerprint':s['plan']['target_fingerprint'],
                    'target_deployment':s['deployment'], 'source_closed':True,
                    'no_writers':True, 'layout_valid':True}
        if any((value.get(k) is not v) if type(v) is bool else value.get(k) != v for k,v in expected.items()):
            raise Stop('transfer_binding_mismatch')
        if (not isinstance(value.get('source_manifest'), str) or not re.fullmatch('[0-9a-f]{64}',value['source_manifest'])
                or value.get('target_manifest') != value['source_manifest']
                or not isinstance(value.get('source_deployment'),str) or not re.fullmatch('[0-9a-f]{64}',value['source_deployment'])
                or any(type(value.get(k)) is not int or value[k] < 0 for k in ('uid','gid'))
                or type(value.get('observed_at')) not in (int,float)
                or not s['steps']['source_close'][-1]['events'][-1]['time'] <= value['observed_at'] <= time.time()):
            raise Stop('transfer_manifest_or_ownership_unverified')
        deployment = getattr(self.readiness, 'record', None)
        if deployment and any(value[k] != deployment['runtime_'+k] for k in ('uid', 'gid')):
            raise Stop('transfer_runtime_ownership_mismatch')
        self.j.checkpoint(s,'state_transfer',canonical(value))
        self.j.intent(s,'state_transfer')
        self.j.finish(s,'state_transfer','confirmed','external_performed',evidence=fingerprint(self.j.key,canonical(value)))

    def verify_target(self,s):
        info=snapshot_value(self.observe(self.r.target,'getWebhookInfo'))
        wanted='' if self.r.action=='polling' else self.r.profile['url']
        if info['url']!=wanted:
            s['results']['webhook_configuration']='failed'
            s['results']['migration_outcome']='partial'
            self.j.save(s)
            raise Stop('target_configuration_drift')
        if self.r.profile.get('mode') == 'full':
            for field in ('allowed_updates', 'max_connections', 'ip_address'):
                if field in self.r.profile and info.get(field) != self.r.profile[field]:
                    s['results']['webhook_configuration']='failed'
                    self.j.save(s)
                    raise Stop('target_configuration_drift')
        s['results']['webhook_configuration']='confirmed'
        self.j.checkpoint(s,'target_verified',canonical(info))
        self.j.save(s)

    def reconcile_unknown(self,s):
        from migration_reconcile import reconcile_allowed
        reconcile_allowed(self,s)

    def refresh(self, s):
        """Explicit phase-aware refresh; offline status never calls this."""
        self.r.bind(s, self.j.key)
        self.j.recover(s)
        detach = self.detach(s)
        if detach and self.j.outcome(s, detach) == 'unknown':
            raise Stop('detach_evidence_required')
        self.gate(s)
        self.reconcile_unknown(s)
        if self.j.outcome(s, 'target_configure') == 'confirmed':
            self.verify_target(s)
        return self.summary(s)
