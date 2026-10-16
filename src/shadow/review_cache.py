"""Versioned JSON analysis cache. No executable objects are deserialized."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import fields, is_dataclass
from pathlib import Path

import numpy as np

from . import config

log = logging.getLogger(__name__)


def _encode(value):
    if is_dataclass(value):
        return {'type': type(value).__name__, 'fields': {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, np.ndarray):
        return {'type': 'array', 'values': value.tolist()}
    if isinstance(value, Path):
        return {'type': 'path', 'value': str(value)}
    if isinstance(value, (tuple, frozenset)):
        return {'type': type(value).__name__, 'values': [_encode(item) for item in value]}
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, np.generic):
        return value.item()
    return value


def _decode(value):
    from .models import Word
    from .analysis.diff import DiffToken
    from .analysis.prosody import Prosody
    from .analysis.rhythm import PauseGap, Rhythm
    from .report.advice import Advice
    from .review import Take
    types = {cls.__name__: cls for cls in (Word, DiffToken, Prosody, PauseGap, Rhythm, Advice, Take)}
    if not isinstance(value, dict):
        return value
    tag = value.get('type')
    if tag == 'array':
        return np.asarray(value['values'], dtype=float)
    if tag == 'path':
        return Path(value['value'])
    if tag in ('tuple', 'frozenset'):
        return (tuple if tag == 'tuple' else frozenset)(_decode(item) for item in value['values'])
    if tag in types:
        return types[tag](**{key: _decode(item) for key, item in value['fields'].items()})
    return {key: _decode(item) for key, item in value.items()}


class AnalysisCache:
    def __init__(self, directory: Path):
        self.directory = directory
        # Content-based invalidation covers analysis rules, model and cache schema.
        root = Path(__file__).parent
        digest = hashlib.sha256(b'shadow-analysis-cache-v1')
        for name in ('review.py', 'review_cache.py', 'config.py', 'models.py', 'text.py',
                     'analysis/align.py', 'analysis/diff.py', 'analysis/prosody.py',
                     'analysis/rhythm.py', 'ingest/transcriber.py',
                     'report/advice.py', 'report/takes.py'):
            digest.update((root / name).read_bytes())
        digest.update(repr((config.WHISPER_MODEL, config.WHISPER_LANGUAGE)).encode())
        self.version = digest.hexdigest()

    def key(self, path: Path, context: str = '') -> str:
        digest = hashlib.sha256((self.version + context + str(path.resolve())).encode())
        with path.open('rb') as source:
            for block in iter(lambda: source.read(65536), b''):
                digest.update(block)
        return digest.hexdigest()

    def get(self, key):
        try:
            return _decode(json.loads((self.directory / f'{key}.json').read_text()))
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def put(self, key, value):
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, delete=False) as target:
                temporary = target.name
                json.dump(_encode(value), target, ensure_ascii=False)
            os.replace(temporary, self.directory / f'{key}.json')
        except (OSError, TypeError, ValueError):
            log.warning('Analysis cache write failed; analysis result remains usable', exc_info=True)
        finally:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass
