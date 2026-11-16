"""Known IR -> strict API wire schema; normalization never replaces full validation.

Structured Outputs requires closed objects and all keys required. The IR has
kind-dependent parameter maps and optional constraint.value. We encode only
those known maps as closed nullable slots and remove only those explicit nulls.
Numeric/string bounds remain enforced by IR_SCHEMA and validate_ir locally.
No generic unknown-schema rewriting or automatic JSON-mode fallback exists.
"""
from __future__ import annotations
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from .ir import IR_SCHEMA, FRAME, validate_ir, IRValidationError


class WireSchemaError(ValueError):
    def __init__(self, code, details=None):
        self.code = code
        self.details = details or {}
        super().__init__(code)


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def _nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def wire_schema(full_schema=None):
    """Return the documented supported basic subset for this exact IR version."""
    schema = IR_SCHEMA if full_schema is None else full_schema
    if schema != IR_SCHEMA:
        raise WireSchemaError('unsupported_ir_schema')

    def lower(node):
        if 'const' in node:
            value = node['const']
            if isinstance(value, str):
                return {'type': 'string', 'enum': [value]}
            if value == FRAME:
                return _object({key: {'type': 'array', 'items': {'type': 'number'}} for key in FRAME})
            raise WireSchemaError('unsupported_ir_schema')
        if 'enum' in node:
            return {'type': 'string', 'enum': list(node['enum'])}
        kind = node.get('type')
        if kind == 'object':
            props = node.get('properties')
            if not isinstance(props, dict):
                raise WireSchemaError('unsupported_ir_schema')
            required = node.get('required', [])
            return _object({key: lower(value) if key in required else _nullable(lower(value))
                            for key, value in props.items()})
        if kind == 'array':
            return {'type': 'array', 'items': lower(node['items'])}
        if kind in {'string', 'number', 'integer', 'boolean'}:
            return {'type': kind}
        raise WireSchemaError('unsupported_ir_schema')

    source = deepcopy(schema)
    entity = source['properties']['sketches']['items']['properties']['entities']['items']
    entity['properties']['parameters'] = _object({key: {'type': 'string'} for key in ['cx', 'cy', 'length', 'width', 'diameter']})
    entity['properties']['parameters']['required'] = ['cx', 'cy']
    feature = source['properties']['features']['items']
    feature['properties']['parameters'] = _object({key: {'type': 'string'} for key in ['z', 'thickness', 'depth']})
    feature['properties']['parameters']['required'] = []
    result = lower(source)
    Draft202012Validator.check_schema(result)
    return result


def normalize_wire_candidate(candidate, observation=None):
    """Require the wire shape before removing only declared optional null slots."""
    errors = list(Draft202012Validator(wire_schema()).iter_errors(candidate))
    if errors:
        err = errors[0]
        # No data values or arbitrary unknown keys are copied into feedback.
        known = {'schema_version','units','frame','origin','x_axis','y_axis','z_axis',
                 'source','kind','sha256','observation_sha256','proposal','approval',
                 'parameters','value','id','evidence','sketches','plane','entities',
                 'features','operation','sketch','entity','depends_on','constraints',
                 'type','refs','provenance','execution_order','rationale',
                 'cx','cy','length','width','diameter','z','thickness','depth'}
        path = [part if isinstance(part, int) or part in known else '*' for part in err.path]
        raise WireSchemaError('wire_schema_violation', {'path': path, 'validator': err.validator})
    result = deepcopy(candidate)
    for sketch in result['sketches']:
        for entity in sketch['entities']:
            entity['parameters'] = {key: value for key, value in entity['parameters'].items() if value is not None}
    for feature in result['features']:
        feature['parameters'] = {key: value for key, value in feature['parameters'].items() if value is not None}
    for constraint in result['constraints']:
        if constraint['value'] is None:
            del constraint['value']
    try:
        validate_ir(result, observation)
    except (IRValidationError, ValueError, TypeError, KeyError) as exc:
        code = str(exc) if re.fullmatch(r'[a-z_]{1,100}', str(exc)) else 'ir_schema_violation'
        raise WireSchemaError('candidate_ir_validation_failed', {'validation_code': code}) from None
    return result


def to_wire_candidate(candidate):
    """Fixture/test utility: explicit inverse mapping, followed by wire validation."""
    validate_ir(candidate)
    result = deepcopy(candidate)
    for sketch in result['sketches']:
        for entity in sketch['entities']:
            for key in ['cx', 'cy', 'length', 'width', 'diameter']:
                entity['parameters'].setdefault(key, None)
    for feature in result['features']:
        for key in ['z', 'thickness', 'depth']:
            feature['parameters'].setdefault(key, None)
    for constraint in result['constraints']:
        constraint.setdefault('value', None)
    if list(Draft202012Validator(wire_schema()).iter_errors(result)):
        raise WireSchemaError('wire_schema_violation')
    return result
