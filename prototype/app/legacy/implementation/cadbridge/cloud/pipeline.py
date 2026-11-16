"""Bounded candidate generation, strict gates, actual solver/CAD, persisted evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .ir import validate_ir, to_legacy, independent_rule
from .observations import ai_request, digest, validate_observation, verify_source_observation
from .providers import ProviderError, is_retryable_candidate_error
from .solver import solve
from cadbridge import kernel
from cadbridge.geometry import build_shape, compare_shapes


def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

class RuleProvider:
    mode='rule'
    def __init__(self):self.audit=[]
    def generate(self,request,feedback,attempt):
        candidate=independent_rule(request['observation'])
        self.audit.append({'mode':'rule','provider':'deterministic_independent_dimensions','model':None,'input_sha256':digest(request),'attempt':attempt,'prompt':None,'raw_response':deepcopy(candidate),'candidate_sha256':digest(candidate),'status':'generated'})
        return candidate


def execute_candidate(ir,observation,source_step,out_dir,edits=None):
    """Reconstruct or regenerate with a separate explicit edit transaction."""
    out=Path(out_dir)
    protected=['solver.json','result.step','model.ir.json','edits.json','model.legacy.json','validation.json']
    if any((out/name).exists() for name in protected):raise ValueError('output_already_exists')
    out.mkdir(parents=True,exist_ok=True)
    result={'schema_version':'cadbridge.validation/1','status':'FAIL','stage':'schema','native_status':'UNIMPLEMENTED_UNVERIFIED','edit_task_verification':'UNVERIFIED','limitations':['Affine scalar DOF only; generic nonlinear CAD constraints unsupported.','Finite surface sampling is not a continuous Hausdorff certificate.','Geometry agreement does not recover unique original design intent.','IR/STEP regeneration is not native CAD execution.']}
    try:
        validate_ir(ir,observation)
        result['stage']='source_hash'
        if hashlib.sha256(Path(source_step).read_bytes()).hexdigest()!=ir['source']['sha256']:raise ValueError('source_changed_or_mismatched')
        result['stage']='source_provenance'
        verify_source_observation(observation, source_step)
        result['stage']='initial_solve'
        initial=solve(ir); result['initial_solver']=initial
        if initial['status']!='fully_constrained':raise ValueError('initial_solver_'+initial['status'])
        result['stage']='initial_geometry'
        initial_shape=build_shape(to_legacy(ir,initial['values']))
        result['source_geometry']=compare_shapes(kernel.read_step(source_step),initial_shape)
        if result['source_geometry']['status']!='PASS':raise ValueError('source_geometry_mismatch')
        result['stage']='solve'
        solved=initial if edits is None else solve(ir,edits); result['solver']=solved
        dump(out/'solver.json',solved)
        if solved['status']!='fully_constrained':raise ValueError('solver_'+solved['status'])
        result['stage']='lowering'
        plan=to_legacy(ir,solved['values'])
        result['stage']='geometry'
        shape=initial_shape if edits is None else build_shape(plan)
        result['stage']='step_reopen'
        kernel.write_step(shape,out/'result.step')
        reopened=kernel.read_step(out/'result.step')
        result['roundtrip_geometry']=compare_shapes(shape,reopened)
        if result['roundtrip_geometry']['status']!='PASS':raise ValueError('step_roundtrip_failed')
        # Reload the declarative IR AND edit transaction, and actually regenerate.
        dump(out/'model.ir.json',ir);dump(out/'edits.json',edits or {});dump(out/'model.legacy.json',plan)
        stored=json.loads((out/'model.ir.json').read_text())
        stored_edits=json.loads((out/'edits.json').read_text())
        validate_ir(stored,observation)
        rerun=solve(stored,stored_edits)
        if rerun['status']!='fully_constrained':raise ValueError('reload_solver_failure')
        regenerated=build_shape(to_legacy(stored,rerun['values']))
        result['ir_reload_regeneration']=compare_shapes(reopened,regenerated)
        if result['ir_reload_regeneration']['status']!='PASS':raise ValueError('ir_regeneration_failure')
        if hashlib.sha256(Path(source_step).read_bytes()).hexdigest()!=ir['source']['sha256']:raise ValueError('source_changed_during_execution')
        result.update(status='PASS',stage='complete',verification_scope='initial_geometry_and_roundtrip' if edits is None else 'edit_execution_and_roundtrip',candidate_sha256=digest(ir))
    except Exception as exc:
        result['error']={'type':type(exc).__name__,'message':str(exc)[:400]}
    dump(out/'validation.json',result)
    return result


def run_pipeline(source_step, observation, provider, out_dir, max_retries=1):
    if type(max_retries) is not int or not 0<=max_retries<=1:raise ValueError('max_retries_must_be_0_or_1')
    out=Path(out_dir)
    if out.exists():raise ValueError('output_already_exists')
    verify_source_observation(observation, source_step)
    out.mkdir(parents=True)
    request=ai_request(observation)
    dump(out/'observation.json',observation);dump(out/'request.json',request)
    feedback=[];attempts=[];accepted=None;terminal_error=None
    for attempt in range(max_retries+1):
        attempt_dir=out/f'attempt-{attempt}';attempt_dir.mkdir()
        retry_allowed=False
        try:
            candidate=provider.generate(request,feedback,attempt)
        except ProviderError as exc:
            error={'type':'ProviderError','message':exc.code}
            if getattr(exc,'details',None):error['details']=deepcopy(exc.details)
            validation={'status':'FAIL','stage':'provider','error':error}
            retry_allowed=is_retryable_candidate_error(exc.code)
            dump(attempt_dir/'validation.json',validation)
        except Exception:
            # An unexpected transport exception may contain credentials or URLs.
            # Never persist it or send it back to a candidate model.
            validation={'status':'FAIL','stage':'provider','error':{'type':'ProviderError','message':'provider_internal_error'}}
            dump(attempt_dir/'validation.json',validation)
        else:
          try:
            dump(attempt_dir/'candidate.json',candidate)
            validate_ir(candidate,observation)
            expected='rule_proposal' if getattr(provider,'mode',None)=='rule' else 'ai_proposal'
            if candidate.get('proposal',{}).get('kind')!=expected:raise ValueError('provider_proposal_kind_mismatch')
            validation=execute_candidate(candidate,observation,source_step,attempt_dir)
            retry_allowed=validation.get('stage') in ['schema','initial_solve','initial_geometry','solve','lowering','geometry']
          except (ValueError,TypeError,KeyError) as exc:
            validation={'status':'FAIL','stage':'provider_or_candidate','error':{'type':type(exc).__name__,'message':str(exc)[:400]}}
            retry_allowed=True
            dump(attempt_dir/'validation.json',validation)
          except Exception:
            validation={'status':'FAIL','stage':'execution','error':{'type':'ExecutionError','message':'candidate_execution_internal_error'}}
            dump(attempt_dir/'validation.json',validation)
        attempts.append({'attempt':attempt,'validation':validation,'corrective_retry_allowed':retry_allowed})
        if provider.audit:provider.audit[-1]['validation']=deepcopy(validation)
        dump(out/'provider-audit.json',provider.audit)
        if validation['status']=='PASS':accepted=attempt;break
        # Feedback contains only execution/schema errors, never evaluator intent.
        feedback.append({'attempt':attempt,'stage':validation.get('stage'),'error':validation.get('error',{}),'solver_status':validation.get('solver',{}).get('status')})
        # Auth/config, HTTP, transport, refusal and incomplete responses are
        # terminal. Only an actual candidate error receives corrective feedback.
        terminal_error=validation.get('error',{}).get('message','candidate_validation_failed')
        if not retry_allowed:break
    live=getattr(provider,'mode',None)=='live_provider'
    result={'schema_version':'cadbridge.pipeline/1','status':'PASS' if accepted is not None else 'FAIL','accepted_attempt':accepted,'attempt_count':len(attempts),'max_retries':max_retries,'attempts':attempts,'input_sha256':digest(request),'provider_mode':getattr(provider,'mode','unknown'),'native_status':'UNIMPLEMENTED_UNVERIFIED','live_api_validated':bool(live and accepted is not None),
            'live_inference_completed':bool(live and any(entry.get('inference_completed',False) for entry in provider.audit)),
            'external_api_call_count':sum(bool(entry.get('external_api_attempted',False)) for entry in provider.audit),
            'transport_call_count':sum(bool(entry.get('transport_invoked',False)) for entry in provider.audit),
            'automatic_transient_retries':0,'max_provider_attempts':max_retries+1,
            'terminal_error_code':terminal_error if accepted is None else None}
    dump(out/'pipeline.json',result)
    return result
