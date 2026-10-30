#!/usr/bin/env python3
"""Check that every retained vendoring target has exactly one owning build slice.

Inputs (repository root, or --root):
  NOTICE             the vendoring inventory block (retained and excluded rows)
  slice-scopes.json  DESIGN §9 writable grants per slice, plus §15 declared owners

Grants are explicit paths or bounded `<dir>/**` subtrees. Bare directories, other globs,
absolute paths, `..`, and top-level-or-broader subtrees (`src/**`, `dashboard/**`, `**`) are
rejected: implicit parent-directory ownership is forbidden. A slice's `except` list holds exact
paths carved out of its own grants, each of which another slice must own.

Exit status: 0 when the inventory is consistent, 1 on any finding, 2 on unreadable input.
Stdlib only, so it runs under any Python 3.11+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UPSTREAM_SHA = "1e326ddd28ae261821d7714d106fe114999a0bba"
BEGIN = "BEGIN STUDIOTWIN VENDORING INVENTORY v1"
END = "END STUDIOTWIN VENDORING INVENTORY v1"
SLICE_IDS = [f"S{i:02d}" for i in range(1, 31)]
_SEGMENT = re.compile(r"^[A-Za-z0-9._@-]+$")


@dataclass(frozen=True)
class NoticeRow:
    status: str
    target: str
    upstream: str
    disposition: str
    license: str


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    retained: list[str] = field(default_factory=list)
    owners: dict[str, list[str]] = field(default_factory=dict)

    def add(self, code: str, message: str) -> None:
        self.errors.append(f"{code}: {message}")


def parse_notice(text: str) -> list[NoticeRow]:
    """Rows between the inventory markers. Raises ValueError on a missing/duplicated block."""
    lines = text.splitlines()
    if lines.count(BEGIN) != 1 or lines.count(END) != 1 or lines.index(BEGIN) > lines.index(END):
        raise ValueError("NOTICE must contain exactly one inventory block")
    rows = []
    for line in lines[lines.index(BEGIN) + 1:lines.index(END)]:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5:
            raise ValueError(f"inventory row needs 5 fields: {line!r}")
        rows.append(NoticeRow(*parts))
    return rows


def _grant_problem(grant: Any) -> str | None:
    """Why *grant* is not an acceptable writable grant, or None."""
    if not isinstance(grant, str) or not grant:
        return "empty or non-string grant"
    if grant.startswith("/") or "\\" in grant:
        return "grant must be a repository-relative POSIX path"
    if grant.endswith("/"):
        return "bare directory grants are implicit parent ownership; use an exact path or <dir>/**"
    segments = grant.split("/")
    subtree = segments[-1] == "**"
    body = segments[:-1] if subtree else segments
    if not body:
        return "unbounded glob"
    for segment in body:
        if segment in ("", ".", "..") or not _SEGMENT.fullmatch(segment):
            return f"invalid path segment {segment!r}"
    return None


# Top-level trees that several slices write into. A whole-tree grant on one of them would hand a
# single slice every sibling's files. Single-owner trees (`licenses/**` for S01, `docs/**` for S27)
# are legitimate bounded grants and are not listed.
SHARED_TREES = frozenset({"src", "dashboard", "gateway", "tests", "skills", "contracts", "tools"})


def _is_broad(grant: str) -> bool:
    """`**`, `*`, or a whole shared top-level tree such as `src/**` or `dashboard/**`."""
    return grant in ("*", "**") or (grant.endswith("/**") and grant[:-3] in SHARED_TREES)


def _known_paths(scopes: dict, notice_text: str) -> set[str]:
    """Every path the inputs name: grants, exceptions, sole-writer paths and NOTICE targets."""
    paths = set(scopes.get("sole_writer_paths", {}))
    for s in scopes["slices"]:
        paths.update(p for p in [*s.get("writable", []), *s.get("except", [])] if isinstance(p, str))
    try:
        paths.update(row.target for row in parse_notice(notice_text) if row.target != "-")
    except ValueError:
        pass  # reported as notice-format later
    return paths


def _looks_like_directory(grant: str, known: set[str]) -> bool:
    """An exact grant that is a strict path prefix of any named path is a bare directory."""
    prefix = grant + "/"
    return any(other.startswith(prefix) for other in known)


def _covers(grant: str, target: str) -> bool:
    if grant.endswith("/**"):
        base = grant[:-3]
        if target.endswith("/**"):
            return target[:-3] == base or target[:-3].startswith(base + "/")
        return target.startswith(base + "/")
    return grant == target


def _grants_overlap(a: str, b: str) -> bool:
    return _covers(a, b) or _covers(b, a)


def writers(scopes: dict, target: str) -> list[str]:
    """Slices whose grants cover *target*, after their own exact exceptions."""
    out = []
    for s in scopes["slices"]:
        if target in s.get("except", []):
            continue
        if any(_covers(g, target) for g in s.get("writable", []) if _grant_problem(g) is None):
            out.append(s["id"])
    return out


def check(scopes: dict, notice_text: str) -> Report:
    report = Report()
    slices = scopes.get("slices")
    if not isinstance(slices, list):
        report.add("slice-ids", "slice-scopes.json has no slices list")
        return report
    ids = [s.get("id") for s in slices]
    if ids != SLICE_IDS:
        report.add("slice-ids", f"expected S01..S30 once each in order, got {ids}")
    known_ids = set(ids)
    known_paths = _known_paths(scopes, notice_text)

    for s in slices:
        sid = s.get("id")
        for dep in [*s.get("depends_on", []), *s.get("may_run_with", [])]:
            if dep not in known_ids:
                report.add("unknown-dependency", f"{sid} references {dep}")
        for grant in s.get("writable", []):
            if isinstance(grant, str) and _is_broad(grant):
                report.add("broad-grant", f"{sid} grant {grant!r} owns a whole shared tree")
                continue
            problem = _grant_problem(grant)
            if problem:
                report.add("bad-grant", f"{sid} grant {grant!r}: {problem}")
            elif not grant.endswith("/**") and _looks_like_directory(grant, known_paths):
                report.add("bad-grant", f"{sid} grant {grant!r} is a directory; implicit parent ownership is forbidden")
        for exc in s.get("except", []):
            if _grant_problem(exc) or exc.endswith("/**"):
                report.add("bad-exception", f"{sid} exception {exc!r} must be an exact file path")
                continue
            if not any(_covers(g, exc) for g in s.get("writable", []) if _grant_problem(g) is None):
                report.add("exception-not-in-grant", f"{sid} excepts {exc!r}, which none of its grants cover")
            if not [w for w in writers(scopes, exc) if w != sid]:
                report.add("exception-unowned", f"{sid} excepts {exc!r} but no other slice owns it")

    # Grants of different slices must not overlap except where an exact exception separates them.
    for i, a in enumerate(slices):
        for b in slices[i + 1:]:
            for ga in a.get("writable", []):
                for gb in b.get("writable", []):
                    if _grant_problem(ga) or _grant_problem(gb) or not _grants_overlap(ga, gb):
                        continue
                    exact = gb if _covers(ga, gb) else ga
                    if exact.endswith("/**") or not (exact in a.get("except", []) or exact in b.get("except", [])):
                        report.add("grant-overlap", f"{a['id']} {ga!r} overlaps {b['id']} {gb!r}")

    for path, owner in scopes.get("sole_writer_paths", {}).items():
        found = writers(scopes, path)
        if found != [owner]:
            report.add("sole-writer", f"{path} must be written only by {owner}, writers: {found}")

    try:
        rows = parse_notice(notice_text)
    except ValueError as exc:
        report.add("notice-format", str(exc))
        return report
    retained: list[str] = []
    for row in rows:
        if row.status not in ("retained", "excluded"):
            report.add("notice-format", f"unknown status {row.status!r}")
            continue
        if not row.upstream.endswith("@" + UPSTREAM_SHA):
            report.add("notice-format", f"{row.upstream!r} is not pinned to {UPSTREAM_SHA}")
        if row.status == "excluded":
            if row.target != "-":
                report.add("notice-format", f"excluded row must not name a target: {row.target!r}")
            continue
        if _grant_problem(row.target):
            report.add("notice-format", f"retained target {row.target!r} is not a bounded path")
            continue
        if not row.license.startswith("MIT, Copyright (c) "):
            report.add("notice-format", f"{row.target}: license field must keep the upstream MIT copyright line")
        if row.target not in retained:
            retained.append(row.target)
    report.retained = retained

    declared = scopes.get("retained_target_owners", {})
    for target in retained:
        owners = writers(scopes, target)
        report.owners[target] = owners
        if not owners:
            report.add("missing-owner", f"{target} has no owning slice")
        elif len(owners) > 1:
            report.add("duplicate-owner", f"{target} is owned by {', '.join(owners)}")
        if target not in declared:
            report.add("notice-undeclared", f"{target} is in NOTICE but not in retained_target_owners")
        elif owners and declared[target] != owners[0]:
            report.add("declared-owner-mismatch", f"{target} declared {declared[target]}, grants give {owners}")
    for target in declared:
        if target not in retained:
            report.add("declared-not-in-notice", f"{target} is declared but has no retained NOTICE row")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check exact-one-owner coverage of retained vendoring targets.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        scopes = json.loads((args.root / "slice-scopes.json").read_text(encoding="utf-8"))
        notice = (args.root / "NOTICE").read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"error: cannot read inputs: {exc}", file=sys.stderr)
        return 2
    report = check(scopes, notice)
    for error in report.errors:
        print(error)
    if report.errors:
        print(f"FAIL: {len(report.errors)} finding(s)")
        return 1
    print(f"OK: {len(report.retained)} retained targets, each owned by exactly one of {len(scopes['slices'])} slices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
