"""S01: plugin.json/mcp.json pass the pinned Hermes core translator; locks, runners and licenses pin.

Config validation only. Nothing here starts gateway/run.py: S05 owns the first executable launch
(DESIGN §0, §8.1 item 3). The translator is pinned core 088f657 on PYTHONPATH (DESIGN §9).
Imports only stdlib, pytest and pinned core; no gateway/dashboard/Desktop leaf of this package.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from hermes_cli.agent_plugins import AgentPluginError, load_agent_plugin, manifest_config_schema
from hermes_cli.plugin_validate import ValidationReport, _check_config_spec
from hermes_cli.plugins_settings import _field_type, secret_env_name

ROOT = Path(__file__).resolve().parents[2]
CORE = Path("/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent")
UPSTREAM = Path("/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-official-plugins")
UPSTREAM_SHA = "1e326ddd28ae261821d7714d106fe114999a0bba"
CANARY = "st-canary-7f3e1c9a-not-a-real-key"


def _manifests():
    return (json.loads((ROOT / "plugin.json").read_text(encoding="utf-8")),
            json.loads((ROOT / "mcp.json").read_text(encoding="utf-8")))


def _package_dir(tmp_path: Path, plugin: dict | None = None, mcp: dict | None = None) -> Path:
    """Copy of the manifests alone: proves translation needs no gateway/run.py on disk."""
    real_plugin, real_mcp = _manifests()
    pkg = tmp_path / "hermes-studiotwin"
    pkg.mkdir()
    (pkg / "plugin.json").write_text(json.dumps(plugin or real_plugin), encoding="utf-8")
    (pkg / "mcp.json").write_text(json.dumps(mcp or real_mcp), encoding="utf-8")
    return pkg


@pytest.fixture()
def translated(tmp_path):
    pkg = _package_dir(tmp_path)
    data = tmp_path / "plugin-data" / "agent-plugin-hermes-studiotwin"
    return pkg, data, load_agent_plugin(pkg, data)


# --- translator (pinned core hermes_cli/agent_plugins.py) ---------------------------------------


def test_pinned_core_reference_is_the_one_on_pythonpath():
    import hermes_cli.agent_plugins as agent_plugins

    assert Path(agent_plugins.__file__).resolve() == CORE / "hermes_cli" / "agent_plugins.py"


def test_identity_and_single_server(translated):
    _pkg, _data, package = translated
    assert package.name == "hermes-studiotwin"  # D01
    assert list(package.mcp_servers) == ["studiotwin"]  # D01
    assert package.diagnostics == ()
    assert package.server_declarations == {}  # policy keys alone declare no application


def test_stdio_launch_contract_translates_with_bare_python(translated):
    pkg, data, package = translated
    server = package.mcp_servers["studiotwin"]
    assert server["command"] == "python"  # bare executable, never a root-anchored path (DESIGN §0)
    assert server["args"] == [str(pkg / "gateway" / "run.py")]  # ${PLUGIN_ROOT} expanded in args
    assert server["cwd"] == str(data)  # ${PLUGIN_DATA}
    assert data.is_dir()  # discovery creates only the data root
    assert server["env"]["PLUGIN_ROOT"] == str(pkg) and server["env"]["PLUGIN_DATA"] == str(data)
    assert not (pkg / "gateway").exists()  # translation alone: no entry point needed, none launched


def test_policy_is_untrusted_with_timeout_and_no_static_costs(translated):
    _pkg, _data, package = translated
    server = package.mcp_servers["studiotwin"]
    assert server["trust"] == "untrusted"
    assert 0 < server["timeout"] <= 600
    for key in ("tool_costs", "spend_limit", "cost_unit"):
        assert key not in server  # manifest spend_limit is not a safety control (DESIGN §2.2)


def test_secrets_stay_profile_references_in_the_manifest(translated):
    _pkg, _data, package = translated
    env = package.mcp_servers["studiotwin"]["env"]
    assert env["STUDIOTWIN_API_KEY"] == "${STUDIOTWIN_API_KEY}"
    assert env["STUDIOTWIN_EXPERT_API_KEY"] == "${STUDIOTWIN_EXPERT_API_KEY}"
    plugin, mcp = _manifests()
    plugin.pop("$schema"), mcp.pop("$schema")  # the Agent Plugins schema ids are the only URLs allowed
    raw = json.dumps([plugin, mcp])
    for marker in ("http://", "https://", "x-api-key", "api-dev.studiotwin"):
        assert marker not in raw  # the gateway derives the endpoint; no URL or header in manifests


def test_root_anchored_command_is_rejected_by_the_translator(tmp_path):
    """Why DESIGN §0 forbids `${PLUGIN_ROOT}/gateway/run.py` as `command`: core rejects the entry, and
    because plugin.json still declares the server, the whole package then fails closed."""
    from hermes_cli.agent_plugins import _translate_stdio

    _plugin, mcp = _manifests()
    mcp["mcpServers"]["studiotwin"]["command"] = "${PLUGIN_ROOT}/gateway/run.py"
    with pytest.raises(ValueError, match="bare executable or begin with ./"):
        _translate_stdio(mcp["mcpServers"]["studiotwin"], tmp_path, tmp_path / "data")
    with pytest.raises(AgentPluginError, match="no matching mcp.json server"):
        load_agent_plugin(_package_dir(tmp_path, mcp=mcp), tmp_path / "data")


def test_posix_dot_slash_fallback_translates(tmp_path):
    _plugin, mcp = _manifests()
    mcp["mcpServers"]["studiotwin"].update(command="./gateway/run.py", args=[])
    pkg = _package_dir(tmp_path, mcp=mcp)
    package = load_agent_plugin(pkg, tmp_path / "data")
    assert package.mcp_servers["studiotwin"]["command"] == str(pkg / "gateway" / "run.py")


def test_unknown_trust_value_is_fatal(tmp_path):
    plugin, _mcp = _manifests()
    plugin["extensions"]["com.nousresearch.hermes"]["servers"]["studiotwin"]["trust"] = "trusted"
    with pytest.raises(AgentPluginError):
        load_agent_plugin(_package_dir(tmp_path, plugin=plugin), tmp_path / "data")


# --- settings schema (D04, D28) ----------------------------------------------------------------


def test_config_schema_passes_admission_shape_check():
    plugin, _mcp = _manifests()
    report = ValidationReport()
    _check_config_spec(report, {"config_schema": manifest_config_schema(plugin)})
    assert report.ok, report.failures


def test_settings_fields_render_as_intended():
    schema = manifest_config_schema(_manifests()[0])
    kinds = {key: _field_type(spec) for key, spec in schema.items()}
    assert kinds["api_key"] == "secret" and kinds["expert_api_key"] == "secret"
    assert secret_env_name("hermes-studiotwin", "api_key", schema["api_key"]) == "STUDIOTWIN_API_KEY"
    assert secret_env_name("hermes-studiotwin", "expert_api_key", schema["expert_api_key"]) == "STUDIOTWIN_EXPERT_API_KEY"
    assert kinds["endpoint"] == "enum"
    assert schema["endpoint"]["choices"] == ["staging", "production", "expert"]
    assert schema["endpoint"]["default"] == "staging"  # D04
    assert kinds["expert_url_confirmed"] == "boolean" and schema["expert_url_confirmed"]["default"] is False  # D28
    assert schema["spend_guard_credits"]["default"] == 200  # D11
    assert schema["unattended_max_credits"]["default"] == 0  # D15
    assert schema["webgl_limit"]["default"] == 4  # D13
    assert schema["cache_quota_mb"]["default"] == 2048  # D26
    for key, spec in schema.items():
        assert "default" not in spec or kinds[key] != "secret", key
        assert spec.get("description"), key


def test_profile_secret_interpolation_reaches_the_child_env_without_cross_fill(tmp_path, monkeypatch):
    """Runtime render path: profile secret scope -> recursive ${VAR} interpolation -> filtered child
    env (tools/mcp_tool_config.py). The expert credential is never filled from the main key (D28)."""
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from tools import mcp_tool_config

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    for name in ("STUDIOTWIN_API_KEY", "STUDIOTWIN_EXPERT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    server = dict(load_agent_plugin(_package_dir(tmp_path), tmp_path / "data").mcp_servers["studiotwin"])
    token = set_secret_scope({"STUDIOTWIN_API_KEY": CANARY}, profile_home=str(tmp_path / "home"))
    try:
        rendered = mcp_tool_config._interpolate_env_vars(server)
        child_env = mcp_tool_config._build_safe_env(rendered["env"])
    finally:
        reset_secret_scope(token)
    assert child_env["STUDIOTWIN_API_KEY"] == CANARY
    assert "STUDIOTWIN_EXPERT_API_KEY" not in child_env
    assert CANARY not in json.dumps(server)  # the translated config never carries the value
    assert rendered["args"] == server["args"] and rendered["command"] == "python"


# --- locks, runners and licenses ----------------------------------------------------------------


def test_python_project_and_lock_are_pinned():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == ">=3.11"
    assert project["project"]["dependencies"] == ["mcp==2.3.0"]
    for requirement in [*project["project"]["dependencies"], *project["dependency-groups"]["dev"]]:
        assert "==" in requirement, requirement
    assert not any(r.startswith("pytest-xdist") for r in project["dependency-groups"]["dev"])
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert lock["requires-python"] == ">=3.11"
    versions = {p["name"]: p.get("version") for p in lock["package"]}
    assert versions["mcp"] == "2.3.0" and versions["pytest"] == "9.1.1"


def test_running_interpreter_is_the_locked_project_environment():
    assert sys.version_info >= (3, 11)
    assert Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    from importlib.metadata import version

    assert version("mcp") == "2.3.0" and version("pytest") == "9.1.1"


def test_node_project_and_lock_pin_the_serial_vitest_runner():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert package["engines"]["node"] == ">=24.0.0"
    deps = {**package.get("dependencies", {}), **package["devDependencies"]}
    for name, spec in deps.items():
        assert spec[0].isdigit(), f"{name} must be an exact pin, got {spec}"
    assert deps["vitest"] == "3.2.4"  # 3.x: --pool=forks --poolOptions.forks.singleFork=true is supported
    assert lock["lockfileVersion"] == 3
    for name, spec in deps.items():
        assert lock["packages"][f"node_modules/{name}"]["version"] == spec, name
    assert "jest" not in json.dumps(package)  # no Jest --runInBand path


def test_pytest_collects_the_dotted_s27_release_test_filename(tmp_path):
    """Salt DESIGN-REREVIEW-3 note 3: S27's `tests/docs/release.test.py` must import and run under
    this pytest config, both as an explicit path (S27's command) and during a directory walk."""
    sandbox = tmp_path / "repo"
    (sandbox / "tests" / "docs").mkdir(parents=True)
    shutil.copy(ROOT / "pyproject.toml", sandbox / "pyproject.toml")
    (sandbox / "tests" / "docs" / "release.test.py").write_text(
        "def test_release_probe():\n    assert True\n", encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for args in (["tests/docs/release.test.py"], ["tests"]):
        result = subprocess.run([sys.executable, "-B", "-m", "pytest", *args, "-q"], cwd=sandbox, env=env,
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout


@pytest.mark.parametrize(("target", "upstream", "year"), [
    ("licenses/MESHY-LICENSE", "meshy/LICENSE", "2025"),
    ("licenses/ELEVENLABS-SFX-LICENSE", "elevenlabs-sound-effects/LICENSE", "2026"),
    ("licenses/ELEVENLABS-MUSIC-LICENSE", "elevenlabs-music/LICENSE", "2026"),
])
def test_licenses_are_verbatim_with_the_original_copyright_line(target, upstream, year):
    ours = (ROOT / target).read_bytes()
    assert f"Copyright (c) {year} Nous Research".encode() in ours
    assert ours.startswith(b"MIT License")
    if UPSTREAM.is_dir():  # read-only reference at the pinned commit
        assert hashlib.sha256(ours).digest() == hashlib.sha256((UPSTREAM / upstream).read_bytes()).digest()
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert f"retained | {target} | {upstream}@{UPSTREAM_SHA} | verbatim | MIT, Copyright (c) {year} Nous Research" in notice


def test_no_provider_runtime_or_meshy_server_is_configured():
    plugin, mcp = _manifests()
    text = json.dumps([plugin, mcp]).lower()
    for marker in ("meshy", "elevenlabs", "npx", "meshy-mcp-server"):
        assert marker not in text, marker
