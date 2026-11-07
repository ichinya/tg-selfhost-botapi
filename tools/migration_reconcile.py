"""Evidence binding and permitted observations; JSON is not proof of provenance."""
import re
import time
from migration_contract import canonical,fingerprint
from migration_engine import Stop,snapshot_value


def validate_external(s,record,*,now=None):
    fields={'version','operation_id','step_id','attempt_id','endpoint_fingerprint','token_fingerprint',
            'observed_at','outcome','provenance'}
    if not isinstance(record,dict) or set(record)!=fields or type(record['version']) is not int or record['version']!=1:
        raise ValueError('incomplete independent evidence')
    step=record['step_id']
    if step not in s['steps'] or not s['steps'][step]:
        raise ValueError('unknown evidence attempt')
    attempt=s['steps'][step][-1]
    side='source' if step.startswith('source_') else 'target'
    for n,v in [('operation_id',s['plan']['operation_id']),('attempt_id',attempt['id']),
                ('endpoint_fingerprint',s['plan'][side+'_fingerprint']),('token_fingerprint',s['plan']['token_fingerprint'])]:
        if record[n]!=v:
            raise ValueError('independent evidence binding mismatch')
    observed=record['observed_at']
    if type(observed) not in (int,float) or not attempt['events'][0]['time'] <= observed <= (time.time() if now is None else now)+5:
        raise ValueError('evidence time does not match attempt')
    if record['outcome'] not in ('performed','not_performed'):
        raise ValueError('evidence must distinguish performed and not performed')
    provenance=record['provenance']
    if not isinstance(provenance,dict) or set(provenance)!={'kind','reference','verified_by'}:
        raise ValueError('evidence provenance required')
    if provenance['kind'] not in ('server_audit','transport_audit','fixture'):
        raise ValueError('unsupported evidence provenance')
    if provenance['kind']=='fixture' and not s['plan']['fixture']:
        raise ValueError('fixture evidence is not valid for a real endpoint')
    for n in ('reference','verified_by'):
        if not isinstance(provenance[n],str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}',provenance[n]):
            raise ValueError('invalid provenance reference')
    return step


def apply_external(journal,s,record):
    step=validate_external(s,record)
    if journal.outcome(s,step)!='unknown':
        raise ValueError('evidence requires an unknown attempt')
    evidence=fingerprint(journal.key,canonical(record))
    journal.finish(s,step,'confirmed' if record['outcome']=='performed' else 'failed',
                   'external_performed' if record['outcome']=='performed' else 'external_not_performed',evidence=evidence)


def reconcile_allowed(engine,s):
    j,r=engine.j,engine.r
    detach = engine.detach(s)
    if detach and j.outcome(s,detach)=='unknown':
        raise Stop('logout_evidence_required')
    for step in ('source_delete','target_authorize','target_configure'):
        if step not in s['steps']:
            continue
        if j.outcome(s,step)!='unknown':
            continue
        if step=='source_delete':
            if not detach or j.outcome(s,detach)!='pending':
                raise Stop('source_observation_not_permitted')
            info=snapshot_value(engine.observe(r.source,'getWebhookInfo'))
            if info['url']:
                raise Stop('source_delete_unresolved_new_plan_required')
            evidence=fingerprint(j.key,canonical({'operation':s['plan']['operation_id'],
                                 'attempt':s['steps'][step][-1]['id'],'empty_source_webhook':True}))
            j.finish(s,step,'confirmed','source_webhook_observed',evidence=evidence)
        elif step=='target_authorize':
            if not detach or j.outcome(s,detach)!='confirmed':
                raise Stop('source_disable_not_confirmed')
            # getMe may authorize again. Persist a distinct observation intent
            # on the same uncertain attempt, retaining its UNKNOWN history.
            j.reconciliation_intent(s,step)
            result=engine.client.request(r.target,'getMe',token=r.token,effect=True)
            data=result.data
            matched=(result.outcome=='confirmed' and isinstance(data,dict)
                     and type(data.get('id')) is int and str(data['id'])==r.bot_id and data.get('is_bot') is True)
            j.finish(s,step,'confirmed' if matched else 'unknown',
                     'target_identity_observed' if matched else 'target_identity_unresolved',
                     evidence=fingerprint(j.key,canonical({'attempt':s['steps'][step][-1]['id'],'identity_matches':matched})))
            if not matched:
                raise Stop('target_authorization_unresolved')
        else:
            if r.drop:
                raise Stop('drop_effect_requires_independent_evidence')
            info=snapshot_value(engine.observe(r.target,'getWebhookInfo'))
            wanted='' if r.action=='polling' else r.profile['url']
            if info['url']!=wanted:
                raise Stop('target_configuration_unresolved')
            # URL-only is an explicit limitation, never a hidden-profile claim.
            evidence=fingerprint(j.key,canonical({'attempt':s['steps'][step][-1]['id'],'url_only_match':True}))
            j.finish(s,step,'confirmed','target_configuration_observed',evidence=evidence)


def apply_delivery(journal,s,record):
    fields={'operation_id','target_fingerprint','received_at','update_id','payload_digest','consumer_id','mode','provenance'}
    if not isinstance(record,dict) or set(record)!=fields:
        raise ValueError('incomplete delivery receipt')
    if (record['operation_id']!=s['plan']['operation_id'] or record['target_fingerprint']!=s['plan']['target_fingerprint']
            or record['mode'] not in ('mock','live') or type(record['update_id']) is not int
            or not isinstance(record['payload_digest'],str) or not re.fullmatch('[0-9a-f]{64}',record['payload_digest'])
            or any(not isinstance(record[n],str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}',record[n]) for n in ('consumer_id','provenance'))
            or type(record['received_at']) not in (int,float) or not 0 <= time.time()-record['received_at'] <= 300):
        raise ValueError('invalid delivery evidence')
    if ('application_start' not in s['checkpoints'] or 'target_verified' not in s['checkpoints']
            or s['results']['webhook_configuration']!='confirmed'):
        raise ValueError('delivery requires controlled start and verified configuration')
    if record['received_at'] < s['checkpoints']['application_start']['time']:
        raise ValueError('delivery update predates controlled application start')
    if s['plan']['fixture'] and record['mode']!='mock':
        raise ValueError('fixture delivery cannot be labelled live')
    journal.checkpoint(s,'delivery',canonical(record))
    s['results']['delivery_verification']=record['mode']
    journal.save(s)
