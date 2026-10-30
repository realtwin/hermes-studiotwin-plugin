"""S02 fixture foundation acceptance (DESIGN §8.1 item 1, §9 S02).

    env PYTHONPATH=<pinned hermes-agent> uv run pytest tests/fixtures/test_fixture_foundation.py -q

Proves: the 45-tool capture is the verbatim source; every named fake-server mode is reachable
and shows its distinguishing behaviour over a real MCP client (in-process JSON-RPC stream, and
loopback Streamable HTTP for HTTP modes); every canary is unique, synthetic and observable in
its declared channel; every media golden is reproducible and structurally valid. No network
except 127.0.0.1; no StudioTwin calls.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # keep fake_mcp/ and media/ free of __pycache__

import base64  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import time  # noqa: E402
import wave  # noqa: E402
import zlib  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import anyio  # noqa: E402
import httpx2  # noqa: E402
import jsonschema  # noqa: E402
import mcp_types as T  # noqa: E402
import pytest  # noqa: E402
from mcp.client import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from mcp.shared.exceptions import MCPError  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Pytest's assertion rewriter caches this module's bytecode under tests/fixtures/__pycache__,
# which is outside S02's writable paths and has no ignore rule. Remove our own cache entry.
for _pyc in (HERE / "__pycache__").glob("test_fixture_foundation.*.pyc"):
    _pyc.unlink(missing_ok=True)
try:
    (HERE / "__pycache__").rmdir()
except OSError:
    pass

# Pinned Hermes core (on PYTHONPATH) ships a top-level `tests` package, so import fake_mcp from
# this directory explicitly and prove which file was loaded.
sys.path.insert(0, str(HERE))
from fake_mcp import canaries, catalog, concept_inputs  # noqa: E402
from fake_mcp.http import serve  # noqa: E402
from fake_mcp.scenarios import MODES  # noqa: E402
from fake_mcp.server import MAX_CREDITS_CAPABILITY, build_server  # noqa: E402
from fake_mcp.state import FakeStudioTwin  # noqa: E402

assert Path(catalog.__file__).resolve().is_relative_to(HERE), catalog.__file__

SOURCE_CAPTURE = Path(catalog.TOOLS_LIST_SOURCE)
MEDIA = HERE / "media"
CONTRACTS = HERE / "contracts"
PY = sys.executable

# Independent of the capture: the 45 names exactly as DESIGN §3 lists them, in matrix order.
DESIGN_45 = [
    "text-to-motion-edit", "text-to-motion", "text-to-motion-kimodo", "text-to-motion-control",
    "motion-stitch-single", "text-to-environment-map", "image-to-environment-map", "environment-map-to-world",
    "environment-map-upscale-cpu", "pano-sticker-placement", "pano-stickers", "text-to-material",
    "texture-to-material", "image-to-material", "image-to-3d-mesh", "tripo-image-to-3d-mesh", "tripo-rig-check",
    "blender-auto-rig", "tripo-auto-rig", "tripo-retopology", "text-to-sound-effect",
    "prompt-to-dart-translation", "openai-gpt-image-2-v4-fn", "concept-lab-img-fn", "studiotwin_get_job_status",
    "studiotwin_estimate_cost", "studiotwin_get_credit_balance", "studiotwin_list_my_jobs",
    "studiotwin_cancel_job", "studiotwin_list_my_assets", "studiotwin_upload_asset",
    "studiotwin_complete_asset_upload", "studiotwin_resolve_asset", "studiotwin_conceptlab_create",
    "studiotwin_conceptlab_create_and_generate", "studiotwin_conceptlab_list", "studiotwin_conceptlab_get",
    "studiotwin_conceptlab_get_status", "studiotwin_conceptlab_attach_asset", "studiotwin_conceptlab_generate",
    "studiotwin_conceptlab_edit", "studiotwin_conceptlab_clone", "studiotwin_conceptlab_set_active_asset",
    "studiotwin_conceptlab_update", "studiotwin_conceptlab_delete",
]


# =============================================================================== helpers
def dummy(schema: dict[str, Any]) -> Any:
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "number" or t == "integer":
        return schema.get("minimum", 1)
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return "vpc::assets/00000000-0000-4000-8000-000000000001"


def required_args(name: str) -> dict[str, Any]:
    schema = catalog.tool(name)["inputSchema"]
    return {k: dummy(schema["properties"].get(k, {})) for k in schema.get("required", [])}


class Session:
    """A connected MCP client plus raw (unvalidated) tools/call, progress and log capture."""

    def __init__(self, client: Client, fake: FakeStudioTwin):
        self.client, self.fake = client, fake
        self.progress: list[str] = []
        self.logs: list[Any] = []
        self.notifications: list[Any] = []

    async def call(self, name: str, args: dict[str, Any] | None = None, *, timeout: float | None = None) -> T.CallToolResult:
        async def pcb(progress: float, total: float | None, message: str | None) -> None:
            self.progress.append(message or "")

        return await self.client.session.send_request(
            T.CallToolRequest(params=T.CallToolRequestParams(name=name, arguments=args or {})),
            T.CallToolResult, request_read_timeout_seconds=timeout, progress_callback=pcb)

    async def json(self, name: str, args: dict[str, Any] | None = None) -> Any:
        res = await self.call(name, args)
        assert not res.is_error, res
        return json.loads(res.content[0].text)

    async def names(self) -> list[str]:
        return [t.name for t in (await self.client.list_tools()).tools]

    async def run_job(self, name: str = "text-to-environment-map", args: dict[str, Any] | None = None) -> str:
        ack = await self.json(name, args if args is not None else required_args(name))
        return ack["jobId"]

    async def poll_to_end(self, job_id: str, limit: int = 10) -> dict[str, Any]:
        for _ in range(limit):
            st = await self.json("studiotwin_get_job_status", {"jobId": job_id})
            if st["status"] in ("done", "failed", "COMPLETE", "FAILED"):
                return st
        return st


def session(mode_name: str, body, *, proto: str = "legacy", **overrides):
    """Run `body(Session)` against a fresh fake in `mode_name` over the in-process JSON-RPC stream."""
    fake = FakeStudioTwin(MODES[mode_name].scenario.with_(**overrides) if overrides else MODES[mode_name].scenario)

    async def main():
        s: Session

        async def lcb(params):
            s.logs.append(params.data)

        async def mh(message):
            s.notifications.append(message)

        async with Client(build_server(fake), mode=proto, logging_callback=lcb, log_level="debug",
                          message_handler=mh) as client:
            s = Session(client, fake)
            return await body(s)

    return anyio.run(main), fake


def http_session(harness, body, *, proto: str = "legacy", api_key: str | None = None):
    async def main():
        s: Session

        async def lcb(params):
            s.logs.append(params.data)

        hc = httpx2.AsyncClient(headers={"x-api-key": api_key or harness.api_key})
        async with Client(streamable_http_client(harness.mcp_url, http_client=hc), mode=proto,
                          logging_callback=lcb, log_level="debug") as client:
            s = Session(client, harness.fake)
            return await body(s)

    return anyio.run(main)


def raw_post(harness, *, api_key: str | None = "default") -> httpx2.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "s02", "version": "0"}}}
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    if api_key is not None:
        headers["x-api-key"] = harness.api_key if api_key == "default" else api_key
    with httpx2.Client(follow_redirects=False) as c:
        return c.post(harness.mcp_url, json=body, headers=headers)


# =============================================================================== capture
def test_capture_is_verbatim_source_with_pinned_sha256():
    local = (HERE / "tools-list-2026-10-30.json").read_bytes()
    assert hashlib.sha256(local).hexdigest() == catalog.TOOLS_LIST_SHA256 == catalog.capture_sha256()
    if SOURCE_CAPTURE.is_file():  # the handoff copy; absent on other hosts
        assert SOURCE_CAPTURE.read_bytes() == local


def test_capture_has_45_unique_tools_matching_design_matrix():
    names = catalog.tool_names()
    assert len(names) == len(set(names)) == catalog.EXPECTED_TOOL_COUNT == 45
    assert names == DESIGN_45
    src = json.loads(SOURCE_CAPTURE.read_text()) if SOURCE_CAPTURE.is_file() else catalog.capture()
    assert [t["name"] for t in src["tools"]] == names
    assert len(catalog.generation_tools()) == 24 and len(catalog.concept_tools()) == 12
    assert set(catalog.CONCEPT_PAID_TOOLS) <= set(catalog.concept_tools())
    assert catalog.UNCLASSIFIED_TOOL["name"] not in names


def test_derived_contracts_are_current():
    out = subprocess.run([PY, "-B", str(CONTRACTS / "build_contracts.py"), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    summary = json.loads((CONTRACTS / "tools-list-summary.v1.json").read_text())
    assert summary["toolCount"] == 45 and summary["captureSha256"] == catalog.TOOLS_LIST_SHA256
    assert [r["name"] for r in summary["tools"]] == DESIGN_45
    modes = json.loads((CONTRACTS / "fake-modes.v1.json").read_text())
    assert [m["name"] for m in modes["modes"]] == list(MODES)


def test_fake_server_lists_exact_capture_over_both_protocol_eras():
    for proto in ("legacy", "auto"):
        async def body(s: Session):
            tools = (await s.client.list_tools()).tools
            return [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]

        listed, _ = session("normal", body, proto=proto)
        assert [t["name"] for t in listed] == DESIGN_45
        for got, want in zip(listed, catalog.tools()):
            assert got["inputSchema"] == want["inputSchema"]
            assert got.get("outputSchema") == want.get("outputSchema")
            assert got.get("annotations") == want.get("annotations")


def test_every_captured_tool_is_callable_on_the_fake():
    async def body(s: Session):
        results = {}
        for name in catalog.generation_tools():
            res = await s.call(name, required_args(name))
            assert not res.is_error, (name, res.content)
            results[name] = json.loads(res.content[0].text)
        for name in catalog.PLATFORM_TOOLS:
            args = {"studiotwin_get_job_status": {"jobId": results["text-to-motion"]["jobId"]},
                    "studiotwin_estimate_cost": {"functionName": "text-to-material"},
                    "studiotwin_cancel_job": {"jobId": results["tripo-auto-rig"]["jobId"]},
                    "studiotwin_resolve_asset": {"assetId": next(iter(s.fake.assets))}}.get(name, {})
            if name == "studiotwin_complete_asset_upload":
                sid = (await s.json("studiotwin_upload_asset"))["uuid"]
                s.fake.put_upload(sid, "x.png", b"png")
                args = {"uploadSessionId": sid}
            res = await s.call(name, args)
            assert not res.is_error, (name, res.content)
        return results

    results, fake = session("normal", body)
    assert len(results) == 24 and len(fake.jobs) == 24
    assert all(r["status"] == "queued" and r["functionName"] == n for n, r in results.items())


# =============================================================================== modes
# One probe per named mode. Each asserts the observable that distinguishes the mode.
def probe_normal():
    async def body(s: Session):
        ack_res = await s.call("text-to-environment-map", {"prompt": "dusk", "seed": 3})
        statuses = []
        for _ in range(3):
            statuses.append((await s.json("studiotwin_get_job_status", {"jobId": json.loads(ack_res.content[0].text)["jobId"]})))
        return ack_res, statuses

    (ack_res, statuses), fake = session("normal", body)
    ack = json.loads(ack_res.content[0].text)
    assert ack_res.structured_content is None  # live shape: text-only JSON ack
    assert set(ack) == {"jobId", "functionName", "cost", "status", "next"} and ack["cost"] == 20
    assert [s["status"] for s in statuses] == ["queued", "running", "done"]
    outputs = statuses[-1]["outputs"]
    assert set(outputs) == {"environmentHDR", "environmentPNG"}
    for url in outputs.values():
        assert canaries.value("job_output_signed_url") in url and ".invalid/" in url
        assert fake.fetch_signed(url).startswith((b"#?RADIANCE", b"\x89PNG\r\n\x1a\n"))
    assert fake.balance == 500 - 20 and [e["event"] for e in fake.ledger] == ["debit", "settled"]


def probe_ambiguous(mode_name: str, check_response):
    async def body(s: Session):
        try:
            res = await s.call("text-to-environment-map", {"prompt": "x", "seed": 1}, timeout=0.5)
        except (MCPError, TimeoutError) as exc:  # protocol error / timeout after create
            res = exc
        listed = await s.json("studiotwin_list_my_jobs")
        return res, listed

    (res, listed), fake = session(mode_name, body, **({"hang_seconds": 3.0} if "timeout" in mode_name else {}))
    check_response(res)
    # The job really was created and billed even though the response hides it.
    assert len(fake.jobs) == 1 and [e["event"] for e in fake.ledger] == ["debit"]
    job_id = next(iter(fake.jobs))
    assert job_id not in json.dumps(res.model_dump(mode="json") if hasattr(res, "model_dump") else str(res))
    assert [j["uuid"] for j in listed] == [job_id]  # recoverable by listing


def _no_structured(res):
    assert isinstance(res, T.CallToolResult) and not res.is_error and res.structured_content is None


def probe_ambiguous_no_structured_content():
    def check(res):
        _no_structured(res)
        assert "jobId" not in res.content[0].text and "received" in res.content[0].text
    probe_ambiguous("ambiguous_no_structured_content", check)


def probe_ambiguous_empty_content():
    def check(res):
        _no_structured(res)
        assert res.content == []
    probe_ambiguous("ambiguous_empty_content", check)


def probe_ambiguous_malformed_ack():
    def check(res):
        _no_structured(res)
        with pytest.raises(json.JSONDecodeError):
            json.loads(res.content[0].text)
    probe_ambiguous("ambiguous_malformed_ack", check)


def probe_ambiguous_protocol_error_after_create():
    def check(res):
        assert isinstance(res, MCPError) and res.code == -32603
    probe_ambiguous("ambiguous_protocol_error_after_create", check)


def probe_ambiguous_timeout_after_create():
    def check(res):
        assert isinstance(res, (MCPError, TimeoutError)) and not isinstance(res, T.CallToolResult)
        if isinstance(res, MCPError):
            assert "timed out" in res.message.lower() or res.code in (-32001, 408)
    probe_ambiguous("ambiguous_timeout_after_create", check)


def probe_delayed_list_visibility():
    async def body(s: Session):
        job = await s.run_job()
        seen = [[j["uuid"] for j in await s.json("studiotwin_list_my_jobs")] for _ in range(3)]
        return job, seen

    (job, seen), _ = session("delayed_list_visibility", body)
    assert seen == [[], [], [job]]


def _price_change(mode_name: str, max_credits: int | None):
    async def body(s: Session):
        est = await s.json("studiotwin_estimate_cost", {"functionName": "text-to-material", "inputs": {"textPrompt": "oak"}})
        args = dict(required_args("text-to-material"))
        if max_credits is not None:
            args["maxCredits"] = max_credits
        res = await s.call("text-to-material", args)
        status = None
        if not res.is_error:
            status = await s.poll_to_end(json.loads(res.content[0].text)["jobId"])
        caps = s.client.server_capabilities.experimental or {}
        return est, res, status, caps

    return session(mode_name, body)


def probe_price_change_interim():
    (est, res, status, caps), fake = _price_change("price_change_interim", None)
    assert est["estimatedCost"] == 18 and not res.is_error and MAX_CREDITS_CAPABILITY not in caps
    debit = [e for e in fake.ledger if e["event"] == "debit"]
    assert debit == [{"event": "debit", "jobId": debit[0]["jobId"], "function": "text-to-material", "credits": 30,
                      "estimate": 18, "provider": "fixture-provider-b"}]
    assert fake.balance == 500 - 30 and len(fake.jobs) == 1
    assert status["settlement"]["finalDebitCredits"] == 30 > est["estimatedCost"]
    assert [e["provider"] for e in fake.ledger if e["event"] == "estimate"] == ["fixture-provider-a"]


def probe_price_change_server_max():
    (est, res, status, caps), fake = _price_change("price_change_server_max", 18)
    assert MAX_CREDITS_CAPABILITY in caps
    assert res.is_error and json.loads(res.content[0].text)["code"] == "PRICE_EXCEEDS_MAX"
    assert fake.jobs == {} and fake.balance == 500 and status is None
    assert [e["event"] for e in fake.ledger] == ["estimate", "rejected_price_exceeds_max"]
    (_, res2, _, _), fake2 = _price_change("price_change_server_max", 40)
    assert not res2.is_error and len(fake2.jobs) == 1


def probe_max_credits_advertised_not_enforced():
    (est, res, status, caps), fake = _price_change("max_credits_advertised_not_enforced", 18)
    assert MAX_CREDITS_CAPABILITY in caps  # advertised ...
    assert not res.is_error and fake.balance == 500 - 30  # ... but silently not enforced


def probe_settlement_evidence():
    async def body(s: Session):
        return await s.poll_to_end(await s.run_job())

    st, _ = session("settlement_evidence", body)
    assert st["settlement"] == {"kind": "fixture-ledger-v1", "ledgerRef": f"fixture-ledger-{st['uuid']}",
                                "finalDebitCredits": 20, "refundCredits": 0}
    st_normal, _ = session("normal", body)
    assert "settlement" not in st_normal


def probe_job_failure():
    async def body(s: Session):
        return await s.poll_to_end(await s.run_job())

    st, fake = session("job_failure", body)
    assert st["status"] == "failed" and st["error"]["code"] == "GENERATION_FAILED" and st["outputs"] == {}
    assert fake.balance == 500 and [e["event"] for e in fake.ledger] == ["debit", "refund"]


def probe_long_running():
    async def body(s: Session):
        job = await s.run_job("pano-stickers")
        return [(await s.json("studiotwin_get_job_status", {"jobId": job}))["status"] for _ in range(12)]

    statuses, _ = session("long_running", body)
    assert statuses[0] == "queued" and set(statuses[1:]) == {"running"}


def probe_insufficient_balance():
    async def body(s: Session):
        return await s.call("text-to-environment-map", {"prompt": "x", "seed": 1}), await s.json("studiotwin_get_credit_balance")

    (res, bal), fake = session("insufficient_balance", body)
    assert res.is_error and "40001" in res.content[0].text and fake.jobs == {} and bal == {"balance": 3}


def _channel_dump(res: T.CallToolResult) -> dict[str, Any]:
    d = res.model_dump(mode="json", by_alias=True, exclude_none=True)
    blocks = d["content"]
    return {
        "text": [b["text"] for b in blocks if b["type"] == "text" and not b.get("_meta")],
        "resource_link": [b["uri"] for b in blocks if b["type"] == "resource_link"],
        "embedded_resource": [b["resource"] for b in blocks if b["type"] == "resource"],
        "content_meta": [b["_meta"] for b in blocks if b.get("_meta")],
        "structured_content": d.get("structuredContent"),
        "result_meta": {k: v for k, v in (d.get("_meta") or {}).items() if k.startswith("fixture/")},
    }


SECRET_CHANNEL_EXPECTATIONS = {
    "text_prose_url": "text", "text_embedded_json": "text", "text_fenced_json": "text",
    "resource_link_uri": "resource_link", "embedded_resource_uri": "embedded_resource",
    "embedded_resource_text": "embedded_resource", "embedded_resource_blob": "embedded_resource",
    "content_meta": "content_meta", "result_meta": "result_meta", "structured_content": "structured_content",
    "structured_content_post_signature": "structured_content",
}


def probe_secret_channels():
    async def body(s: Session):
        ok = await s.call("studiotwin_get_credit_balance")
        err = await s.call("studiotwin_get_job_status", {"jobId": "no-such-job"})
        upload = await s.call("studiotwin_upload_asset")
        return ok, err, upload, s.progress, s.logs

    (ok, err, upload, progress, logs), _ = session("secret_channels", body)
    channels = _channel_dump(ok)
    for cid, channel in SECRET_CHANNEL_EXPECTATIONS.items():
        assert cid in canaries.find(channels[channel]), (cid, channel)
        others = {k: v for k, v in channels.items() if k != channel}
        if cid not in ("text_prose_url",):
            assert cid not in canaries.find(others) or channel == "text", (cid, "leaked into another channel")
    # Embedded/fenced JSON parse back out of prose.
    embedded = re.search(r"(\{.*\})", channels["text"][2]).group(1)
    assert canaries.value("text_embedded_json") in json.loads(embedded)["debug"]["previewUrl"]
    fenced = channels["text"][3].split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert canaries.value("text_fenced_json") in json.loads(fenced)["downloadUrl"]
    blob = next(r["blob"] for r in channels["embedded_resource"] if "blob" in r)
    assert canaries.value("embedded_resource_blob").encode() in base64.b64decode(blob)
    assert err.is_error and "error_result_text" in canaries.find(err.content[0].text)
    assert "progress_message" in canaries.find(progress) and "log_message" in canaries.find(logs)
    post = json.loads(_channel_dump(upload)["text"][0])["preSignedPost"]
    assert {"upload_post_url", "upload_post_policy", "upload_post_signature", "upload_post_credential",
            "upload_post_security_token"} <= canaries.find(post)
    assert "api_key" not in canaries.find([ok, err, upload, progress, logs])


def probe_secret_protocol_error():
    async def body(s: Session):
        with pytest.raises(MCPError) as info:
            await s.call("studiotwin_get_job_status", {"jobId": "no-such-job"})
        return info.value

    exc, _ = session("secret_protocol_error", body)
    assert "protocol_error_message" in canaries.find(exc.message)
    assert "protocol_error_data" in canaries.find(exc.data)


def probe_new_unclassified_tool():
    async def body(s: Session):
        names = await s.names()
        res = await s.json(catalog.UNCLASSIFIED_TOOL["name"], {"prompt": "x"})
        return names, res

    (names, res), fake = session("new_unclassified_tool", body)
    assert names == DESIGN_45 + [catalog.UNCLASSIFIED_TOOL["name"]]
    assert res["cost"] == catalog.UNCLASSIFIED_TOOL_COST and len(fake.jobs) == 1  # billable if ever forwarded
    _, fake_normal = session("normal", lambda s: s.call(catalog.UNCLASSIFIED_TOOL["name"], {"prompt": "x"}))
    assert fake_normal.jobs == {}


def probe_new_tool_midsession():
    async def body(s: Session):
        before = await s.names()
        await s.json("studiotwin_get_credit_balance")
        await anyio.sleep(0.05)
        after = await s.names()
        return before, after, s.notifications

    (before, after, notes), _ = session("new_tool_midsession", body)
    assert before == DESIGN_45 and after == DESIGN_45 + [catalog.UNCLASSIFIED_TOOL["name"]]
    assert any(isinstance(n, T.ToolListChangedNotification) for n in notes), notes


def probe_schema_drift():
    async def body(s: Session):
        return [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in (await s.client.list_tools()).tools]

    tools, _ = session("schema_drift", body)
    assert [t["name"] for t in tools] == DESIGN_45
    drifted = next(t for t in tools if t["name"] == catalog.SCHEMA_DRIFT_TOOL)
    assert catalog.schema_hash(drifted) != catalog.schema_hash(catalog.tool(catalog.SCHEMA_DRIFT_TOOL))
    assert "fixtureDriftMode" in drifted["inputSchema"]["required"]
    same = [t for t in tools if t["name"] != catalog.SCHEMA_DRIFT_TOOL]
    assert all(catalog.schema_hash(t) == catalog.schema_hash(catalog.tool(t["name"])) for t in same)


def probe_malformed_status():
    async def body(s: Session):
        job = await s.run_job()
        return await s.call("studiotwin_get_job_status", {"jobId": job})

    res, _ = session("malformed_status", body)
    assert not res.is_error and res.content[0].text.startswith("<html>")
    with pytest.raises(json.JSONDecodeError):
        json.loads(res.content[0].text)


def probe_malformed_concept():
    async def body(s: Session):
        raw = await s.call("studiotwin_conceptlab_create", {"conceptType": "object", "name": "n"})
        with pytest.raises(RuntimeError, match="Invalid structured content"):
            await s.client.call_tool("studiotwin_conceptlab_create", {"conceptType": "object", "name": "m"})
        return raw

    raw, _ = session("malformed_concept", body)
    schema = catalog.tool("studiotwin_conceptlab_create")["outputSchema"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw.structured_content, schema)


def probe_mixed_timestamps():
    async def body(s: Session):
        for _ in range(4):
            await s.poll_to_end(await s.run_job())
        return await s.json("studiotwin_list_my_jobs")

    jobs, _ = session("mixed_timestamps", body)
    kinds = [type(j["createdAt"]).__name__ + (":offset" if isinstance(j["createdAt"], str) and "+02:00" in j["createdAt"] else "")
             for j in jobs]
    assert kinds == ["str", "str:offset", "int", "dict"]
    assert jobs[3]["createdAt"]["$date"].endswith("Z")


def probe_described_status_vocabulary():
    async def body(s: Session):
        job = await s.run_job()
        return [(await s.json("studiotwin_get_job_status", {"jobId": job}))["status"] for _ in range(3)]

    statuses, _ = session("described_status_vocabulary", body)
    assert statuses == ["QUEUED", "RUNNING", "COMPLETE"]


def probe_optional_outputs_omitted():
    async def body(s: Session):
        world = await s.poll_to_end(await s.run_job("environment-map-to-world"))
        rig = await s.poll_to_end(await s.run_job("tripo-auto-rig"))
        return world["outputs"], rig["outputs"]

    (world, rig), _ = session("optional_outputs_omitted", body)
    assert set(world) == {"worldMesh"} and set(rig) == {"metadata"}
    (world_n, rig_n), _ = session("normal", body)
    assert set(world_n) == {"skyMap", "worldMesh"} and "mesh" in rig_n


def probe_expiring_signed_urls():
    async def body(s: Session):
        return await s.poll_to_end(await s.run_job())

    st, fake = session("expiring_signed_urls", body)
    url = st["outputs"]["environmentPNG"]
    assert "X-Amz-Expires=60" in url and fake.fetch_signed(url).startswith(b"\x89PNG")
    fake.advance(61)
    with pytest.raises(PermissionError, match="expired"):
        fake.fetch_signed(url)


def probe_slow_calls():
    async def body(s: Session):
        t0 = time.monotonic()
        await s.json("studiotwin_get_credit_balance")
        return time.monotonic() - t0

    elapsed, _ = session("slow_calls", body)
    assert elapsed >= 0.3


def probe_concept_active_asset_race():
    async def body(s: Session):
        a, b = list(s.fake.assets)[:2]
        c = await s.json("studiotwin_conceptlab_create", {"conceptType": "object", "name": "race"})
        await s.json("studiotwin_conceptlab_attach_asset", {"conceptId": c["uuid"], "assetId": a, "makeActive": True})
        await s.json("studiotwin_conceptlab_attach_asset", {"conceptId": c["uuid"], "assetId": b})
        job_inputs = {"modelId": "openai/gpt-image-2", "prompt": {"user": "fog", "enhancement": {"enabled": False}}}
        quoted = concept_inputs.build_op_inputs("edit", job_inputs, s.fake.assets[a]["s3Uri"], "object")
        await s.json("studiotwin_conceptlab_edit", {"conceptId": c["uuid"], "jobInputs": job_inputs})
        return a, b, quoted

    (a, b, quoted), fake = session("concept_active_asset_race", body)
    submitted = fake.vp_submissions[-1]
    assert submitted["functionName"] == "concept-lab-img-fn"
    assert quoted["sourceAsset"] == fake.assets[a]["s3Uri"] != submitted["inputs"]["sourceAsset"] == fake.assets[b]["s3Uri"]
    assert {k: v for k, v in submitted["inputs"].items() if k != "sourceAsset"} == \
        {k: v for k, v in quoted.items() if k != "sourceAsset"}


def probe_http_sse():
    with serve(FakeStudioTwin(MODES["http_sse"].scenario)) as h:
        async def body(s: Session):
            names = await s.names()
            await s.json("studiotwin_get_credit_balance")
            return names, s.progress

        names, progress = http_session(h, body)
        assert names == DESIGN_45 and progress == ["studiotwin_get_credit_balance: accepted"]
        r = raw_post(h)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")


def probe_http_rate_limited():
    with serve(FakeStudioTwin(MODES["http_rate_limited"].scenario)) as h:
        codes = [raw_post(h) for _ in range(3)]
        assert [r.status_code for r in codes] == [429, 429, 200]
        assert codes[0].headers["retry-after"] == "1"


def probe_http_redirect_foreign():
    with serve(FakeStudioTwin(MODES["http_redirect_foreign"].scenario)) as h:
        r = raw_post(h)
        assert r.status_code == 307 and "redirect_location" in canaries.find(r.headers["location"])
        assert r.headers["location"].startswith("https://redirect-target.invalid/")
        with pytest.raises(BaseException):  # the SDK refuses a cross-origin MCP redirect
            http_session(h, lambda s: s.names())
        assert not any(req["path"] != "/mcp" for req in h.requests)


def probe_http_redirect_same_origin():
    with serve(FakeStudioTwin(MODES["http_redirect_same_origin"].scenario)) as h:
        r = raw_post(h)
        assert r.status_code == 307 and r.headers["location"] == "/mcp-moved"
        names = http_session(h, lambda s: s.names())
        assert names == DESIGN_45 and any(req["path"] == "/mcp-moved" for req in h.requests)


def probe_http_error_body():
    with serve(FakeStudioTwin(MODES["http_error_body"].scenario)) as h:
        r = raw_post(h)
        assert r.status_code == 502 and "http_error_body" in canaries.find(r.text)


PROBES = {name[len("probe_"):]: fn for name, fn in dict(globals()).items()
          if name.startswith("probe_") and callable(fn) and name not in ("probe_ambiguous",)}


def test_every_mode_has_exactly_one_probe():
    assert set(PROBES) == set(MODES), (set(MODES) ^ set(PROBES))


@pytest.mark.parametrize("mode_name", list(MODES))
def test_fake_mode_reachable(mode_name):
    PROBES[mode_name]()


def test_normal_mode_over_loopback_http_with_api_key_and_storage():
    with serve(FakeStudioTwin(MODES["normal"].scenario)) as h:
        assert h.host == "127.0.0.1"
        assert raw_post(h, api_key=None).status_code == 401
        assert raw_post(h, api_key="wrong").status_code == 401

        async def body(s: Session):
            job = await s.run_job()
            st = await s.poll_to_end(job)
            sid = (await s.json("studiotwin_upload_asset"))
            return st, sid

        st, upload = http_session(h, body)
        url = st["outputs"]["environmentHDR"]
        assert url.startswith(h.storage_base)
        with httpx2.Client() as c:
            assert c.get(url).content.startswith(b"#?RADIANCE")
            assert c.get(url.replace("X-Amz-Signature=", "X-Amz-Signature=x")).status_code == 403
            post = upload["preSignedPost"]
            files = {"file": ("frames.tar", (MEDIA / "sequence/frames-4x16.tar").read_bytes())}
            assert c.post(post["url"], data={k: v.replace("${filename}", "frames.tar") for k, v in post["fields"].items()},
                          files=files).status_code == 204
            assert c.post(post["url"], data={}, files=files).status_code == 403

        async def complete(s: Session):
            bad = await s.call("studiotwin_complete_asset_upload", {"uploadSessionId": upload["uuid"]})
            entries = json.loads((MEDIA / "MANIFEST.json").read_text())["files"]["sequence/frames-4x16.tar"]["entries"]
            good = await s.json("studiotwin_complete_asset_upload", {"uploadSessionId": upload["uuid"], "entries": entries})
            again = await s.call("studiotwin_complete_asset_upload", {"uploadSessionId": upload["uuid"], "entries": entries})
            return bad, good, again

        bad, good, again = http_session(h, complete, proto="auto")
        assert bad.is_error and "entries are required" in bad.content[0].text
        assert good["status"] == "closed" and good["assets"][0]["type"] == "image_sequence"
        assert again.is_error and "already closed" in again.content[0].text
        mcp_posts = [r for r in h.requests if r["path"] == "/mcp" and r["method"] == "POST"]
        assert [r["has_api_key"] for r in mcp_posts[:2]] == [False, True]  # the two raw 401 probes
        assert all(r["has_api_key"] for r in mcp_posts[3:])  # every SDK session request authenticated


def test_live_shape_generation_ack_fails_sdk_output_schema_validation():
    """Recorded for S05/S06: the live ack carries no structuredContent although the tool declares
    an outputSchema (it describes job outputs), so mcp==2.3.0 `Client.call_tool` raises.
    The gateway must read generation acks without SDK output validation."""
    async def body(s: Session):
        with pytest.raises(RuntimeError, match="did not return structured content"):
            await s.client.call_tool("text-to-environment-map", {"prompt": "x", "seed": 1})

    _, fake = session("normal", body)
    assert len(fake.jobs) == 1  # and the job was created anyway: an ambiguity source


# =============================================================================== Concepts
def test_concept_effective_inputs_port_matches_source_derived_contract():
    doc = json.loads((CONTRACTS / "concept-effective-inputs.v1.json").read_text())
    assert doc["source"].endswith(concept_inputs.API_SOURCE_COMMIT)
    for case in doc["cases"]:
        got = concept_inputs.build_op_inputs(case["action"], case["jobInputs"], case["sourceS3Uri"], case["conceptType"])
        assert got == case["expected"], case["id"]
        assert list(got)[-1] == "n"


def test_fake_server_submits_effective_inputs_for_concept_generate_and_edit():
    doc = {c["id"]: c for c in json.loads((CONTRACTS / "concept-effective-inputs.v1.json").read_text())["cases"]}

    async def body(s: Session):
        ref = next(iter(s.fake.assets))
        ji = doc["gpt_image_2_resolution_alias"]["jobInputs"]
        c = await s.json("studiotwin_conceptlab_create_and_generate", {"conceptType": "character", "name": "k", "jobInputs": ji})
        status = [await s.json("studiotwin_conceptlab_get_status", {"conceptId": c["uuid"]}) for _ in range(3)]
        got = await s.json("studiotwin_conceptlab_get", {"conceptId": c["uuid"]})
        edit_ji = doc["edit_uses_active_asset"]["jobInputs"]
        await s.json("studiotwin_conceptlab_edit", {"conceptId": c["uuid"], "jobInputs": edit_ji})
        gen_src = {"modelId": "openai/gpt-image-2", "prompt": {"user": "like this", "enhancement": {"enabled": True}},
                   "sourceAsset": f"vpc::assets/{ref}"}
        c2 = await s.json("studiotwin_conceptlab_create", {"conceptType": "object", "name": "o"})
        await s.json("studiotwin_conceptlab_generate", {"conceptId": c2["uuid"], "jobInputs": gen_src})
        return c, status, got, ref

    (c, status, got, ref), fake = session("normal", body)
    subs = fake.vp_submissions
    assert [x["functionName"] for x in subs] == ["concept-lab-img-fn"] * 3
    assert subs[0]["inputs"] == doc["gpt_image_2_resolution_alias"]["expected"]
    active = next(a for a in got["assets"] if a["isActive"])
    assert subs[1]["inputs"]["mode"] == "edit" and subs[1]["inputs"]["sourceAsset"] == fake.assets[active["assetId"]]["s3Uri"]
    assert subs[2]["inputs"]["sourceAsset"] == fake.assets[ref]["s3Uri"] and subs[2]["inputs"]["mode"] == "generate"
    assert [x["operation"]["status"] for x in status] == ["queued", "running", "done"]
    # Concept results dual-emit and validate against the captured outputSchemas.
    jsonschema.validate(c, catalog.tool("studiotwin_conceptlab_create_and_generate")["outputSchema"])
    jsonschema.validate(got, catalog.tool("studiotwin_conceptlab_get")["outputSchema"])
    jsonschema.validate(status[-1], catalog.tool("studiotwin_conceptlab_get_status")["outputSchema"])


def test_concept_crud_tools_and_outputs_validate():
    async def body(s: Session):
        a = next(iter(s.fake.assets))
        c = (await s.client.call_tool("studiotwin_conceptlab_create", {"conceptType": "world", "name": "w",
                                                                       "metadata": {"x": 1}})).structured_content
        out = {"create": c}
        out["attach"] = (await s.client.call_tool("studiotwin_conceptlab_attach_asset",
                                                  {"conceptId": c["uuid"], "assetId": a, "makeActive": True})).structured_content
        out["set_active"] = (await s.client.call_tool("studiotwin_conceptlab_set_active_asset",
                                                      {"conceptId": c["uuid"], "assetId": a})).structured_content
        out["update"] = (await s.client.call_tool("studiotwin_conceptlab_update",
                                                  {"conceptId": c["uuid"], "metadata": {"y": 2}})).structured_content
        out["clone"] = (await s.client.call_tool("studiotwin_conceptlab_clone", {"conceptId": c["uuid"]})).structured_content
        out["list"] = (await s.client.call_tool("studiotwin_conceptlab_list", {"limit": 5})).structured_content
        out["delete"] = (await s.client.call_tool("studiotwin_conceptlab_delete", {"conceptId": c["uuid"]})).structured_content
        out["bad_extra"] = await s.call("studiotwin_conceptlab_get", {"conceptId": c["uuid"], "x": 1})
        return out

    out, _ = session("normal", body)  # Client.call_tool validates every outputSchema
    assert out["update"]["metadata"] == {"y": 2}  # replaces, never merges
    assert out["clone"]["sourceConceptId"] == out["create"]["uuid"] and out["clone"]["assets"][0]["isActive"]
    assert out["delete"]["deleted"] is True and len(out["list"]["concepts"]) == 2
    assert out["bad_extra"].is_error and "Unexpected argument" in out["bad_extra"].content[0].text


# =============================================================================== canaries
REAL_KEY_SHAPES = [
    r"AKIA[0-9A-Z]{16}", r"ASIA[0-9A-Z]{16}", r"\bsk-[A-Za-z0-9]{20,}", r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\bxox[abprs]-", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
    r"\bAIza[0-9A-Za-z_-]{35}", r"\b[0-9a-f]{40}\b(?<!0)",
]


def test_canaries_unique_greppable_and_not_real_looking():
    doc = canaries.document()
    rows = doc["canaries"]
    values = [r["value"] for r in rows]
    assert len(values) == len(set(values)) == len({r["id"] for r in rows}) == 28
    for r in rows:
        v = r["value"]
        assert re.fullmatch(r"STCANARY_[A-Z0-9_]+_[0-9a-f]{10}", v), v
        assert v == f"STCANARY_{r['id'].upper()}_" + hashlib.sha256(r["id"].encode()).hexdigest()[:10]
        assert not any(v in o for o in values if o != v), "no canary is a substring of another"
    corpus = (HERE / "secret_channels/canaries.v1.json").read_text()
    for pat in REAL_KEY_SHAPES[:-1]:
        assert not re.search(pat, corpus), pat
    # Every URL any fake mode emits is on a reserved .invalid host or the loopback harness.
    _, fake = session("secret_channels", lambda s: s.call("studiotwin_get_credit_balance"))
    assert fake.storage_base.endswith(".invalid")


def test_every_registered_canary_channel_is_emitted_somewhere():
    emitted: set[str] = set()

    async def body(s: Session):
        st = await s.poll_to_end(await s.run_job("text-to-sound-effect"))
        r = await s.json("studiotwin_resolve_asset", {"assetId": next(iter(s.fake.assets))})
        u = await s.json("studiotwin_upload_asset")
        b = await s.call("studiotwin_get_credit_balance")
        e = await s.call("studiotwin_get_job_status", {"jobId": "missing"})
        return [st, r, u, b, e, s.progress, s.logs]

    out, _ = session("secret_channels", body)
    emitted |= canaries.find(out)

    async def protocol_error(s: Session):
        try:
            await s.call("studiotwin_get_job_status", {"jobId": "x"})
        except MCPError as exc:
            return canaries.find([exc.message, exc.data])
        raise AssertionError("secret_protocol_error mode did not raise")

    found, _ = session("secret_protocol_error", protocol_error)
    emitted |= found
    with serve(FakeStudioTwin(MODES["http_error_body"].scenario)) as h:
        emitted |= canaries.find(raw_post(h).text)
    with serve(FakeStudioTwin(MODES["http_redirect_foreign"].scenario)) as h:
        emitted |= canaries.find(raw_post(h).headers["location"])
    missing = set(canaries.ids()) - emitted - {"api_key"}
    assert not missing, missing
    assert "api_key" not in emitted  # the key authenticates; it is never emitted


def test_leak_scanner_detects_every_needle_and_unregistered_values():
    for cid, needles in canaries.needles().items():
        for n in needles:
            assert canaries.find({"k": ["x", n.encode()]}) == {cid}
    assert canaries.find("STCANARY_SOMETHING_NEW") == {"<unregistered STCANARY_ value>"}
    assert canaries.find({"safe": "job 000010b5-0001"}) == set()
    with pytest.raises(AssertionError):
        canaries.assert_absent(["ok", canaries.value("log_message")])


# =============================================================================== media
MANIFEST = json.loads((MEDIA / "MANIFEST.json").read_text()) if (MEDIA / "MANIFEST.json").is_file() else {"files": {}}


def _glb(data: bytes) -> tuple[dict, bytes]:
    magic, version, total = struct.unpack_from("<4sII", data)
    assert magic == b"glTF" and version == 2 and total == len(data)
    jlen, jtype = struct.unpack_from("<I4s", data, 12)
    assert jtype == b"JSON"
    doc = json.loads(data[20:20 + jlen])
    blen, btype = struct.unpack_from("<I4s", data, 20 + jlen)
    assert btype == b"BIN\0"
    binary = data[28 + jlen:28 + jlen + blen]
    assert doc["buffers"][0]["byteLength"] <= len(binary)
    for acc in doc["accessors"]:
        view = doc["bufferViews"][acc["bufferView"]]
        comps = {"SCALAR": 1, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
        size = {5126: 4, 5123: 2, 5121: 1}[acc["componentType"]]
        assert view["byteOffset"] + view["byteLength"] <= len(binary)
        assert acc["count"] * comps * size == view["byteLength"]
    return doc, binary


def _png(data: bytes) -> tuple[int, int, int, bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        (n,) = struct.unpack_from(">I", data, pos)
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        (crc,) = struct.unpack_from(">I", data, pos + 8 + n)
        assert zlib.crc32(tag + body) & 0xFFFFFFFF == crc, tag
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    w, h, depth, ctype = ihdr[0], ihdr[1], ihdr[2], ihdr[3]
    channels = {0: 1, 2: 3, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    assert depth == 8 and len(raw) == h * (1 + w * channels)
    return w, h, channels, raw


def test_media_tree_small_and_manifest_hashes_match():
    files = MANIFEST["files"]
    assert len(files) == 17
    total = 0
    for rel, meta in files.items():
        data = (MEDIA / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"] and len(data) == meta["bytes"], rel
        total += len(data)
    on_disk = {p.relative_to(MEDIA).as_posix() for p in MEDIA.rglob("*") if p.is_file()}
    assert on_disk == set(files) | {"MANIFEST.json", "generate_media.py"}
    assert sum(p.stat().st_size for p in HERE.rglob("*") if p.is_file()) < 1_000_000
    assert MANIFEST["not_produced"] == []


def test_media_generator_reproduces_every_file_byte_for_byte():
    out = subprocess.run([PY, "-B", str(MEDIA / "generate_media.py"), "--check"], capture_output=True, text=True)
    report = json.loads(out.stdout)
    assert out.returncode == 0 and report["differ"] == [], report
    if shutil.which("ffmpeg"):
        assert report["skipped"] == []


def test_glb_static_and_rigged_animated():
    static, _ = _glb((MEDIA / "model/static-cube.glb").read_bytes())
    assert "skins" not in static and "animations" not in static
    assert static["accessors"][static["meshes"][0]["primitives"][0]["indices"]]["count"] == 36
    rig, binary = _glb((MEDIA / "model/rigged-animated.glb").read_bytes())
    prim = rig["meshes"][0]["primitives"][0]
    assert {"JOINTS_0", "WEIGHTS_0"} <= set(prim["attributes"])
    assert rig["nodes"][0]["skin"] == 0 and rig["skins"][0]["joints"] == [1, 2]
    assert [a["name"] for a in rig["animations"]] == ["Wave", "Idle"]
    for anim in rig["animations"]:
        sampler = anim["samplers"][0]
        assert rig["accessors"][sampler["input"]]["count"] == rig["accessors"][sampler["output"]]["count"] == 3
        out = rig["accessors"][sampler["output"]]
        view = rig["bufferViews"][out["bufferView"]]
        quats = struct.unpack_from("<12f", binary, view["byteOffset"])
        for i in range(3):
            assert abs(math.sqrt(sum(q * q for q in quats[4 * i:4 * i + 4])) - 1) < 1e-5
    w = rig["accessors"][prim["attributes"]["WEIGHTS_0"]]
    weights = struct.unpack_from("<48f", binary, rig["bufferViews"][w["bufferView"]]["byteOffset"])
    assert all(abs(sum(weights[4 * i:4 * i + 4]) - 1) < 1e-6 for i in range(12))


def _rgbe(px: bytes) -> tuple[float, float, float]:
    if px[3] == 0:
        return (0.0, 0.0, 0.0)
    f = math.ldexp(1.0, px[3] - 136)
    return (px[0] * f, px[1] * f, px[2] * f)


def test_hdr_exr_and_png_equirect():
    hdr = (MEDIA / "env/equirect-64x32.hdr").read_bytes()
    head, _, body = hdr.partition(b"\n\n")
    assert head.startswith(b"#?RADIANCE") and b"FORMAT=32-bit_rle_rgbe" in head
    res, _, pixels = body.partition(b"\n")
    assert res == b"-Y 32 +X 64" and len(pixels) == 64 * 32 * 4
    peak = max(max(_rgbe(pixels[i:i + 4])) for i in range(0, len(pixels), 4))
    assert peak > 1.0  # genuinely high dynamic range

    exr = (MEDIA / "env/equirect-32x16.exr").read_bytes()
    assert struct.unpack_from("<ii", exr) == (20000630, 2)
    pos, attrs = 8, {}
    while exr[pos] != 0:
        name_end = exr.index(b"\0", pos)
        type_end = exr.index(b"\0", name_end + 1)
        (size,) = struct.unpack_from("<i", exr, type_end + 1)
        attrs[exr[pos:name_end].decode()] = (exr[name_end + 1:type_end].decode(), exr[type_end + 5:type_end + 5 + size])
        pos = type_end + 5 + size
    assert attrs["compression"][1] == b"\x00" and attrs["channels"][0] == "chlist"
    assert struct.unpack("<iiii", attrs["dataWindow"][1]) == (0, 0, 31, 15)
    offsets = struct.unpack_from("<16Q", exr, pos + 1)
    y, size = struct.unpack_from("<ii", exr, offsets[0])
    assert y == 0 and size == 32 * 3 * 4
    values = []
    for off in offsets:
        _, n = struct.unpack_from("<ii", exr, off)
        values += struct.unpack_from(f"<{n // 4}f", exr, off + 8)
    assert offsets[-1] + 8 + size == len(exr) and max(values) > 1.0

    w, h, ch, _ = _png((MEDIA / "env/equirect-64x32.png").read_bytes())
    assert (w, h, ch) == (64, 32, 3) and w == 2 * h  # equirect aspect


def test_pbr_material_set_has_exactly_one_missing_role():
    ms = MANIFEST["material_set"]
    assert ms["missing"] == ["height"] and len(ms["present"]) == 4
    roles = {meta["role"]: rel for rel, meta in MANIFEST["files"].items() if "role" in meta}
    assert set(roles) == set(ms["present"])
    assert not any("height" in p.name for p in (MEDIA / "material").iterdir())
    for role, rel in roles.items():
        w, h, ch, _ = _png((MEDIA / rel).read_bytes())
        assert (w, h) == (16, 16) and ch == (1 if role in ("roughness", "metalness") else 3)
    # The fake material job returns signed URLs only for maps it has; height stays absent on disk.
    assert set(catalog.tool("text-to-material")["outputSchema"]["properties"]) >= {"albedo", "heightmap"}


def test_audio_wav_and_mp3():
    with wave.open(str(MEDIA / "audio/tone-48k.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (48000, 2, 2, 12000)
        frames = w.readframes(w.getnframes())
    first, last = struct.unpack_from("<h", frames, 0)[0], struct.unpack_from("<h", frames, len(frames) - 4)[0]
    assert first == 0 and abs(last) < 800  # loop boundary is near-continuous
    mp3 = (MEDIA / "audio/tone-44k.mp3").read_bytes()
    assert mp3[:3] != b"ID3" and mp3[0] == 0xFF and (mp3[1] & 0xE0) == 0xE0
    assert (mp3[1] >> 3) & 0x3 == 0b11 and (mp3[1] >> 1) & 0x3 == 0b01  # MPEG-1 Layer III
    assert ((mp3[2] >> 2) & 0x3) == 0  # 44.1 kHz


def _boxes(data: bytes) -> list[bytes]:
    out, pos = [], 0
    while pos + 8 <= len(data):
        size, typ = struct.unpack_from(">I4s", data, pos)
        out.append(typ)
        pos += size if size else len(data)
    return out


def test_video_mp4():
    data = (MEDIA / "video/testsrc-32.mp4").read_bytes()
    boxes = _boxes(data)
    assert boxes[0] == b"ftyp" and b"moov" in boxes and b"mdat" in boxes
    assert boxes.index(b"moov") < boxes.index(b"mdat")  # faststart: range playback without full download
    assert b"avc1" in data
    probe = shutil.which("ffprobe")
    if probe:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_name,width,height,nb_frames",
                              "-of", "json", str(MEDIA / "video/testsrc-32.mp4")], capture_output=True, text=True)
        stream = json.loads(out.stdout)["streams"][0]
        assert (stream["codec_name"], stream["width"], stream["height"], stream["nb_frames"]) == ("h264", 32, 32, "6")


def test_image_sequence_archives():
    data = (MEDIA / "sequence/frames-4x16.tar").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = tf.getmembers()
        assert [m.name for m in members] == [f"frame_{i:04d}.png" for i in range(4)]
        for m in members:
            assert _png(tf.extractfile(m).read())[:2] == (16, 16)
    meta = MANIFEST["files"]["sequence/frames-4x16.tar"]
    assert meta["entries"] == [{"name": m.name, "offset": m.offset, "size": m.size} for m in members]
    hostile = (MEDIA / "sequence/traversal-hostile.tar").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(hostile)) as tf:
        names = tf.getnames()
    assert "../../escape.txt" in names and MANIFEST["files"]["sequence/traversal-hostile.tar"]["hostile"] is True


def test_motion_and_image_fixtures():
    motion = json.loads((MEDIA / "motion/walk-clip.json").read_text())
    assert motion["frames"] == len(motion["joints"]["root"]) and motion["clips"][0]["name"] == "walk"
    w, h, ch, raw = _png((MEDIA / "image/concept-64.png").read_bytes())
    assert (w, h, ch) == (64, 64, 4)


def test_fake_outputs_resolve_to_committed_media():
    async def body(s: Session):
        res = {}
        for tool in ("image-to-3d-mesh", "blender-auto-rig", "text-to-sound-effect", "text-to-material"):
            res[tool] = (await s.poll_to_end(await s.run_job(tool)))["outputs"]
        return res

    out, fake = session("normal", body)
    assert fake.fetch_signed(out["image-to-3d-mesh"]["mesh"]) == (MEDIA / "model/static-cube.glb").read_bytes()
    assert fake.fetch_signed(out["blender-auto-rig"]["mesh"]) == (MEDIA / "model/rigged-animated.glb").read_bytes()
    assert fake.fetch_signed(out["text-to-sound-effect"]["audioClip"]) == (MEDIA / "audio/tone-48k.wav").read_bytes()
    assert out["text-to-sound-effect"]["sizeBytes"] == (MEDIA / "audio/tone-48k.wav").stat().st_size
    assert fake.fetch_signed(out["text-to-material"]["albedo"]) == (MEDIA / "material/pbr-albedo.png").read_bytes()
    assert fake.fetch_signed(out["text-to-material"]["heightmap"]) == b""  # role missing from the set
    assert "job_output_storage_uri" in canaries.find(out["text-to-material"]["s3Uris"])
