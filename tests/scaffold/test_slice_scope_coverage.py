"""S01: slice-scopes.json encodes DESIGN §9 and every retained vendoring target has exactly one owner.

Imports only stdlib, pytest and the S01 checker (tools/check-slice-scopes.py). No gateway,
dashboard or Desktop leaf is imported; test_scaffold_import_graph_has_no_future_leaf proves it.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "tools" / "check-slice-scopes.py"
SCOPES_PATH = ROOT / "slice-scopes.json"
NOTICE_PATH = ROOT / "NOTICE"
CORE = "/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent"

S01_WRITABLE = [
    "plugin.json", "mcp.json", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts",
    "vitest.config.ts", "pyproject.toml", "uv.lock", "src/sdk.d.ts", "NOTICE", "licenses/**",
    "slice-scopes.json", "tools/check-slice-scopes.py", "tests/scaffold/**",
]
S01_COMMAND = (
    "npm ci && uv sync --frozen && env PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent "
    "uv run pytest tests/scaffold/test_manifest_config.py tests/scaffold/test_slice_scope_coverage.py -q && "
    "npm exec -- vitest run tests/scaffold/scaffold.test.ts --pool=forks --poolOptions.forks.singleFork=true"
)
SERIAL = "--pool=forks --poolOptions.forks.singleFork=true"


def _load_checker():
    sys.dont_write_bytecode = True  # keep tools/__pycache__ out of the worktree
    spec = importlib.util.spec_from_file_location("check_slice_scopes", CHECKER_PATH)
    assert spec is not None and spec.loader is not None, f"missing checker at {CHECKER_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


@pytest.fixture()
def scopes():
    return json.loads(SCOPES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def notice():
    return NOTICE_PATH.read_text(encoding="utf-8")


def _slice(doc, sid):
    return next(s for s in doc["slices"] if s["id"] == sid)


def _codes(report):
    return sorted({error.split(":", 1)[0] for error in report.errors})


# --- the real inventory -------------------------------------------------------------------------


def test_real_inventory_has_exactly_one_owner_per_retained_target(checker, scopes, notice):
    report = checker.check(scopes, notice)
    assert report.errors == []
    assert len(report.retained) == 42
    assert all(len(owners) == 1 for owners in report.owners.values())
    assert {t: o[0] for t, o in report.owners.items()} == scopes["retained_target_owners"]


def test_cli_exits_zero_on_the_real_inventory():
    result = subprocess.run([sys.executable, "-B", str(CHECKER_PATH), "--root", str(ROOT)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "42 retained targets" in result.stdout


def test_scopes_encode_all_thirty_design_rows(scopes):
    ids = [s["id"] for s in scopes["slices"]]
    assert ids == [f"S{i:02d}" for i in range(1, 31)]
    assert _slice(scopes, "S01")["writable"] == S01_WRITABLE
    assert _slice(scopes, "S01")["command"] == S01_COMMAND
    assert scopes["design"]["sha256_content_above_footer"] == (
        "7980c5207ce9f7c1bea49735e81d1becd91f6328e16b0728e8319bf62bf25a0d")
    for s in scopes["slices"]:
        assert s["writable"], s["id"]
        assert s["command"] and s["pass_assertion"], s["id"]
        assert set(s["depends_on"]) | set(s["may_run_with"]) <= set(ids), s["id"]


def test_every_command_uses_the_locked_serial_runners(scopes):
    for s in scopes["slices"]:
        command = s["command"]
        assert "--runInBand" not in command, s["id"]
        assert " -n " not in command and "xdist" not in command, s["id"]
        for part in command.split("&&"):
            if "vitest" in part:
                assert part.strip().startswith("npm exec -- vitest run ") and part.rstrip().endswith(SERIAL), s["id"]
            if "pytest" in part:
                assert part.strip().startswith(f"env PYTHONPATH={CORE} uv run pytest "), s["id"]
            if "playwright" in part:
                assert "--workers=1" in part, s["id"]


def test_s27_release_test_is_collectable_and_excluded_from_s25(scopes):
    """Salt DESIGN-REREVIEW-3 notes 2 and 3."""
    assert "tests/docs/release.test.py" in _slice(scopes, "S27")["writable"]
    assert "tests/docs/release.test.py" in _slice(scopes, "S27")["command"]
    assert "tests/docs/release.test.py" in _slice(scopes, "S25")["except"]
    assert scopes["sole_writer_paths"]["tests/docs/release.test.py"] == "S27"


def test_s28_is_sole_writer_of_routers_registry_and_plugin_entry(checker, scopes, notice):
    for path in ("gateway/router.py", "dashboard/router.py", "src/registry.ts", "src/plugin.tsx"):
        assert scopes["sole_writer_paths"][path] == "S28"
        assert checker.writers(scopes, path) == ["S28"], path


def test_meshy_mcp_server_is_explicitly_excluded(checker, notice):
    rows = checker.parse_notice(notice)
    assert any(r.status == "excluded" and r.upstream.startswith("meshy/mcp-server@") for r in rows)
    assert all(r.status in {"retained", "excluded"} for r in rows)


# --- adversarial fixtures -----------------------------------------------------------------------


def test_missing_owner_fails(checker, scopes, notice):
    _slice(scopes, "S17")["writable"].remove("skills/studiotwin-creative-suite/scripts/glb_stats.py")
    report = checker.check(scopes, notice)
    assert "missing-owner" in _codes(report)
    assert any("glb_stats.py" in e for e in report.errors)


def test_duplicate_owner_fails(checker, scopes, notice):
    _slice(scopes, "S23")["writable"].append("src/data/**")
    report = checker.check(scopes, notice)
    assert "duplicate-owner" in _codes(report)
    assert any("src/data/job-query.ts" in e and "S16" in e and "S23" in e for e in report.errors)


@pytest.mark.parametrize("grant", ["src/**", "dashboard/**", "gateway/**", "tests/**", "skills/**", "**", "*"])
def test_broad_grant_fails(checker, scopes, notice, grant):
    _slice(scopes, "S12")["writable"].append(grant)
    assert "broad-grant" in _codes(checker.check(scopes, notice))


def test_single_owner_top_level_trees_from_the_design_are_not_broad(checker, scopes, notice):
    assert "licenses/**" in _slice(scopes, "S01")["writable"]
    assert "docs/**" in _slice(scopes, "S27")["writable"]
    assert "broad-grant" not in _codes(checker.check(scopes, notice))


@pytest.mark.parametrize("grant", ["src/media/model", "src/media/model/", "/abs/path.ts", "src/../NOTICE",
                                   "src/*.ts", "src/**/x.ts", "./plugin.json", "src\\plugin.tsx", ""])
def test_malformed_or_implicit_directory_grant_fails(checker, scopes, notice, grant):
    _slice(scopes, "S17")["writable"].append(grant)
    assert "bad-grant" in _codes(checker.check(scopes, notice))


def test_implicit_parent_directory_ownership_is_not_ownership(checker, scopes, notice):
    s17 = _slice(scopes, "S17")
    s17["writable"] = [g for g in s17["writable"] if not g.startswith("src/media/model")] + ["src/media/model"]
    codes = _codes(checker.check(scopes, notice))
    assert "bad-grant" in codes and "missing-owner" in codes


def test_removing_an_exception_creates_a_duplicate_owner(checker, scopes, notice):
    _slice(scopes, "S25")["except"].remove("skills/studiotwin-creative-suite/scripts/sfx_tool.py")
    report = checker.check(scopes, notice)
    assert "duplicate-owner" in _codes(report)
    assert any("sfx_tool.py" in e and "S18" in e and "S25" in e for e in report.errors)


def test_exception_outside_own_grant_fails(checker, scopes, notice):
    _slice(scopes, "S26")["except"].append("src/cards/job-card.tsx")
    assert "exception-not-in-grant" in _codes(checker.check(scopes, notice))


def test_exception_that_no_other_slice_owns_fails(checker, scopes, notice):
    _slice(scopes, "S26")["except"].append("src/chrome/orphan.tsx")
    assert "exception-unowned" in _codes(checker.check(scopes, notice))


def test_exception_must_be_an_exact_path(checker, scopes, notice):
    _slice(scopes, "S26")["except"].append("src/chrome/sub/**")
    assert "bad-exception" in _codes(checker.check(scopes, notice))


def test_overlapping_grants_between_slices_fail_even_off_inventory(checker, scopes, notice):
    _slice(scopes, "S29")["writable"].append("tests/e2e/**")
    assert "grant-overlap" in _codes(checker.check(scopes, notice))


def test_sole_writer_violation_fails(checker, scopes, notice):
    _slice(scopes, "S12")["writable"].append("gateway/router.py")
    codes = _codes(checker.check(scopes, notice))
    assert "sole-writer" in codes


def test_declared_owner_mismatch_fails(checker, scopes, notice):
    scopes["retained_target_owners"]["src/plugin.tsx"] = "S18"
    assert "declared-owner-mismatch" in _codes(checker.check(scopes, notice))


def test_notice_target_missing_from_declared_owners_fails(checker, scopes, notice):
    del scopes["retained_target_owners"]["gateway/background_wait.py"]
    assert "notice-undeclared" in _codes(checker.check(scopes, notice))


def test_declared_target_missing_from_notice_fails(checker, scopes, notice):
    trimmed = "\n".join(line for line in notice.splitlines() if "| gateway/background_wait.py |" not in line)
    assert "declared-not-in-notice" in _codes(checker.check(scopes, trimmed))


def test_notice_row_with_wrong_upstream_sha_fails(checker, scopes, notice):
    broken = notice.replace("meshy/src/stage.ts@1e326ddd28ae261821d7714d106fe114999a0bba",
                            "meshy/src/stage.ts@e746f4c", 1)
    assert "notice-format" in _codes(checker.check(scopes, broken))


def test_slice_set_must_be_s01_to_s30(checker, scopes, notice):
    scopes["slices"].append(copy.deepcopy(_slice(scopes, "S30")))
    assert "slice-ids" in _codes(checker.check(scopes, notice))


def test_unknown_dependency_fails(checker, scopes, notice):
    _slice(scopes, "S04")["depends_on"].append("S31")
    assert "unknown-dependency" in _codes(checker.check(scopes, notice))


def test_cli_exits_nonzero_on_a_broken_fixture(tmp_path, scopes, notice):
    _slice(scopes, "S16")["writable"].append("src/**")
    (tmp_path / "slice-scopes.json").write_text(json.dumps(scopes), encoding="utf-8")
    (tmp_path / "NOTICE").write_text(notice, encoding="utf-8")
    result = subprocess.run([sys.executable, "-B", str(CHECKER_PATH), "--root", str(tmp_path)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "broad-grant" in result.stdout


# --- import isolation (DESIGN §9 preamble) ------------------------------------------------------

_FUTURE_ROOTS = ("gateway", "dashboard", "contracts", "skills", "src")


def test_scaffold_python_tests_import_no_future_leaf_statically():
    for path in sorted((ROOT / "tests" / "scaffold").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{path.name}: relative import"
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                assert top not in _FUTURE_ROOTS, f"{path.name} imports {name}"


def test_scaffold_import_graph_has_no_future_leaf(tmp_path):
    """Import both scaffold test modules in a clean interpreter and list every module loaded from
    this repository. Only the scaffold tests and the checker may appear: no gateway/, dashboard/,
    src/ or skills/ file. File paths are compared, so core's own ``gateway`` package cannot mask a
    plugin leaf (or be mistaken for one)."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, json, sys\n"
        "sys.dont_write_bytecode = True\n"
        f"root = {str(ROOT)!r}\n"
        "for name in ('test_manifest_config', 'test_slice_scope_coverage'):\n"
        "    spec = importlib.util.spec_from_file_location(name, f'{root}/tests/scaffold/{name}.py')\n"
        "    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)\n"
        "    if name == 'test_slice_scope_coverage': mod._load_checker()\n"
        "files = sorted({getattr(m, '__file__', None) or '' for m in list(sys.modules.values())})\n"
        "print(json.dumps([f for f in files if f.startswith(root + '/') and '/.venv/' not in f]))\n",
        encoding="utf-8")
    result = subprocess.run([sys.executable, "-B", str(probe)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    loaded = {str(Path(f).relative_to(ROOT)) for f in json.loads(result.stdout.strip().splitlines()[-1])}
    assert loaded == {"tests/scaffold/test_manifest_config.py", "tests/scaffold/test_slice_scope_coverage.py",
                      "tools/check-slice-scopes.py"}
