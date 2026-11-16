"""Persistent local STEP reconstruction projects with auditable, atomic state.

The original STEP and IR remain immutable observations. Cumulative dimension
edits are separate transactions. A failed operation never replaces active state.
This is a single-user local project format, not a signed provenance authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from .adapters import read_input, require_target
from .ir import validate_ir
from .observations import ai_request, digest, validate_observation
from .pipeline import dump, run_pipeline
from .providers import strict_json_object
from .solver import solve

VERSION = 'cadbridge.workspace/1'
_ID = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
_RUN = re.compile(r'^[0-9a-f]{32}$')


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _json(path):
    path = Path(path)
    if path.stat().st_size > 8_388_608:
        raise ValueError('workspace_json_size_limit')
    return strict_json_object(path.read_bytes())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path, value):
    """fsync before replacement; readers see either the old or the new manifest."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.manifest-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def init_workspace(source, project):
    source, project = Path(source).resolve(), Path(project).absolute()
    if project.exists():
        raise ValueError('workspace_already_exists')
    # Retain the input reader boundary: renaming a native file does not add support.
    if source.suffix.lower() not in {'.step', '.stp'}:
        raise ValueError('unsupported_input_format:' + source.suffix.lstrip('.'))
    if not source.is_file():
        raise ValueError('source_file_required')
    original_hash = _sha(source)
    project.parent.mkdir(parents=True, exist_ok=True)
    project.mkdir()  # exclusive creation; never replace a pre-existing project
    try:
        (project / 'source').mkdir()
        (project / 'runs').mkdir()
        copied = project / 'source/input.step'
        shutil.copyfile(source, copied)
        if _sha(copied) != original_hash or _sha(source) != original_hash:
            raise ValueError('source_changed_during_import')
        observation = read_input(copied)
        dump(project / 'observation.json', observation)
        dump(project / 'request.json', ai_request(observation))
        manifest = {'schema_version': VERSION, 'created_at': _now(),
                    'source_sha256': original_hash,
                    'observation_sha256': _sha(project / 'observation.json'),
                    'request_sha256': _sha(project / 'request.json'),
                    'candidates': {}, 'selected_candidate': None,
                    'active_revision': None, 'edits': {}, 'operations': [],
                    'native_status': 'UNIMPLEMENTED_UNVERIFIED'}
        _atomic_json(project / 'workspace.json', manifest)
    except BaseException:
        shutil.rmtree(project)
        raise
    return {'status': 'PASS', 'project': str(project.resolve()),
            'source_sha256': original_hash, 'next': 'workspace propose'}


class Workspace:
    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)
        if not self.path.is_dir():
            raise ValueError('workspace_directory_required')

    def _path(self, relative):
        """Never follow artifact symlinks or manifest-provided path traversal."""
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe_workspace_path')
        current = self.path
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('workspace_symlink_rejected')
        return current

    @contextmanager
    def _locked(self):
        lock = self._path('.workspace.lock')
        with lock.open('a+b') as stream:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if lock.stat().st_size == 0:
                        stream.write(b'0'); stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                raise ValueError('workspace_busy') from None
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read(self):
        manifest = _json(self._path('workspace.json'))
        if manifest.get('schema_version') != VERSION:
            raise ValueError('unsupported_workspace_version')
        for key, filename in [('source_sha256', 'source/input.step'),
                              ('observation_sha256', 'observation.json'),
                              ('request_sha256', 'request.json')]:
            if manifest.get(key) != _sha(self._path(filename)):
                raise ValueError('workspace_integrity_failure:' + filename)
        if not isinstance(manifest.get('candidates'), dict) or not isinstance(manifest.get('operations'), list) or not isinstance(manifest.get('edits'), dict):
            raise ValueError('invalid_workspace_manifest')
        observation = _json(self._path('observation.json'))
        validate_observation(observation)
        if observation['source']['sha256'] != manifest['source_sha256']:
            raise ValueError('workspace_source_observation_mismatch')
        if _json(self._path('request.json')) != ai_request(observation):
            raise ValueError('workspace_request_observation_mismatch')
        return manifest, observation

    def _write_manifest(self, manifest):
        _atomic_json(self._path('workspace.json'), manifest)

    def _run_path(self, identifier):
        if not isinstance(identifier, str) or not _RUN.fullmatch(identifier):
            raise ValueError('invalid_workspace_run_id')
        return self._path('runs/' + identifier)

    def _candidate(self, manifest, identifier=None):
        identifier = identifier or manifest.get('selected_candidate')
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier not in manifest['candidates']:
            raise ValueError('candidate_not_found_or_not_selected')
        record = manifest['candidates'][identifier]
        if not isinstance(record, dict):
            raise ValueError('invalid_candidate_record')
        attempt = record.get('accepted_attempt')
        if type(attempt) is not int or attempt not in (0, 1):
            raise ValueError('invalid_candidate_attempt')
        folder = self._run_path(record['run']) / ('attempt-' + str(attempt))
        candidate_path = self._path(folder.relative_to(self.path) / 'candidate.json')
        candidate = _json(candidate_path)
        if digest(candidate) != record.get('candidate_sha256'):
            raise ValueError('workspace_candidate_integrity_failure')
        run = self._run_path(record['run'])
        for key, filename in [('pipeline_sha256', 'pipeline.json'), ('audit_sha256', 'provider-audit.json')]:
            if _sha(self._path(run.relative_to(self.path) / filename)) != record.get(key):
                raise ValueError('workspace_candidate_evidence_integrity_failure')
        report = _json(run / 'pipeline.json')
        if report.get('status') != 'PASS' or report.get('accepted_attempt') != attempt or report.get('provider_mode') != record.get('origin_mode') or report.get('live_api_validated') != record.get('live_api_validated'):
            raise ValueError('workspace_candidate_evidence_mismatch')
        return identifier, candidate, record

    def _revision(self, manifest):
        record = manifest.get('active_revision')
        if not isinstance(record, dict):
            raise ValueError('candidate_not_selected')
        folder = self._run_path(record['run'])
        files = record.get('files')
        required = {'result.step', 'model.ir.json', 'edits.json', 'model.legacy.json', 'solver.json', 'validation.json', 'target.json'}
        if not isinstance(files, dict) or set(files) != required:
            raise ValueError('invalid_revision_manifest')
        for filename, expected in files.items():
            if expected != _sha(self._path(folder.relative_to(self.path) / filename)):
                raise ValueError('workspace_revision_integrity_failure:' + filename)
        if _json(folder / 'edits.json') != manifest['edits']:
            raise ValueError('workspace_revision_edits_mismatch')
        _, candidate, _ = self._candidate(manifest)
        if _json(folder / 'model.ir.json') != candidate:
            raise ValueError('workspace_revision_candidate_mismatch')
        return folder

    def status(self):
        with self._locked():
            manifest, observation = self._read()
            candidates = []
            for identifier in manifest['candidates']:
                _, candidate, record = self._candidate(manifest, identifier)
                validate_ir(candidate, observation)
                candidates.append({'id': identifier, 'selected': identifier == manifest['selected_candidate'],
                                   'origin_mode': record['origin_mode'],
                                   'live_api_validated': record['live_api_validated'],
                                   'rationale': candidate['rationale'],
                                   'candidate_sha256': record['candidate_sha256']})
            dimensions = []
            if manifest['selected_candidate'] is not None:
                self._revision(manifest)
                _, candidate, _ = self._candidate(manifest)
                solved = solve(candidate, manifest['edits'])
                if solved['status'] != 'fully_constrained':
                    raise ValueError('workspace_active_solver_failure')
                dimensions = [{'id': c['id'], 'type': c['type'], 'refs': c['refs'],
                               'original_value': c['value'],
                               'current_value': (solved['values'][c['refs'][0]] if c['type'] == 'dimension'
                                                 else solved['values'][c['refs'][0]] - solved['values'][c['refs'][1]])}
                              for c in candidate['constraints'] if c['type'] in ('dimension', 'offset')]
            return {'status': 'PASS', 'project': str(self.path), 'source_sha256': manifest['source_sha256'],
                    'selected_candidate': manifest['selected_candidate'], 'edits': manifest['edits'],
                    'active_revision': manifest['active_revision'], 'candidates': candidates,
                    'driving_dimensions': dimensions, 'operation_count': len(manifest['operations']),
                    'native_status': 'UNIMPLEMENTED_UNVERIFIED',
                    'edit_task_verification': 'UNVERIFIED',
                    'provenance_note': 'Local hashes detect accidental changes; session origin is externally attested, not authenticated.'}

    def propose(self, identifier, provider, max_retries=0):
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise ValueError('candidate_id_must_be_lowercase_safe_identifier')
        with self._locked():
            manifest, observation = self._read()
            if identifier in manifest['candidates']:
                raise ValueError('candidate_id_already_exists')
            run_id = uuid.uuid4().hex
            folder = self._run_path(run_id)
            result = run_pipeline(self._path('source/input.step'), observation, provider, folder, max_retries)
            if result['status'] == 'PASS':
                candidate = _json(folder / f"attempt-{result['accepted_attempt']}" / 'candidate.json')
                manifest['candidates'][identifier] = {
                    'run': run_id, 'accepted_attempt': result['accepted_attempt'],
                    'candidate_sha256': digest(candidate), 'origin_mode': result['provider_mode'],
                    'live_api_validated': result['live_api_validated'],
                    'pipeline_sha256': _sha(folder / 'pipeline.json'),
                    'audit_sha256': _sha(folder / 'provider-audit.json')}
            manifest['operations'].append({'operation': 'propose', 'candidate': identifier,
                                           'run': run_id, 'status': result['status'], 'at': _now()})
            self._write_manifest(manifest)
            return {'status': result['status'], 'candidate': identifier, 'run': str(folder),
                    'selected': False, 'provider_mode': result['provider_mode'],
                    'live_api_validated': result['live_api_validated']}

    def _execute(self, manifest, observation, identifier, candidate, edits, operation, previous=None, persist=True):
        run_id = uuid.uuid4().hex
        folder = self._run_path(run_id)
        result = require_target('occt-step').execute(candidate, folder, observation=observation,
                                                    source_step=self._path('source/input.step'), edits=edits)
        if result['status'] == 'PASS' and previous is not None:
            from cadbridge import kernel
            from cadbridge.geometry import compare_shapes
            comparison = compare_shapes(kernel.read_step(previous / 'result.step'), kernel.read_step(folder / 'result.step'))
            result['previous_saved_result_comparison'] = comparison
            if comparison['status'] != 'PASS':
                result.update(status='FAIL', stage='previous_saved_result_comparison')
            dump(folder / 'validation.json', result)
        if result['status'] == 'PASS':
            filenames = ['result.step', 'model.ir.json', 'edits.json', 'model.legacy.json', 'solver.json', 'validation.json', 'target.json']
            manifest.update(selected_candidate=identifier, edits=deepcopy(edits),
                            active_revision={'run': run_id, 'files': {name: _sha(folder / name) for name in filenames}})
        manifest['operations'].append({'operation': operation, 'candidate': identifier,
                                       'run': run_id, 'status': result['status'], 'at': _now()})
        if persist:
            self._write_manifest(manifest)
        return {'status': result['status'], 'run': str(folder), 'selected_candidate': manifest['selected_candidate'],
                'edits': manifest['edits'], 'error': result.get('error'),
                'verification_scope': result.get('verification_scope'),
                'edit_task_verification': 'UNVERIFIED', 'native_status': 'UNIMPLEMENTED_UNVERIFIED'}

    def select(self, identifier):
        with self._locked():
            manifest, observation = self._read()
            identifier, candidate, _ = self._candidate(manifest, identifier)
            # Selecting a DIFFERENT candidate starts its dimensions at observations.
            # Selecting the already active one preserves all accumulated edits.
            edits = manifest['edits'] if identifier == manifest['selected_candidate'] else {}
            if identifier == manifest['selected_candidate']:
                self._revision(manifest)
            return self._execute(manifest, observation, identifier, candidate, edits, 'select')

    def edit(self, changes):
        if not isinstance(changes, dict) or not changes:
            raise ValueError('nonempty_dimension_edits_required')
        with self._locked():
            manifest, observation = self._read()
            self._revision(manifest)
            identifier, candidate, _ = self._candidate(manifest)
            edits = {**manifest['edits'], **changes}
            return self._execute(manifest, observation, identifier, candidate, edits, 'edit')

    def verify(self):
        with self._locked():
            manifest, observation = self._read()
            previous = self._revision(manifest)
            identifier, candidate, _ = self._candidate(manifest)
            return self._execute(manifest, observation, identifier, candidate, manifest['edits'], 'verify', previous)

    def export(self, output):
        """Export the validated current revision plus its explicit origin and edits."""
        output = Path(output).absolute()
        if output.exists():
            raise ValueError('output_already_exists')
        with self._locked():
            manifest, observation = self._read()
            previous = self._revision(manifest)
            identifier, candidate, record = self._candidate(manifest)
            result = self._execute(manifest, observation, identifier, candidate, manifest['edits'], 'export_verify', previous, persist=False)
            if result['status'] != 'PASS':
                return result
            folder = self._revision(manifest)
            output.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive output reservation; if interrupted, export.json is absent.
            output.mkdir()
            try:
                for filename in manifest['active_revision']['files']:
                    shutil.copyfile(folder / filename, output / filename)
                    if _sha(output / filename) != manifest['active_revision']['files'][filename]:
                        raise ValueError('export_integrity_failure:' + filename)
                shutil.copyfile(self._path('source/input.step'), output / 'input.step')
                if _sha(output / 'input.step') != manifest['source_sha256']:
                    raise ValueError('export_integrity_failure:input.step')
                dump(output / 'observation.json', observation)
                if _sha(output / 'observation.json') != manifest['observation_sha256']:
                    raise ValueError('export_integrity_failure:observation.json')
                dump(output / 'export.json', {'schema_version': 'cadbridge.export/1', 'status': 'PASS',
                    'source_sha256': manifest['source_sha256'], 'candidate': identifier,
                    'candidate_sha256': record['candidate_sha256'], 'provider_mode': record['origin_mode'],
                    'live_api_validated': record['live_api_validated'], 'edits': manifest['edits'],
                    'files': {p.name: _sha(p) for p in output.iterdir() if p.is_file()},
                    'native_status': 'UNIMPLEMENTED_UNVERIFIED', 'edit_task_verification': 'UNVERIFIED',
                    'reopen_command': 'cadbridge-cloud edit input.step --ir model.ir.json --edits edits.json --out NEW_DIRECTORY'})
                self._write_manifest(manifest)
            except BaseException:
                shutil.rmtree(output)
                raise
            return {'status': 'PASS', 'out': str(output.resolve()), 'result_step': str((output / 'result.step').resolve()),
                    'selected_candidate': identifier, 'provider_mode': record['origin_mode'],
                    'live_api_validated': record['live_api_validated'], 'native_status': 'UNIMPLEMENTED_UNVERIFIED'}
