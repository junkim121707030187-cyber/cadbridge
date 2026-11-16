"""CLI for cloud IR milestone. Legacy `python -m cadbridge` stays compatible."""
import argparse
import json
from pathlib import Path
from .adapters import read_input,require_target,SUPPORT_MATRIX
from .ir import IR_SCHEMA
from .observations import ai_request
from .providers import OpenAIProvider,SessionCandidateProvider,FixtureProvider,strict_json_object
from .pipeline import run_pipeline,RuleProvider,execute_candidate,dump


def load(path):
    p=Path(path)
    if p.stat().st_size>2_097_152:raise ValueError('JSON_input_size_limit')
    return strict_json_object(p.read_bytes())

def _provider_arguments(parser):
    parser.add_argument('--mode',choices=['rule','session','fixture','openai'],default='rule')
    parser.add_argument('--candidate');parser.add_argument('--record')
    parser.add_argument('--max-retries',type=int,choices=[0,1],default=0)
    parser.add_argument('--config',help='Nonsecret API JSON configuration; API keys belong in the approved environment')

def _provider(args):
    if getattr(args,'config',None) and args.mode!='openai':raise ValueError('api_config_requires_openai_mode')
    if args.mode=='rule':return RuleProvider()
    if args.mode=='openai':return OpenAIProvider.from_env(config_path=getattr(args,'config',None))
    if not args.candidate:raise ValueError('candidate_path_required')
    if args.mode=='fixture':return FixtureProvider([load(args.candidate)])
    if not args.record:raise ValueError('session_candidate_and_record_required')
    return SessionCandidateProvider(load(args.candidate),load(args.record))

def _workspace(args):
    from .workspace import Workspace, init_workspace
    if args.action=='init':return init_workspace(args.input,args.project)
    project=Workspace(args.project)
    if args.action in ('status','list'):return project.status()
    if args.action=='propose':return project.propose(args.name,_provider(args),args.max_retries)
    if args.action=='select':return project.select(args.name)
    if args.action=='edit':return project.edit(load(args.edits))
    if args.action=='verify':return project.verify()
    return project.export(args.out)

def main(argv=None):
    p=argparse.ArgumentParser(prog='cadbridge-cloud')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('capabilities');sub.add_parser('schema')
    doctor=sub.add_parser('doctor');doctor.add_argument('--config')
    obs=sub.add_parser('observe');obs.add_argument('input');obs.add_argument('--out',required=True)
    run=sub.add_parser('reconstruct');run.add_argument('input');run.add_argument('--out',required=True)
    run.add_argument('--mode',choices=['rule','session','fixture','openai'],default='rule')
    run.add_argument('--candidate');run.add_argument('--record');run.add_argument('--max-retries',type=int,choices=[0,1],default=1)
    run.add_argument('--config')
    run.add_argument('--target',default='occt-step')
    edit=sub.add_parser('edit');edit.add_argument('input');edit.add_argument('--ir',required=True);edit.add_argument('--edits',required=True);edit.add_argument('--out',required=True)
    ev=sub.add_parser('evaluate');ev.add_argument('input');ev.add_argument('--ir',required=True);ev.add_argument('--out',required=True)
    work=sub.add_parser('workspace',help='Persistent candidate selection and cumulative dimension editing')
    actions=work.add_subparsers(dest='action',required=True)
    wi=actions.add_parser('init');wi.add_argument('input');wi.add_argument('--project',required=True)
    for action in ('status','list','propose','select','edit','verify','export'):
        command=actions.add_parser(action);command.add_argument('--project',required=True)
        if action=='propose':command.add_argument('--name',required=True);_provider_arguments(command)
        elif action=='select':command.add_argument('--name',required=True)
        elif action=='edit':command.add_argument('--edits',required=True)
        elif action=='export':command.add_argument('--out',required=True)
    api=sub.add_parser('api',help='Bounded external API preflight and resumable complete workflow')
    api_actions=api.add_subparsers(dest='api_action',required=True)
    preflight=api_actions.add_parser('preflight',help='Local configuration checks; no network request')
    preflight.add_argument('--config')
    api_run=api_actions.add_parser('run')
    api_run.add_argument('input');api_run.add_argument('--project',required=True);api_run.add_argument('--out',required=True)
    api_run.add_argument('--config');api_run.add_argument('--edits')
    api_run.add_argument('--replace-edits',action='store_true',help='With --resume, replace failed, unapplied edits without generating again')
    api_run.add_argument('--max-retries',type=int,choices=[0,1],default=1)
    recovery=api_run.add_mutually_exclusive_group()
    recovery.add_argument('--resume',action='store_true',help='Reuse the accepted candidate; never call the API')
    recovery.add_argument('--retry-generation',action='store_true',help='Explicitly authorize a new bounded attempt after failed or uncertain generation')
    args=p.parse_args(argv)
    try:
        if args.command=='capabilities':print(json.dumps(SUPPORT_MATRIX,indent=2));return 0
        if args.command=='schema':print(json.dumps(IR_SCHEMA,indent=2));return 0
        if args.command=='doctor':
            from .providers import configuration_status
            from .adapters import target_status
            print(json.dumps({'status':'PASS','provider':configuration_status(config_path=args.config),'targets':target_status()},ensure_ascii=False))
            return 0
        if args.command=='api':
            from .api_workflow import preflight,run_api
            if args.api_action=='preflight':result=preflight(args.config)
            else:
                try:edits=load(args.edits) if args.edits else None
                except Exception:
                    print(json.dumps({'status':'FAIL','error':{'code':'invalid_edit_file','action':'유효한 UTF-8 JSON 편집 파일을 지정하세요. 비밀값을 넣지 마세요.'}},ensure_ascii=False))
                    return 2
                result=run_api(args.input,args.project,args.out,config_path=args.config,edits=edits,
                               max_retries=args.max_retries,resume=args.resume,retry_generation=args.retry_generation,
                               replace_edits=args.replace_edits)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result['status']=='PASS' else 2
        if args.command=='workspace':
            result=_workspace(args)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result['status']=='PASS' else 2
        if Path(args.out).exists():raise ValueError('output_already_exists')
        if args.command=='reconstruct':require_target(args.target)
        observation=read_input(args.input)
        if args.command=='observe':
            Path(args.out).mkdir(parents=True);dump(Path(args.out)/'observation.json',observation);dump(Path(args.out)/'request.json',ai_request(observation));result={'status':'PASS','out':args.out}
        elif args.command=='reconstruct':
            provider=_provider(args)
            result=run_pipeline(args.input,observation,provider,args.out,args.max_retries)
        elif args.command=='edit':result=execute_candidate(load(args.ir),observation,args.input,args.out,load(args.edits))
        else:
            from .evaluation import evaluate_candidate
            result=evaluate_candidate(load(args.ir),observation,args.input,args.out)
        print(json.dumps({'status':result['status'],'execution_status':result.get('execution_status'),'out':str(Path(args.out).resolve()),'live_api_validated':result.get('live_api_validated',False)},ensure_ascii=False))
        return 0 if result['status']=='PASS' else 2
    except (ValueError,OSError,TypeError,KeyError) as exc:
        print(json.dumps({'status':'FAIL','error':str(exc),'native_status':'UNIMPLEMENTED_UNVERIFIED'},ensure_ascii=False))
        return 2
