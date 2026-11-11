#!/usr/bin/env python3
"""Regenerate the derived S02 contract files (or `--check` them for drift).

    python tests/fixtures/contracts/build_contracts.py [--check]

Derived (from the pinned capture and the fake-mode registry):
  tools-list-summary.v1.json   45 names in capture order, families, fixed costs, schema hashes
  fake-modes.v1.json           every named fake mode: transport, consumers, knobs, summary
Hand-authored (not touched here):
  concept-effective-inputs.v1.json
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
# Import `fake_mcp` from tests/fixtures directly: pinned Hermes core (on PYTHONPATH in every §9
# command) ships its own top-level `tests` package, so `tests.fixtures...` would resolve there.
sys.path.insert(0, str(HERE.parent))

from fake_mcp import catalog  # noqa: E402
from fake_mcp.scenarios import MODES, Scenario  # noqa: E402

if not Path(catalog.__file__).resolve().is_relative_to(HERE.parent):  # pragma: no cover
    raise SystemExit(f"imported the wrong fake_mcp: {catalog.__file__}")


def tools_summary() -> dict:
    cap = catalog.capture()
    rows = []
    for t in cap["tools"]:
        name = t["name"]
        family = ("platform" if name in catalog.PLATFORM_TOOLS else
                  "concept" if name.startswith(catalog.CONCEPT_PREFIX) else "generation")
        rows.append({"name": name, "family": family, "fixedCost": catalog.fixed_cost(name),
                     "hasOutputSchema": "outputSchema" in t, "conceptPaid": name in catalog.CONCEPT_PAID_TOOLS,
                     "schemaHash": catalog.schema_hash(t)})
    return {"format": "studiotwin-tools-list-summary/v1", "capture": "tests/fixtures/tools-list-2026-10-30.json",
            "captureSha256": catalog.TOOLS_LIST_SHA256, "sourcePath": catalog.TOOLS_LIST_SOURCE,
            "server": cap["server"], "toolCount": len(rows), "tools": rows,
            "unclassifiedFixtureTool": catalog.UNCLASSIFIED_TOOL["name"],
            "schemaHashRule": "sha256 of compact sorted JSON {name,inputSchema,outputSchema} (fixture helper only)"}


def fake_modes() -> dict:
    defaults = Scenario()
    rows = []
    for m in MODES.values():
        knobs = {}
        for f in dataclasses.fields(Scenario):
            if f.name in ("name", "extra"):
                continue
            v = getattr(m.scenario, f.name)
            if v != getattr(defaults, f.name):
                knobs[f.name] = list(v) if isinstance(v, tuple) else v
        rows.append({"name": m.name, "transport": m.transport, "consumers": list(m.consumers),
                     "knobs": knobs, "summary": m.summary})
    return {"format": "studiotwin-fake-modes/v1", "module": "tests/fixtures/fake_mcp/scenarios.py",
            "modeCount": len(rows), "modes": rows}


OUTPUTS = {"tools-list-summary.v1.json": tools_summary, "fake-modes.v1.json": fake_modes}


def render(fn) -> str:
    return json.dumps(fn(), indent=2, sort_keys=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for name, fn in OUTPUTS.items():
        text = render(fn)
        path = HERE / name
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        print("stale: " + ", ".join(stale))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
