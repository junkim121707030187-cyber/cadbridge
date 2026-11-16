"""Integrator-owned strict IR schema and the legacy OCCT execution bridge."""
from copy import deepcopy
from functools import lru_cache
import math
import re
from jsonschema import Draft202012Validator
from cadbridge.model import validate_plan

VERSION = 'cadbridge.ir/1'
FRAME = {'origin':[0,0,0], 'x_axis':[1,0,0], 'y_axis':[0,1,0], 'z_axis':[0,0,1]}
ID = {'type':'string','pattern':r'^[A-Za-z][A-Za-z0-9_]{0,63}$'}
NUMBER = {'type':'number','minimum':-10000,'maximum':10000}
HASH = {'type':'string','pattern':'^[0-9a-f]{64}$'}

def obj(properties, required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}

def arr(items, minimum=0, maximum=512):
    return {'type':'array','items':items,'minItems':minimum,'maxItems':maximum}

CONSTRAINT_SCHEMA=obj({'id':ID,'type':{'enum':['dimension','equal','offset','symmetric']},'refs':arr(ID,1,3),'value':NUMBER,'provenance':{'enum':['measured','inferred']}},['id','type','refs','provenance'])
ENTITY_SCHEMA=obj({'id':ID,'kind':{'enum':['rectangle','circle']},'parameters':{'type':'object','additionalProperties':ID,'minProperties':3,'maxProperties':4},'evidence':arr(ID,1,1)})
FEATURE_SCHEMA=obj({'id':ID,'operation':{'enum':['extrude','pocket','through_hole']},'sketch':ID,'entity':ID,'parameters':{'type':'object','additionalProperties':ID,'maxProperties':2},'depends_on':arr(ID,0,100)})
IR_SCHEMA=obj({
 'schema_version':{'const':VERSION},'units':{'const':'mm'},'frame':{'const':FRAME},
 'source':obj({'kind':{'const':'step_measurement'},'sha256':HASH,'observation_sha256':HASH}),
 'proposal':obj({'kind':{'enum':['ai_proposal','rule_proposal']},'approval':{'const':'unapproved'}}),
 'parameters':arr(obj({'id':ID,'value':NUMBER,'evidence':arr({'type':'string','maxLength':100},1,8)}),1,400),
 'sketches':arr(obj({'id':ID,'plane':{'const':'XY'},'entities':arr(ENTITY_SCHEMA,1,100)}),1,101),
 'features':arr(FEATURE_SCHEMA,1,101),
 'constraints':arr(CONSTRAINT_SCHEMA,1,800),
 'execution_order':arr(ID,1,101),'rationale':{'type':'string','maxLength':2000}
})

class IRValidationError(ValueError):
    pass

def _unique(items,label):
    ids=[i['id'] for i in items]
    if len(ids)!=len(set(ids)):raise IRValidationError('duplicate_'+label+'_id')
    return {i['id']:i for i in items}

def validate_ir(ir, observation=None):
    errors=sorted(Draft202012Validator(IR_SCHEMA).iter_errors(ir),key=lambda e:str(list(e.path)))
    if errors:
        e=errors[0]
        raise IRValidationError('schema: '+'.'.join(map(str,e.path))+': '+e.validator)
    # JSON numeric validation must also reject NaN/Infinity (non-standard JSON).
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value):raise IRValidationError('nonfinite_number')
        if isinstance(value,dict):
            for v in value.values():finite(v)
        if isinstance(value,list):
            for v in value:finite(v)
    finite(ir)
    params=_unique(ir['parameters'],'parameter'); sketches=_unique(ir['sketches'],'sketch')
    feats=_unique(ir['features'],'feature'); _unique(ir['constraints'],'constraint')
    entities={}; used_params=set(); used_entities=set(); observed_features={}; expected_measurements=None
    if observation is not None:
        from .observations import validate_observation
        validate_observation(observation)
        if ir['source']['observation_sha256']!=observation['sha256'] or ir['source']['sha256']!=observation['source']['sha256']:
            raise IRValidationError('stale_observation_or_source_hash')
        expected_measurements=observation['measurements']
        g=observation['geometry']; observed_features={v['id']:v for v in [g['base']]+g['pockets']+g['holes']}
        if set(feats)!=set(observed_features):raise IRValidationError('missing_or_extra_observed_features')
        for p in params.values():
            if len(set(p['evidence']))!=len(p['evidence']) or not set(p['evidence'])<=set(expected_measurements):
                raise IRValidationError('invalid_measurement_evidence')
            # Parameters start from observed values; solutions can change on explicit edits.
            if any(abs(p['value']-expected_measurements[k]['value'])>1e-5 for k in p['evidence']):
                raise IRValidationError('parameter_guess_not_observed')
    for s in sketches.values():
        for e in s['entities']:
            if e['id'] in entities:raise IRValidationError('duplicate_entity_id')
            keys={'cx','cy','length','width'} if e['kind']=='rectangle' else {'cx','cy','diameter'}
            if set(e['parameters'])!=keys:raise IRValidationError('entity_parameters')
            if not set(e['parameters'].values())<=set(params):raise IRValidationError('dangling_parameter_reference')
            entities[e['id']]=(s['id'],e);used_params.update(e['parameters'].values())
    base=[f for f in feats.values() if f['operation']=='extrude']
    if len(base)!=1 or base[0]['id']!='base':raise IRValidationError('one_base_extrude_required')
    for f in feats.values():
        if f['entity'] not in entities or entities[f['entity']][0]!=f['sketch']:raise IRValidationError('dangling_entity_or_sketch_reference')
        _,e=entities[f['entity']]
        if f['entity'] in used_entities:raise IRValidationError('entity_reused_by_feature')
        used_entities.add(f['entity'])
        if e['evidence']!=[f['id']]:raise IRValidationError('entity_evidence_mismatch')
        op=f['operation']; keys={'z','thickness'} if op=='extrude' else {'depth'} if op=='pocket' else set()
        kind='circle' if op=='through_hole' else 'rectangle'
        if e['kind']!=kind or set(f['parameters'])!=keys:raise IRValidationError('unsupported_feature_profile')
        if not set(f['parameters'].values())<=set(params):raise IRValidationError('dangling_feature_parameter')
        used_params.update(f['parameters'].values())
        deps=f['depends_on']
        if len(deps)!=len(set(deps)) or not set(deps)<=set(feats):raise IRValidationError('invalid_dependency_reference')
        if op=='extrude' and deps:raise IRValidationError('base_must_have_no_dependencies')
        if expected_measurements is not None:
            observed=observed_features[f['id']]
            if set(observed)-{'id'}!=set(e['parameters'])|set(f['parameters']):raise IRValidationError('observed_feature_type_mismatch')
            for key,pid in (e['parameters']|f['parameters']).items():
                if f['id']+'.'+key not in params[pid]['evidence']:raise IRValidationError('parameter_entity_evidence_mismatch')
    if used_entities!=set(entities) or used_params!=set(params):raise IRValidationError('unconsumed_entity_or_parameter')
    used_sketches={s for s,_ in entities.values()}
    if used_sketches!=set(sketches):raise IRValidationError('unconsumed_sketch')
    visited=set();active=set()
    def visit(fid):
        if fid in active:raise IRValidationError('dependency_cycle')
        if fid in visited:return
        active.add(fid)
        for dep in feats[fid]['depends_on']:visit(dep)
        active.remove(fid);visited.add(fid)
    for fid in feats:visit(fid)
    @lru_cache(maxsize=None)
    def ancestors(fid):
        deps=set(feats[fid]['depends_on'])
        for dep in tuple(deps):deps.update(ancestors(dep))
        return deps
    if any('base' not in ancestors(fid) for fid in feats if fid!='base'):raise IRValidationError('cut_requires_base_ancestor')
    order=ir['execution_order']
    if len(order)!=len(set(order)) or set(order)!=set(feats) or order[0]!='base':raise IRValidationError('invalid_execution_order')
    indexes={v:i for i,v in enumerate(order)}
    if any(indexes[d]>=indexes[f['id']] for f in feats.values() for d in f['depends_on']):raise IRValidationError('execution_order_violates_dependencies')
    for c in ir['constraints']:
        kind=c['type'];refs=c['refs'];has_value='value' in c
        arity={'dimension':1,'equal':2,'offset':2,'symmetric':3}[kind]
        if len(refs)!=arity or len(set(refs))!=len(refs) or not set(refs)<=set(params):raise IRValidationError('invalid_constraint_references')
        if has_value!=(kind in ['dimension','offset']):raise IRValidationError('invalid_constraint_value')
        # Only a measured dimension may claim direct measurement. Relations are inferred.
        if c['provenance']=='measured':
            if kind!='dimension':raise IRValidationError('relation_cannot_claim_measured_provenance')
            if abs(c['value']-params[refs[0]]['value'])>1e-5:raise IRValidationError('dimension_cannot_claim_unobserved_value')
    return ir

def to_legacy(ir,values):
    """Lower solved sketches/features to the baseline kernel's bounded model."""
    validate_ir(ir)
    if set(values)!={p['id'] for p in ir['parameters']}:raise IRValidationError('solution_parameter_set_mismatch')
    entities={e['id']:e for s in ir['sketches'] for e in s['entities']}
    plan={'schema_version':'0.1','units':'mm','base':None,'holes':[],'pockets':[],'feature_order':ir['execution_order'][:]}
    for f in ir['features']:
        e=entities[f['entity']]
        row={'id':f['id'],**{k:values[v] for k,v in (e['parameters']|f['parameters']).items()}}
        if f['operation']=='extrude':plan['base']=row
        elif f['operation']=='pocket':plan['pockets'].append(row)
        else:plan['holes'].append(row)
    validate_plan(plan)
    return plan

def independent_rule(observation):
    """Measured independent dimensions; explicitly no inferred equality relations."""
    from .observations import validate_observation
    validate_observation(observation)
    ir={'schema_version':VERSION,'units':'mm','frame':deepcopy(FRAME),'source':{'kind':'step_measurement','sha256':observation['source']['sha256'],'observation_sha256':observation['sha256']},'proposal':{'kind':'rule_proposal','approval':'unapproved'},'parameters':[],'sketches':[],'features':[],'constraints':[],'execution_order':[],'rationale':'Deterministic baseline: independently dimension every measured primitive.'}
    g=observation['geometry']
    for f,op in [(g['base'],'extrude')]+[(p,'pocket') for p in g['pockets']]+[(h,'through_hole') for h in g['holes']]:
        fid=f['id']; entity_params={}; feature_params={}
        for k,v in f.items():
            if k=='id':continue
            pid=fid+'_'+k
            ir['parameters'].append({'id':pid,'value':v,'evidence':[fid+'.'+k]})
            ir['constraints'].append({'id':'dim_'+pid,'type':'dimension','refs':[pid],'value':v,'provenance':'measured'})
            (feature_params if k in ['z','thickness','depth'] else entity_params)[k]=pid
        sid='sketch_'+fid;eid='profile_'+fid
        ir['sketches'].append({'id':sid,'plane':'XY','entities':[{'id':eid,'kind':'circle' if op=='through_hole' else 'rectangle','parameters':entity_params,'evidence':[fid]}]})
        ir['features'].append({'id':fid,'operation':op,'sketch':sid,'entity':eid,'parameters':feature_params,'depends_on':[] if op=='extrude' else ['base']})
        ir['execution_order'].append(fid)
    validate_ir(ir,observation)
    return ir
