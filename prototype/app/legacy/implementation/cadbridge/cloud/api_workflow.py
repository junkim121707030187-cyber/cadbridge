"""Bounded external-API orchestration with explicit crash/retry checkpoints.

No credentials are stored here. A generation intent is durably recorded before
calling a provider. Resume never generates: an uncertain/failed API outcome
requires the explicit retry_generation request, which may incur a new call.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import uuid

from .providers import OpenAIProvider, ProviderError, configuration_status
from .workspace import Workspace, init_workspace, _atomic_json, _json, _sha
from .observations import digest

STATE_VERSION = 'cadbridge.api-workflow/1'
STATE_FILE = 'api-workflow.json'
_EXPORT_FILES = {'input.step', 'observation.json', 'result.step', 'model.ir.json',
                 'edits.json', 'model.legacy.json', 'solver.json', 'validation.json', 'target.json'}

_HELP = {
    'authentication_not_configured': '승인된 실행 환경의 OPENAI_API_KEY 또는 OPENAI_API_KEY_FILE에 비밀을 주입하세요. 채팅·CLI 인수·일반 JSON에 키를 넣지 마세요.',
    'model_not_configured': '비밀이 아닌 config의 model 또는 CADBRIDGE_LLM_MODEL을 지정하세요.',
    'authentication_rejected': '현재 인증이 거부되었습니다. 승인된 비밀 저장소의 인증과 계정 상태를 확인한 뒤 명시적으로 재시도하세요.',
    'permission_denied': '설정한 계정·프로젝트·모델에 대한 API 권한을 확인하세요.',
    'model_or_endpoint_not_found': 'config의 model과 api가 제공자에서 지원되는 조합인지 확인하세요.',
    'rate_limit_or_quota': '제공자 한도·할당량을 확인하세요. 자동 재시도하지 않습니다.',
    'provider_unavailable': '제공자가 일시적으로 응답하지 않습니다. 자동 재시도하지 않습니다.',
    'transport_error': '승인된 네트워크·프록시·CA 설정을 확인하세요. TLS 검증을 해제하지 마세요.',
    'ca_configuration_error': '승인된 CA 파일과 기존 TLS 설정을 확인하세요.',
    'output_already_exists': '새 출력 폴더를 지정하세요. 완료한 동일 출력의 재확인은 --resume을 사용하세요.',
    'project_exists_use_resume_or_retry_generation': '검증된 후보가 있으면 --resume, 생성 실패·결과 불명 상태이면 --retry-generation을 명시하세요.',
    'generation_outcome_unknown_or_failed': '자동 API 재호출은 차단되었습니다. 기록을 확인한 뒤 새 호출을 원할 때만 --retry-generation을 명시하세요.',
    'accepted_candidate_already_exists_use_resume': '기존 후보를 보존했습니다. 새 호출 없이 --resume으로 진행하세요.',
    'resume_edits_differ': '재개는 저장된 편집을 사용합니다. 편집 실패를 수정하려면 --resume --replace-edits --edits 수정파일을 사용하세요. 완료 후에는 workspace edit로 새 편집을 적용할 수 있습니다.',
    'api_candidate_selection_changed': '활성 후보가 API 실행 기록과 다릅니다. 프로젝트를 확인하세요. 자동 선택 변경을 하지 않습니다.',
    'api_active_edits_changed': '저장된 편집이 실행 계획과 다릅니다. workspace status로 변경 내용을 확인하세요.',
    'candidate_missing_or_changed': '후보 또는 실행 증거가 변경되었습니다. 원본 프로젝트 백업으로 복원하세요.',
    'export_changed': '기존 내보내기 증거가 변경되었습니다. 새 출력 폴더를 지정해 --resume 하세요.',
    'workspace_busy': '다른 프로젝트 작업이 끝난 뒤 같은 명령을 다시 실행하세요.',
    'api_workflow_busy': '다른 API 작업이 실행 중입니다. 완료 뒤 --resume을 사용하세요.',
}


def _help(code):
    if code in _HELP:
        return _HELP[code]
    if any(word in code for word in ('config', 'model', 'secret', 'credential', 'key_file', 'authentication')):
        return '비밀 설정과 비밀이 아닌 API config의 형식을 확인하세요. 값이나 키를 채팅·로그에 출력하지 마세요.'
    return '저장된 단계와 실행 기록을 확인하세요. 지원 형상·편집 범위 및 설치 상태는 API 사용 안내를 참조하세요.'


def preflight(config_path=None):
    """Local-only checks; PASS is configuration readiness, never an API result."""
    try:
        config = configuration_status(config_path=config_path)
        errors = config.get('errors', [])
        ready = config.get('status') == 'configured_unverified' and not errors
        return {'schema_version': 'cadbridge.api-preflight/1', 'status': 'PASS' if ready else 'BLOCKED',
                'provider': config, 'network_attempted': False, 'api_call_count': 0,
                'live_inference_completed': False, 'live_api_validated': False,
                'guidance': [{'code': code, 'action': _help(code)} for code in errors],
                'native_status': 'POSTPONED_UNIMPLEMENTED_UNVERIFIED'}
    except Exception:
        return {'schema_version': 'cadbridge.api-preflight/1', 'status': 'BLOCKED',
                'error': {'code': 'preflight_configuration_error', 'action': _help('config')},
                'network_attempted': False, 'api_call_count': 0,
                'live_inference_completed': False, 'live_api_validated': False,
                'native_status': 'POSTPONED_UNIMPLEMENTED_UNVERIFIED'}


class WorkflowError(ValueError):
    def __init__(self, code, *, blocked=False):
        self.code, self.blocked = code, blocked
        super().__init__(code)


@contextmanager
def _api_lock(workspace):
    path = workspace._path('.api-workflow.lock')
    with path.open('a+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                if path.stat().st_size == 0:
                    stream.write(b'0'); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise WorkflowError('api_workflow_busy', blocked=True) from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _save(workspace, state):
    _atomic_json(workspace._path(STATE_FILE), state)


def _load_state(workspace):
    try:
        state = _json(workspace._path(STATE_FILE))
    except (ValueError, OSError):
        raise WorkflowError('api_workflow_checkpoint_required', blocked=True) from None
    if (state.get('schema_version') != STATE_VERSION or
            not isinstance(state.get('requested_edits'), dict) or
            not isinstance(state.get('generations'), list) or
            not isinstance(state.get('candidate_name'), str) or
            not isinstance(state.get('source_sha256'), str)):
        raise WorkflowError('invalid_api_workflow_checkpoint')
    return state


def _checked_edits(edits):
    if edits is None:
        return None
    if not isinstance(edits, dict) or len(edits) > 800:
        raise WorkflowError('invalid_edit_transaction')
    for key, value in edits.items():
        if (not isinstance(key, str) or not key or len(key) > 64 or
                isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or abs(value) > 10000):
            raise WorkflowError('invalid_edit_transaction')
    return deepcopy(edits)


def _candidate_evidence(workspace, state):
    # Public status re-checks all source/candidate/audit/revision hashes.
    status = workspace.status()
    matches = [c for c in status['candidates'] if c['id'] == state['candidate_name']]
    if not matches:
        return status, None
    candidate = matches[0]
    expected = state.get('candidate_sha256')
    if expected is not None and expected != candidate['candidate_sha256']:
        raise WorkflowError('candidate_missing_or_changed')
    if candidate['origin_mode'] not in ('live_provider', 'mock_transport'):
        raise WorkflowError('api_candidate_origin_mismatch')
    return status, candidate


def _export_intact(path, state):
    """Only accept an already-completed export checkpoint with unchanged files."""
    expected = state.get('export')
    if not isinstance(expected, dict) or expected.get('path') != str(path):
        raise WorkflowError('output_already_exists')
    if path.is_symlink() or not path.is_dir():
        raise WorkflowError('export_changed')
    manifest_path = path / 'export.json'
    if manifest_path.is_symlink() or _sha(manifest_path) != expected.get('manifest_sha256'):
        raise WorkflowError('export_changed')
    manifest = _json(manifest_path)
    if (manifest.get('status') != 'PASS' or set(manifest.get('files', {})) != _EXPORT_FILES or
            manifest.get('candidate_sha256') != state['candidate_sha256'] or
            manifest.get('source_sha256') != state['source_sha256'] or
            manifest.get('provider_mode') != state['provider_mode'] or
            manifest.get('live_api_validated') != state['live_api_validated'] or
            manifest.get('edits') != state['requested_edits']):
        raise WorkflowError('export_changed')
    for filename, expected_hash in manifest['files'].items():
        artifact = path / filename
        if artifact.is_symlink() or _sha(artifact) != expected_hash:
            raise WorkflowError('export_changed')
    return {'status': 'PASS', 'out': str(path), 'already_exported': True}


def _summarize(workspace, state, *, calls_this_command=0, provider_attempts=0, transport_calls=0, external_calls=0, resumed=False):
    mode = state.get('provider_mode')
    return {'schema_version': STATE_VERSION, 'status': 'PASS', 'stage': state['stage'],
            'project': str(workspace.path), 'candidate': state['candidate_name'],
            'candidate_sha256': state['candidate_sha256'], 'provider_mode': mode,
            'generation_skipped': resumed, 'api_call_count_this_command': calls_this_command,
            'provider_attempt_count_this_command': provider_attempts,
            'transport_call_count_this_command': transport_calls,
            'external_api_call_count_this_command': external_calls,
            'max_api_calls_per_generation': state.get('max_api_calls_per_generation', 2),
            'automatic_transient_retries': 0,
            'live_inference_completed': mode == 'live_provider' and state.get('live_api_validated', False),
            'live_api_validated': bool(mode == 'live_provider' and state.get('live_api_validated', False)),
            'workflow_validation': 'PASS', 'edit_task_verification': 'UNVERIFIED',
            'native_status': 'POSTPONED_UNIMPLEMENTED_UNVERIFIED',
            'out': state['export']['path'], 'edits': state['requested_edits']}


def run_api(source, project, output, *, config_path=None, edits=None,
            max_retries=1, resume=False, retry_generation=False, replace_edits=False):
    """Run or resume one bounded workflow; live credentials remain provider-owned."""
    workspace = None
    state = None
    calls = 0
    provider_attempts = 0
    transport_calls = 0
    external_calls = 0
    verified_live = False
    observed_live_inference = False
    stage = 'preflight'
    try:
        if type(max_retries) is not int or max_retries not in (0, 1):
            raise WorkflowError('max_retries_must_be_0_or_1')
        if resume and retry_generation:
            raise WorkflowError('resume_and_retry_generation_are_exclusive')
        edits = _checked_edits(edits)
        if replace_edits and (not resume or edits is None):
            raise WorkflowError('replace_edits_requires_resume_and_edits')
        source = Path(source).resolve()
        project = Path(project).absolute()
        output = Path(output).absolute()
        if output.resolve().is_relative_to(project.resolve()) or project.resolve().is_relative_to(output.resolve()):
            raise WorkflowError('output_must_be_separate_from_project')
        if not source.is_file():
            raise WorkflowError('source_file_required')
        source_hash = _sha(source)
        exists = project.exists()
        if exists and not (resume or retry_generation):
            raise WorkflowError('project_exists_use_resume_or_retry_generation', blocked=True)
        if not exists and (resume or retry_generation):
            raise WorkflowError('resume_project_missing', blocked=True)
        if output.exists() and not resume:
            raise WorkflowError('output_already_exists')
        if not exists:
            check = preflight(config_path)
            if check['status'] != 'PASS':
                check.update(stage='preflight', workflow_validation='NOT_RUN')
                return check
            stage = 'initialize'
            init_workspace(source, project)
        workspace = Workspace(project)
        with _api_lock(workspace):
            stage = 'checkpoint'
            if exists:
                state = _load_state(workspace)
                if state['source_sha256'] != source_hash:
                    raise WorkflowError('source_changed_or_mismatched')
                if edits is not None and edits != state['requested_edits'] and not replace_edits:
                    raise WorkflowError('resume_edits_differ')
            else:
                state = {'schema_version': STATE_VERSION, 'stage': 'initialized',
                         'source_sha256': source_hash, 'requested_edits': edits or {},
                         'candidate_name': 'api-' + uuid.uuid4().hex[:12],
                         'candidate_sha256': None, 'generations': [],
                         'max_api_calls_per_generation': max_retries + 1,
                         'live_api_validated': False, 'provider_mode': None}
                _save(workspace, state)
            status, candidate = _candidate_evidence(workspace, state)
            if status['source_sha256'] != source_hash:
                raise WorkflowError('source_changed_or_mismatched')
            if retry_generation and candidate is not None:
                raise WorkflowError('accepted_candidate_already_exists_use_resume', blocked=True)
            if resume and candidate is None:
                raise WorkflowError('generation_outcome_unknown_or_failed', blocked=True)
            if replace_edits:
                if status['edits']:
                    raise WorkflowError('replace_edits_requires_unedited_candidate_use_workspace')
                state['requested_edits'] = edits
                state.pop('export', None)
                _save(workspace, state)
            if candidate is None:
                # A new command must explicitly acknowledge repeating an uncertain
                # or failed call. Automatic retry is only within this one budget.
                if exists and not retry_generation:
                    raise WorkflowError('generation_outcome_unknown_or_failed', blocked=True)
                check = preflight(config_path)
                if check['status'] != 'PASS':
                    check.update(stage='preflight', workflow_validation='NOT_RUN')
                    return check
                provider = OpenAIProvider.from_env(config_path=config_path)
                if retry_generation:
                    state['candidate_name'] = 'api-' + uuid.uuid4().hex[:12]
                generation = {'candidate_name': state['candidate_name'], 'status': 'intent_saved',
                              'max_calls': max_retries + 1, 'outcome_known': False}
                state['generations'].append(generation)
                state.update(stage='generation_intent_saved', max_api_calls_per_generation=max_retries + 1)
                _save(workspace, state)
                stage = 'generate'
                try:
                    proposal = workspace.propose(state['candidate_name'], provider, max_retries)
                finally:
                    provider_attempts = len(provider.audit)
                    calls = sum(bool(entry.get('network_attempted', False)) for entry in provider.audit)
                    transport_calls = sum(bool(entry.get('transport_invoked', False)) for entry in provider.audit)
                    external_calls = sum(bool(entry.get('external_api_attempted', False)) for entry in provider.audit)
                    observed_live_inference = bool(provider.mode == 'live_provider' and any(entry.get('inference_completed', False) for entry in provider.audit))
                generation.update(status=proposal['status'], outcome_known=True,
                                  provider_mode=proposal['provider_mode'], provider_attempt_count=provider_attempts,
                                  network_attempt_count=calls, transport_call_count=transport_calls,
                                  external_api_call_count=external_calls,
                                  run=proposal['run'])
                state['provider_mode'] = proposal['provider_mode']
                state['live_inference_completed'] = observed_live_inference
                state['stage'] = 'generation_accepted' if proposal['status'] == 'PASS' else 'generation_failed'
                _save(workspace, state)
                if proposal['status'] != 'PASS':
                    pipeline = _json(Path(proposal['run']) / 'pipeline.json')
                    code = pipeline.get('terminal_error_code') or 'candidate_generation_failed'
                    raise WorkflowError(code)
                status, candidate = _candidate_evidence(workspace, state)
            if candidate is None:
                raise WorkflowError('candidate_missing_or_changed')
            verified_live = bool(candidate['origin_mode'] == 'live_provider' and candidate['live_api_validated'])
            observed_live_inference = observed_live_inference or verified_live
            state.update(candidate_sha256=candidate['candidate_sha256'], provider_mode=candidate['origin_mode'],
                         live_api_validated=verified_live, live_inference_completed=observed_live_inference)
            _save(workspace, state)
            stage = 'select'
            selected = status['selected_candidate']
            if selected is not None and selected != state['candidate_name']:
                raise WorkflowError('api_candidate_selection_changed')
            if selected is None:
                result = workspace.select(state['candidate_name'])
                if result['status'] != 'PASS':
                    raise WorkflowError('candidate_selection_failed')
            status = workspace.status()
            if status['edits'] not in ({}, state['requested_edits']):
                raise WorkflowError('api_active_edits_changed')
            state['stage'] = 'selected'; _save(workspace, state)
            stage = 'edit'
            if state['requested_edits'] and status['edits'] != state['requested_edits']:
                result = workspace.edit(state['requested_edits'])
                if result['status'] != 'PASS':
                    state['stage'] = 'edit_failed'; _save(workspace, state)
                    raise WorkflowError('edit_validation_failed')
            state['stage'] = 'edited'; _save(workspace, state)
            stage = 'verify'
            if workspace.verify()['status'] != 'PASS':
                raise WorkflowError('workflow_verification_failed')
            state['stage'] = 'verified'; _save(workspace, state)
            stage = 'export'
            if output.exists():
                _export_intact(output, state)
            else:
                result = workspace.export(output)
                if result['status'] != 'PASS':
                    raise WorkflowError('export_validation_failed')
                state['export'] = {'path': str(output), 'manifest_sha256': _sha(output / 'export.json')}
                # The general workspace also permits ordinary local edits. An
                # interleaving command must not silently change this API plan.
                # Preserve the mismatching output as evidence; never undo another
                # command's state or report this API workflow as successful.
                _export_intact(output, state)
            state['stage'] = 'complete'; _save(workspace, state)
            return _summarize(workspace, state, calls_this_command=calls, provider_attempts=provider_attempts,
                              transport_calls=transport_calls, external_calls=external_calls, resumed=resume)
    except Exception as exc:
        # Never surface arbitrary transport/OS/config exceptions or their paths.
        code = exc.code if isinstance(exc, (WorkflowError, ProviderError)) else 'api_workflow_error'
        result = {'schema_version': STATE_VERSION,
                  'status': 'BLOCKED' if isinstance(exc, WorkflowError) and exc.blocked else 'FAIL',
                  'stage': stage, 'error': {'code': code, 'action': _help(code)},
                  'api_call_count_this_command': calls, 'automatic_transient_retries': 0,
                  'provider_attempt_count_this_command': provider_attempts,
                  'transport_call_count_this_command': transport_calls,
                  'external_api_call_count_this_command': external_calls,
                  'workflow_validation': 'NOT_COMPLETED',
                  'live_inference_completed': observed_live_inference,
                  'live_api_validated': verified_live,
                  'native_status': 'POSTPONED_UNIMPLEMENTED_UNVERIFIED'}
        return result
