"""Bounded, strict JSON parsing for the all-channel mediation boundary.

No network, logging, persistence, model conversion or exception stringification.
JSON embedded in prose/fences is parsed too; malformed candidate fragments are
left to residual credential detection, never treated as validated structured data.
"""
from __future__ import annotations

import json
import math
import re

MAX_BYTES = 1048576
MAX_DEPTH = 48
MAX_VALUES = 100000


class BoundaryRefused(ValueError):
    """Static refusal: no payload, path or chained validation exception."""
    code = 'UNSAFE_PAYLOAD'

    def __init__(self):
        super().__init__(self.code)


class Budget:
    def __init__(self):
        self.values = 0

    def visit(self, depth):
        self.values += 1
        if depth > MAX_DEPTH or self.values > MAX_VALUES:
            raise BoundaryRefused()


def bounded_copy_v1(candidate: object, *, budget=None, depth=0):
    """Only exact JSON builtins; reject cycles/depth before encoding or schema walk."""
    budget = budget if budget is not None else Budget()
    def clone(value, level):
        budget.visit(level)
        if type(value) is dict:
            result = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise BoundaryRefused()
                result[clone(key, level + 1)] = clone(item, level + 1)
            return result
        if type(value) is list:
            return [clone(item, level + 1) for item in value]
        if type(value) is str:
            # Surrogates, including JSON-escaped unpaired surrogates, are not UTF-8.
            try:
                size = len(value.encode('utf-8'))
            except UnicodeError:
                size = MAX_BYTES + 1
            if size > MAX_BYTES:
                raise BoundaryRefused()
            return value
        if value is None or type(value) in (bool, int):
            if type(value) is int and value.bit_length() > 4096:
                raise BoundaryRefused()
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise BoundaryRefused()
    result = clone(candidate, depth)
    # Compact ASCII JSON is also the canonical on-wire encoding used by IPC.
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()) > MAX_BYTES:
        raise BoundaryRefused()
    return result


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise BoundaryRefused()
        obj[key] = value
    return obj


def _constant(_):
    raise BoundaryRefused()


_DECODER = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_constant)


def parse_json_v1(raw: str | bytes):
    """Refuse wire byte overflow BEFORE parsing, duplicate keys and non-JSON numbers."""
    result = None
    failed = False
    try:
        if type(raw) not in (str, bytes) or len(raw) > MAX_BYTES:
            raise BoundaryRefused()
        if type(raw) is bytes:
            raw = raw.decode('utf-8')
        if len(raw.encode('utf-8')) > MAX_BYTES:
            raise BoundaryRefused()
        result = _DECODER.decode(raw)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return bounded_copy_v1(result)


def embedded_json_v1(text: str):
    """Yield nonoverlapping (start, end, JSON) spans, including fenced JSON.

    At most 256 candidate starts: refuse adversarial repeated malformed openers
    rather than repeatedly decoding an unbounded quadratic suffix series.
    """
    end = 0
    attempts = 0
    for match in re.finditer(r'[\[{]', text):
        if match.start() < end:
            continue
        attempts += 1
        if attempts > 256:
            raise BoundaryRefused()
        parsed = None
        invalid = False
        try:
            parsed, stop = _DECODER.raw_decode(text, match.start())
        except BoundaryRefused:
            invalid = True
        except (ValueError, RecursionError):
            continue
        if invalid:
            raise BoundaryRefused()
        end = stop
        yield match.start(), end, parsed
