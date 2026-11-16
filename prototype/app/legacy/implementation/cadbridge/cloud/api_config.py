"""Bounded nonsecret API settings and private credential-file loading.

No error includes configuration contents or file paths. Caller never persists
returned credentials. Transport, endpoint, proxy and CA cannot be overridden by
this configuration file.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
import stat
from collections.abc import Mapping


class ConfigError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


DEFAULTS = {'api': 'responses', 'response_format': 'json_schema', 'timeout': 45,
            'max_output_tokens': 8192, 'reasoning_effort': None}
ALLOWED = {'model', *DEFAULTS}
EFFORTS = {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}
MODEL_PATTERN = r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}'


def read_bounded_file(path, *, secret=False):
    limit = 8192 if secret else 16384
    prefix = 'credential_file' if secret else 'api_config_file'
    fd = None
    try:
        path = Path(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise ConfigError(prefix + '_not_regular')
        if before.st_size > limit:
            raise ConfigError(prefix + '_too_large')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(path, flags)
        current = os.fstat(fd)
        if not stat.S_ISREG(current.st_mode) or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise ConfigError(prefix + '_changed')
        if secret and os.name == 'posix':
            if stat.S_IMODE(current.st_mode) != 0o600 or current.st_uid != os.getuid():
                raise ConfigError('credential_file_permissions')
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if len(raw) > limit:
            raise ConfigError(prefix + '_too_large')
        if (current.st_size, current.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(raw) != after.st_size:
            raise ConfigError(prefix + '_changed')
        return raw
    except ConfigError:
        raise
    except (OSError, TypeError, ValueError):
        raise ConfigError(prefix + '_unreadable') from None
    finally:
        if fd is not None:
            os.close(fd)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ConfigError('invalid_api_config_json')
        result[key] = value
    return result


def validate_options(options):
    if not isinstance(options, dict) or not set(options) <= ALLOWED:
        raise ConfigError('unknown_api_config_field')
    model = options.get('model')
    if model is not None and (not isinstance(model, str) or not re.fullmatch(MODEL_PATTERN, model)):
        raise ConfigError('invalid_model_configuration')
    if not isinstance(options.get('api'), str) or options['api'] not in {'responses', 'chat_completions'}:
        raise ConfigError('invalid_api_configuration')
    if not isinstance(options.get('response_format'), str) or options['response_format'] not in {'json_schema', 'json_object'}:
        raise ConfigError('invalid_response_format')
    timeout = options.get('timeout')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ConfigError('invalid_timeout')
    tokens = options.get('max_output_tokens')
    if isinstance(tokens, bool) or not isinstance(tokens, int) or not 1 <= tokens <= 16384:
        raise ConfigError('invalid_token_limit')
    effort = options.get('reasoning_effort')
    if effort is not None and (not isinstance(effort, str) or effort not in EFFORTS):
        raise ConfigError('invalid_reasoning_effort')
    return options


def load_options(environ: Mapping | None = None, *, config_path=None, overrides=None):
    env = os.environ if environ is None else environ
    path = config_path if config_path is not None else env.get('CADBRIDGE_API_CONFIG')
    options = dict(DEFAULTS)
    if path is not None and path != '':
        try:
            value = json.loads(read_bounded_file(path).decode('utf-8'), object_pairs_hook=_pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ConfigError('invalid_api_config_json')))
        except ConfigError:
            raise
        except (ValueError, UnicodeError, RecursionError):
            raise ConfigError('invalid_api_config_json') from None
        if not isinstance(value, dict) or not set(value) <= ALLOWED:
            raise ConfigError('unknown_api_config_field')
        options.update(value)
    if env.get('CADBRIDGE_LLM_MODEL') is not None:
        options['model'] = env.get('CADBRIDGE_LLM_MODEL')
    if overrides:
        options.update(overrides)
    return validate_options(options)


def load_credential(environ: Mapping | None = None):
    env = os.environ if environ is None else environ
    key, path = env.get('OPENAI_API_KEY'), env.get('OPENAI_API_KEY_FILE')
    if key and path:
        raise ConfigError('conflicting_authentication_sources')
    if path:
        try:
            key = read_bounded_file(path, secret=True).decode('ascii')
        except UnicodeError:
            raise ConfigError('invalid_authentication_configuration') from None
        # A secret file may end in one conventional line terminator.
        if key.endswith('\r\n'):
            key = key[:-2]
        elif key.endswith('\n'):
            key = key[:-1]
    return key
