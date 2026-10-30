"""Secret canaries (tests/fixtures/secret_channels/canaries.v1.json) and a leak scanner.

Canary values are unique, greppable, synthetic strings with the `STCANARY_` prefix. They are
not real credentials and are not shaped like any provider key. URLs that carry them use the
reserved `.invalid` TLD (or the loopback harness).
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

CANARIES_PATH = Path(__file__).resolve().parent.parent / "secret_channels" / "canaries.v1.json"
PREFIX = "STCANARY_"


@lru_cache(maxsize=1)
def _doc() -> dict[str, Any]:
    return json.loads(CANARIES_PATH.read_text(encoding="utf-8"))


def document() -> dict[str, Any]:
    return json.loads(json.dumps(_doc()))


def value(canary_id: str) -> str:
    for row in _doc()["canaries"]:
        if row["id"] == canary_id:
            return row["value"]
    raise KeyError(canary_id)


def ids() -> list[str]:
    return [row["id"] for row in _doc()["canaries"]]


def needles() -> dict[str, list[str]]:
    return {row["id"]: list(row["needles"]) for row in _doc()["canaries"]}


def channels() -> dict[str, str]:
    return {row["id"]: row["channel"] for row in _doc()["canaries"]}


def blob_bytes(canary_id: str = "embedded_resource_blob") -> bytes:
    """The exact bytes whose base64 form is the second needle of the blob canary."""
    return b"\x00\x01fixture-blob:" + value(canary_id).encode() + b":end\xff"


def blob_b64(canary_id: str = "embedded_resource_blob") -> str:
    return base64.b64encode(blob_bytes(canary_id)).decode()


def _strings(obj: Any) -> Iterable[str]:
    if obj is None:
        return
    if isinstance(obj, (bytes, bytearray)):
        yield bytes(obj).decode("latin-1")
        return
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
        return
    if isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            yield from _strings(v)
        return
    if hasattr(obj, "model_dump"):
        yield from _strings(obj.model_dump(mode="json", by_alias=True))
        return
    yield str(obj)


def find(obj: Any) -> set[str]:
    """Ids of every canary any of whose needles occurs anywhere inside `obj`.

    Walks dicts (keys and values), sequences, pydantic models, str and bytes. Bytes are
    decoded latin-1 so binary sinks (files, sockets) can be scanned too.
    """
    haystack = "\x1f".join(_strings(obj))
    found = set()
    for cid, ns in needles().items():
        if any(n in haystack for n in ns):
            found.add(cid)
    if PREFIX in haystack and not found:
        found.add("<unregistered STCANARY_ value>")
    return found


def assert_absent(obj: Any, where: str = "output") -> None:
    leaked = find(obj)
    if leaked:
        raise AssertionError(f"secret canaries leaked into {where}: {sorted(leaked)}")
