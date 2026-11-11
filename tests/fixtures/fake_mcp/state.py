"""Deterministic in-memory StudioTwin behaviour behind the fake MCP server.

`FakeStudioTwin` owns a fake clock, wallet, jobs, assets, upload sessions and Concepts, and
answers every captured tool. Result shapes follow the API's `src/mcp/mcp.service.ts`
(commit 2eb0df1e): platform and generation tools return one JSON text block and no
`structuredContent`; Concept tools dual-emit text + `structuredContent`; handler failures
become `isError` text results. Scenario knobs (see `scenarios.py`) bend that behaviour into
the failure modes later slices need.

Every upstream side effect is recorded in `ledger` (debits, refunds, jobs created) and
`vp_submissions` (the exact function + inputs a job was submitted with), so tests can prove
"the job was actually created" even when the response hides it.
"""

from __future__ import annotations

import copy
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import canaries, catalog, concept_inputs
from .scenarios import Scenario

EPOCH = datetime(2026, 10, 30, 8, 0, 0, tzinfo=timezone.utc)
USER_ID = "0f1e2d3c-0000-4000-8000-00000000a11c"
ORG_ID = "0f1e2d3c-0000-4000-8000-0000000000e9"
STORAGE_BUCKET = "fixture-bucket"
DEFAULT_STORAGE_BASE = "https://fixture-bucket.s3.invalid"
MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
ASSET_REF_RE = re.compile(r"^(?:vpc::assets/)?([0-9a-fA-F-]{36})$")

# Deterministic "exact estimate" for tools whose description says to estimate.
ESTIMATES = {
    "text-to-motion": 6,
    "text-to-motion-kimodo": 6,
    "environment-map-upscale-cpu": 12,
    "pano-stickers": 14,
    "text-to-material": 18,
    "image-to-material": 22,
    "tripo-image-to-3d-mesh": 30,
    "tripo-retopology": 10,
    "text-to-sound-effect": 3,
    "openai-gpt-image-2-v4-fn": 6,
    "concept-lab-img-fn": 6,
}

# Which committed media fixture backs a signed output URL, by (tool, output key) then key.
_MEDIA_BY_KEY = {
    "environmentHDR": "env/equirect-64x32.hdr",
    "panoramaHDR": "env/equirect-64x32.hdr",
    "environmentPNG": "env/equirect-64x32.png",
    "panorama": "env/equirect-64x32.png",
    "skyMap": "env/equirect-64x32.png",
    "worldMesh": "model/static-cube.glb",
    "mesh": "model/static-cube.glb",
    "audit": "model/rig-audit.json",
    "json": "motion/walk-clip.json",
    "audioClip": "audio/tone-48k.wav",
    "albedo": "material/pbr-albedo.png",
    "normals": "material/pbr-normal.png",
    "roughness": "material/pbr-roughness.png",
    "metalness": "material/pbr-metalness.png",
    "previewUrl": "material/pbr-albedo.png",
    "imageUrl": "image/concept-64.png",
}
_MEDIA_BY_TOOL_KEY = {
    ("blender-auto-rig", "mesh"): "model/rigged-animated.glb",
    ("tripo-auto-rig", "mesh"): "model/rigged-animated.glb",
}
_CATEGORY_BY_EXT = {
    "glb": "3d_model", "gltf": "3d_model", "wav": "audio", "mp3": "audio", "mp4": "video",
    "png": "image", "jpg": "image", "jpeg": "image", "hdr": "image", "exr": "image",
    "json": "animation", "tar": "image_sequence",
}
_DESCRIBED_STATUS = {"queued": "QUEUED", "running": "RUNNING", "done": "COMPLETE", "failed": "FAILED",
                     "cancelled": "CANCELLED", "draft": "DRAFT"}


class ToolFailure(Exception):
    """A handler failure the live server reports as an `isError` text result."""


class ProtocolFailure(Exception):
    """A failure the fake reports as a JSON-RPC error (code, message, data)."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


@dataclass
class Hang:
    """Returned by `call` when the scenario wants the handler to hang (after side effects)."""

    seconds: float


@dataclass
class ToolResponse:
    """A transport-neutral tool result. `server.py` turns it into an MCP CallToolResult."""

    text: str | None = None
    structured: Any = None
    is_error: bool = False
    content: list[dict[str, Any]] | None = None  # raw content blocks (overrides `text`)
    meta: dict[str, Any] | None = None
    progress: list[str] = field(default_factory=list)
    logs: list[Any] = field(default_factory=list)


@dataclass
class Job:
    uuid: str
    function_name: str
    inputs: dict[str, Any]
    estimate: int
    cost: int
    provider: str
    created_ms: int
    schedule: tuple[str, ...]
    polls: int = 0
    status: str = "submitted"
    finished_ms: int | None = None
    outputs: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    refunded: int = 0
    list_calls_seen: int = 0
    concept_id: str | None = None


class FakeStudioTwin:
    def __init__(self, scenario: Scenario | None = None, *, storage_base: str = DEFAULT_STORAGE_BASE):
        self.scenario = scenario or Scenario()
        self.storage_base = storage_base.rstrip("/")
        self.clock_ms = int(EPOCH.timestamp() * 1000)
        self.balance = self.scenario.wallet_balance
        self.jobs: dict[str, Job] = {}
        self.assets: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.concepts: dict[str, dict[str, Any]] = {}
        self.ledger: list[dict[str, Any]] = []
        self.vp_submissions: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.list_job_calls = 0
        self.tools_call_count = 0
        self.storage_objects: dict[str, bytes] = {}
        self.signed: dict[str, dict[str, Any]] = {}  # signature -> {key, expires_ms}
        self._seq = 0
        self._seed_library()

    # ------------------------------------------------------------------ ids / clock / urls
    def _next_uuid(self, kind: int) -> str:
        self._seq += 1
        return f"{kind:08x}-{self._seq:04x}-4000-8000-{self._seq:012x}"

    def now_iso(self, ms: int | None = None) -> str:
        ms = self.clock_ms if ms is None else ms
        return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"

    def advance(self, seconds: float) -> None:
        self.clock_ms += int(seconds * 1000)

    def _s3_uri(self, key: str) -> str:
        return f"s3://{STORAGE_BUCKET}/{key}"

    def _store(self, key: str, media_rel: str | None) -> None:
        if key not in self.storage_objects:
            data = b""
            if media_rel and (MEDIA_DIR / media_rel).is_file():
                data = (MEDIA_DIR / media_rel).read_bytes()
            self.storage_objects[key] = data

    def signed_url(self, key: str, *, canary_id: str = "job_output_signed_url", ttl: int | None = None) -> str:
        ttl = self.scenario.signed_url_ttl_seconds if ttl is None else ttl
        self._seq += 1
        sig = f"{canaries.value(canary_id)}-{self._seq:06d}"
        self.signed[sig] = {"key": key, "expires_ms": self.clock_ms + ttl * 1000}
        stamp = datetime.fromtimestamp(self.clock_ms / 1000, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return (f"{self.storage_base}/{key}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date={stamp}"
                f"&X-Amz-Expires={ttl}&X-Amz-Signature={sig}")

    def fetch_signed(self, url: str) -> bytes:
        """Simulate an object-store GET of a signed URL (raises PermissionError when expired)."""
        match = re.search(r"X-Amz-Signature=([^&]+)", url)
        if not match or match.group(1) not in self.signed:
            raise PermissionError("403 SignatureDoesNotMatch")
        grant = self.signed[match.group(1)]
        if self.clock_ms >= grant["expires_ms"]:
            raise PermissionError("403 Request has expired")
        return self.storage_objects.get(grant["key"], b"")

    # ------------------------------------------------------------------ library
    def _new_asset(self, name: str, category: str, source: str, *, media_rel: str | None = None,
                   key: str | None = None, pinned: bool = False, uuid: str | None = None) -> dict[str, Any]:
        uuid = uuid or self._next_uuid(0xA55E7)
        key = key or f"users/{USER_ID}/assets/{uuid}/{name}"
        self._store(key, media_rel)
        asset = {"uuid": uuid, "name": name, "type": category, "source": source, "pinned": pinned,
                 "createdAt": self.now_iso(), "s3Uri": self._s3_uri(key)}
        self.assets[uuid] = asset
        return asset

    def _seed_library(self) -> None:
        self._new_asset("hero-reference.png", "image", "user", media_rel="image/concept-64.png", pinned=True)
        self._new_asset("crate.glb", "3d_model", "user", media_rel="model/static-cube.glb")
        self._new_asset("walker.glb", "3d_model", "generated", media_rel="model/rigged-animated.glb")
        self._new_asset("wind.wav", "audio", "generated", media_rel="audio/tone-48k.wav")
        self._new_asset("turntable.mp4", "video", "user", media_rel="video/testsrc-32.mp4")

    def _lean_asset(self, a: dict[str, Any]) -> dict[str, Any]:
        return {k: a[k] for k in ("uuid", "name", "type", "source", "pinned", "createdAt", "s3Uri")}

    # ------------------------------------------------------------------ discovery
    def visible_tools(self) -> list[dict[str, Any]]:
        out = catalog.tools()
        if self.scenario.schema_drift_tool:
            out = [catalog.drifted(t) if t["name"] == self.scenario.schema_drift_tool else t for t in out]
        if self.unclassified_visible():
            out.append(catalog.tool(catalog.UNCLASSIFIED_TOOL["name"]))
        return out

    def unclassified_visible(self) -> bool:
        s = self.scenario
        if s.include_unclassified_tool:
            return True
        return s.unclassified_tool_after_calls is not None and self.tools_call_count >= s.unclassified_tool_after_calls

    def instructions(self) -> str:
        return catalog.capture()["instructions"]

    # ------------------------------------------------------------------ dispatch
    def call(self, name: str, args: dict[str, Any] | None) -> ToolResponse | Hang:
        """Execute one tools/call. Raises ProtocolFailure for JSON-RPC-level errors."""
        args = dict(args or {})
        self.tools_call_count += 1
        self.clock_ms += 1000
        self.calls.append({"name": name, "args": copy.deepcopy(args), "at": self.now_iso()})
        visible = {t["name"] for t in self.visible_tools()}
        try:
            if name not in visible:
                raise ToolFailure(f"Unknown tool: {name}. Call tools/list for available tools.")
            if name in catalog.PLATFORM_TOOLS:
                resp = getattr(self, "_t_" + name.removeprefix("studiotwin_"))(args)
            elif name.startswith(catalog.CONCEPT_PREFIX):
                resp = self._concept(name.removeprefix(catalog.CONCEPT_PREFIX), args)
            else:
                resp = self._generation(name, args)
        except ToolFailure as exc:
            resp = ToolResponse(text=str(exc), is_error=True)
        if isinstance(resp, Hang):
            return resp
        if self.scenario.secret_channels:
            self._add_secret_channels(name, args, resp)
        else:
            if self.scenario.emit_progress:
                resp.progress.append(f"{name}: accepted")
            if self.scenario.emit_logs:
                resp.logs.append({"event": "tools/call", "tool": name})
        return resp

    # ------------------------------------------------------------------ money helpers
    def estimate_for(self, function_name: str, inputs: dict[str, Any]) -> int:
        if function_name == catalog.UNCLASSIFIED_TOOL["name"]:
            return catalog.UNCLASSIFIED_TOOL_COST
        fixed = catalog.fixed_cost(function_name)
        if fixed is not None:
            return fixed
        if function_name == "concept-lab-img-fn" and inputs.get("sourceAsset"):
            return ESTIMATES[function_name] + 2
        return ESTIMATES.get(function_name, 10)

    def _run_price(self, function_name: str, inputs: dict[str, Any]) -> tuple[int, str]:
        s = self.scenario
        estimate = self.estimate_for(function_name, inputs)
        applies = s.price_change_tools is None or function_name in s.price_change_tools
        if applies and estimate > 0:
            return estimate + s.price_delta, s.run_provider
        return estimate, s.estimate_provider

    def _create_job(self, function_name: str, inputs: dict[str, Any], *, max_credits: Any = None,
                    concept_id: str | None = None) -> Job:
        s = self.scenario
        estimate = self.estimate_for(function_name, inputs)
        cost, provider = self._run_price(function_name, inputs)
        if s.server_max_credits and max_credits is not None and cost > max_credits:
            self.ledger.append({"event": "rejected_price_exceeds_max", "function": function_name,
                                "cost": cost, "maxCredits": max_credits, "debited": 0})
            raise ToolFailure(json.dumps({"code": "PRICE_EXCEEDS_MAX", "message":
                                          f"Computed cost {cost} exceeds maxCredits {max_credits}; nothing was charged.",
                                          "computedCredits": cost, "maxCredits": max_credits}))
        if self.balance < cost:
            raise ToolFailure(f"Error 40001: insufficient credits (balance {self.balance}, required {cost}).")
        uuid = self._next_uuid(0x10B5)
        job = Job(uuid=uuid, function_name=function_name, inputs=copy.deepcopy(inputs), estimate=estimate,
                  cost=cost, provider=provider, created_ms=self.clock_ms, schedule=tuple(s.job_schedule),
                  concept_id=concept_id)
        self.jobs[uuid] = job
        self.balance -= cost
        self.ledger.append({"event": "debit", "jobId": uuid, "function": function_name, "credits": cost,
                            "estimate": estimate, "provider": provider})
        self.vp_submissions.append({"jobId": uuid, "functionName": function_name, "inputs": copy.deepcopy(inputs)})
        return job

    # ------------------------------------------------------------------ generation tools
    def _generation(self, name: str, args: dict[str, Any]) -> ToolResponse | Hang:
        tool_def = catalog.tool(name) if name != self.scenario.schema_drift_tool else catalog.drifted(catalog.tool(name))
        max_credits = args.pop("maxCredits", None)
        missing = [k for k in tool_def["inputSchema"].get("required", []) if k not in args]
        if missing:
            raise ToolFailure(f"Invalid inputs for {name}: missing required field '{missing[0]}'.")
        job = self._create_job(name, args, max_credits=max_credits)
        style = self.scenario.ack_style
        if style == "live_text_json":
            return ToolResponse(text=json.dumps({
                "jobId": job.uuid, "functionName": name, "cost": job.cost, "status": "queued",
                "next": "Poll studiotwin_get_job_status with this jobId until COMPLETE, then use the output URLs."}))
        if style == "prose_no_id":
            return ToolResponse(text="Your generation request was received and is being processed.")
        if style == "empty_content":
            return ToolResponse(content=[])
        if style == "malformed_json":
            return ToolResponse(text='{"jobId": "' + job.uuid[:13] + '", "functionName": "' + name + '", "co')
        if style == "protocol_error_after_create":
            raise ProtocolFailure(-32603, "Upstream connection reset after submission")
        if style == "timeout_after_create":
            return Hang(self.scenario.hang_seconds)
        raise AssertionError(style)  # pragma: no cover

    # ------------------------------------------------------------------ job progression
    def _advance_job(self, job: Job) -> None:
        if job.status in ("done", "failed", "cancelled"):
            return
        idx = min(job.polls, len(job.schedule) - 1)
        job.polls += 1
        status = job.schedule[idx]
        job.status = status
        if status == "done":
            job.finished_ms = self.clock_ms
            job.outputs = self._outputs_for(job)
            self._register_generated_assets(job)
            self._settle(job)
        elif status == "failed":
            job.finished_ms = self.clock_ms
            job.error = {"code": "GENERATION_FAILED", "message": "The generation provider failed. Credits were refunded."}
            self._refund(job, job.cost)

    def _settle(self, job: Job) -> None:
        self.ledger.append({"event": "settled", "jobId": job.uuid, "finalDebit": job.cost, "estimate": job.estimate})

    def _refund(self, job: Job, amount: int) -> None:
        if job.refunded:
            return
        job.refunded = amount
        self.balance += amount
        self.ledger.append({"event": "refund", "jobId": job.uuid, "credits": amount})

    def _out_key(self, job: Job, key: str) -> str:
        return f"vp-jobs/{job.uuid}/{key}"

    def _outputs_for(self, job: Job) -> dict[str, Any]:
        name = job.function_name
        tool_def = catalog.tool(name)
        schema = tool_def.get("outputSchema") or {}
        props: dict[str, Any] = schema.get("properties", {})
        required = set(schema.get("required", []))
        keys = [k for k in props if self.scenario.optional_outputs == "all" or k in required]
        out: dict[str, Any] = {}
        for key in keys:
            spec = props[key]
            desc = (spec.get("description") or "")
            typ = spec.get("type")
            obj_key = self._out_key(job, key)
            media = _MEDIA_BY_TOOL_KEY.get((name, key)) or _MEDIA_BY_KEY.get(key)
            if typ == "string":
                special = _SCALAR_OUTPUTS.get(key)
                if special is not None:
                    out[key] = special
                elif "s3://" in desc or "S3 URI" in desc:
                    # Bare storage URI (D18): not an asset, needs privileged resolution.
                    self._store(obj_key, media)
                    out[key] = self._canary_s3(obj_key)
                else:
                    self._store(obj_key, media)
                    out[key] = self.signed_url(obj_key)
            elif typ == "number":
                out[key] = _NUMERIC_OUTPUTS.get(key, 1)
            elif typ == "boolean":
                out[key] = True
            elif typ == "array":
                self._store(obj_key, media)
                out[key] = [self._canary_s3(obj_key)]
            elif typ == "object":
                if key == "s3Uris":
                    out[key] = {role: self._canary_s3(self._out_key(job, role)) for role in
                                ("basecolor", "normal", "roughness", "metalness")}
                elif key == "prompt":
                    out[key] = {"user": job.inputs.get("prompt", ""), "effective": job.inputs.get("prompt", "")}
                else:
                    out[key] = {"provider": job.provider, "fixture": True}
        if name == "tripo-auto-rig" and self.scenario.optional_outputs == "required_only":
            out = {"metadata": {"compatible": False, "reason": "fixture: no rig returned"}}
        return out

    def _canary_s3(self, key: str) -> str:
        # Storage URIs carry the storage canary in their path so leaks of raw s3:// are greppable.
        return f"s3://{STORAGE_BUCKET}/{key}/{canaries.value('job_output_storage_uri')}"

    def _register_generated_assets(self, job: Job) -> None:
        for key, value in (job.outputs or {}).items():
            if isinstance(value, str) and value.startswith(self.storage_base):
                media = _MEDIA_BY_TOOL_KEY.get((job.function_name, key)) or _MEDIA_BY_KEY.get(key)
                ext = (media or "x.bin").rsplit(".", 1)[-1]
                self._new_asset(f"{job.function_name}-{key}.{ext}", _CATEGORY_BY_EXT.get(ext, "unknown"),
                                "generated", media_rel=media, key=self._out_key(job, key))

    def _client_status(self, status: str) -> str:
        status = "queued" if status == "submitted" else status
        return _DESCRIBED_STATUS[status] if self.scenario.status_vocabulary == "described" else status

    def _timestamp(self, ms: int, index: int) -> Any:
        if self.scenario.timestamp_style == "iso":
            return self.now_iso(ms)
        forms = (
            lambda: self.now_iso(ms),
            lambda: datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=2))).isoformat(),
            lambda: ms,
            lambda: {"$date": self.now_iso(ms)},
        )
        return forms[index % len(forms)]()

    def _job_view(self, job: Job, index: int = 0) -> dict[str, Any]:
        view: dict[str, Any] = {
            "uuid": job.uuid,
            "status": self._client_status(job.status),
            "createdAt": self._timestamp(job.created_ms, index),
            "finishedAt": self._timestamp(job.finished_ms, index + 1) if job.finished_ms else None,
            "outputs": job.outputs or {},
        }
        if job.error:
            view["error"] = job.error
        if self.scenario.expose_settlement_evidence and job.status in ("done", "failed", "cancelled"):
            view["settlement"] = {
                "kind": "fixture-ledger-v1",
                "ledgerRef": f"fixture-ledger-{job.uuid}",
                "finalDebitCredits": job.cost - job.refunded,
                "refundCredits": job.refunded,
            }
        return view

    # ------------------------------------------------------------------ platform tools
    def _t_get_job_status(self, args: dict[str, Any]) -> ToolResponse:
        job_id = args.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise ToolFailure("jobId (string) is required.")
        job = self.jobs.get(job_id)
        if job is None:
            raise ToolFailure("VP Job not found")
        self._advance_job(job)
        if self.scenario.malformed == "status_not_json":
            return ToolResponse(text="<html><head><title>502 Bad Gateway</title></head><body>upstream</body></html>")
        return ToolResponse(text=json.dumps(self._job_view(job)))

    def _t_estimate_cost(self, args: dict[str, Any]) -> ToolResponse:
        fn = args.get("functionName")
        if not isinstance(fn, str) or not fn:
            raise ToolFailure("functionName (string) is required.")
        if fn not in {t["name"] for t in self.visible_tools()} or fn in catalog.PLATFORM_TOOLS or fn.startswith(catalog.CONCEPT_PREFIX):
            if fn != "concept-lab-img-fn":
                raise ToolFailure(f"Function {fn} is not available for execution")
        inputs = args.get("inputs") or {}
        est = self.estimate_for(fn, inputs)
        self.ledger.append({"event": "estimate", "function": fn, "estimate": est, "provider": self.scenario.estimate_provider})
        return ToolResponse(text=json.dumps({"functionName": fn, "estimatedCost": est, "providerAvailable": True,
                                             "walletBalance": self.balance, "canRun": self.balance >= est}))

    def _t_get_credit_balance(self, args: dict[str, Any]) -> ToolResponse:
        return ToolResponse(text=json.dumps({"balance": self.balance}))

    def _t_list_my_jobs(self, args: dict[str, Any]) -> ToolResponse:
        self.list_job_calls += 1
        limit = args.get("limit") if isinstance(args.get("limit"), (int, float)) else 10
        offset = args.get("offset") if isinstance(args.get("offset"), (int, float)) else 0
        delay = self.scenario.list_visibility_delay
        visible = []
        for job in sorted(self.jobs.values(), key=lambda j: j.created_ms, reverse=True):
            job.list_calls_seen += 1
            if job.list_calls_seen > delay:
                visible.append(job)
        page = visible[int(offset): int(offset) + int(limit)]
        items = []
        for i, job in enumerate(page):
            item = self._job_view(job, i)
            item.update({"functionName": job.function_name, "cost": job.cost, "userId": USER_ID,
                         "jobId": f"internal-{job.uuid[-6:]}", "inputs": job.inputs})
            items.append(item)
        return ToolResponse(text=json.dumps(items))

    def _t_cancel_job(self, args: dict[str, Any]) -> ToolResponse:
        job_id = args.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise ToolFailure("jobId (string) is required.")
        job = self.jobs.get(job_id)
        if job is None:
            raise ToolFailure("VP Job not found")
        if job.status not in ("submitted", "queued"):
            raise ToolFailure(f"Job cannot be cancelled in status '{self._client_status(job.status)}'.")
        job.status = "cancelled"
        job.finished_ms = self.clock_ms
        self._refund(job, job.cost)
        return ToolResponse(text=json.dumps({"jobId": job_id, "status": "cancelled"}))

    def _t_list_my_assets(self, args: dict[str, Any]) -> ToolResponse:
        allowed = ["image", "image_sequence", "3d_model", "animation", "audio", "video", "unknown", "jpg", "png"]
        typ = args.get("type")
        if typ is not None and typ not in allowed:
            raise ToolFailure(f"type must be one of: {', '.join(allowed)}.")
        assets = list(self.assets.values())
        if typ in ("jpg", "png"):
            assets = [a for a in assets if a["name"].lower().endswith("." + typ)]
        elif typ is not None:
            assets = [a for a in assets if a["type"] == typ]
        assets.sort(key=lambda a: (not a["pinned"],))
        return ToolResponse(text=json.dumps({"assets": [self._lean_asset(a) for a in assets]}))

    def _t_upload_asset(self, args: dict[str, Any]) -> ToolResponse:
        uuid = self._next_uuid(0x0B10AD)
        key = f"users/{USER_ID}/assets/{uuid}"
        self.uploads[uuid] = {"uuid": uuid, "status": "uploading", "files": {}, "key": key}
        fields = {
            "bucket": STORAGE_BUCKET,
            "key": key + "/${filename}",
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": canaries.value("upload_post_credential") + "/20261030/us-east-1/s3/aws4_request",
            "X-Amz-Date": "20261030T080000Z",
            "X-Amz-Security-Token": canaries.value("upload_post_security_token"),
            "Policy": canaries.value("upload_post_policy"),
            "X-Amz-Signature": canaries.value("upload_post_signature"),
        }
        url = f"{self.storage_base}/upload?fixture-post={canaries.value('upload_post_url')}"
        return ToolResponse(text=json.dumps({"uuid": uuid, "preSignedPost": {"url": url, "fields": fields}}))

    def put_upload(self, upload_id: str, filename: str, data: bytes) -> None:
        """Simulate the browser/CLI-free presigned POST the gateway performs."""
        session = self.uploads[upload_id]
        if session["status"] != "uploading":
            raise PermissionError("upload session closed")
        name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        session["files"][name] = bytes(data)
        self.storage_objects[f"{session['key']}/{name}"] = bytes(data)

    def _t_complete_asset_upload(self, args: dict[str, Any]) -> ToolResponse:
        sid = args.get("uploadSessionId")
        if not isinstance(sid, str) or not sid:
            raise ToolFailure("uploadSessionId (string) is required.")
        session = self.uploads.get(sid)
        if session is None:
            raise ToolFailure("Upload session not found")
        if session["status"] == "closed":
            raise ToolFailure("Upload session is already closed. Create a new upload session to upload files.")
        entries = args.get("entries")
        created = []
        for name, data in session["files"].items():
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext == "tar":
                if not entries:
                    raise ToolFailure("entries are required to complete a tar upload.")
                if not _tar_entries_match(data, entries):
                    raise ToolFailure("entries do not match the uploaded tar archive.")
                category = "image_sequence"
            else:
                category = _CATEGORY_BY_EXT.get(ext, "unknown")
                if category == "animation":
                    category = "unknown"
            created.append(self._new_asset(name, category, "user", key=f"{session['key']}/{name}"))
        session["status"] = "closed"
        return ToolResponse(text=json.dumps({"uuid": sid, "status": "closed", "assetIds": [a["uuid"] for a in created],
                                             "assets": [self._lean_asset(a) for a in created]}))

    def _t_resolve_asset(self, args: dict[str, Any]) -> ToolResponse:
        aid = args.get("assetId")
        if not isinstance(aid, str) or not aid:
            raise ToolFailure("assetId (string) is required.")
        asset = self.assets.get(aid)
        if asset is None:
            raise ToolFailure(f"Asset {aid} not found")
        key = asset["s3Uri"].split(f"s3://{STORAGE_BUCKET}/", 1)[1]
        url = self.signed_url(key, canary_id="resolve_download_url", ttl=3600)
        body = dict(self._lean_asset(asset))
        body["s3Uri"] = asset["s3Uri"] + "#" + canaries.value("asset_storage_uri")
        body.update({"downloadUrl": url, "expiresInSeconds": 3600})
        return ToolResponse(text=json.dumps(body))

    # ------------------------------------------------------------------ Concepts
    def _concept(self, op: str, args: dict[str, Any]) -> ToolResponse:
        handler = getattr(self, "_c_" + op)
        result = handler(args)
        if self.scenario.malformed == "concept_schema_violation" and isinstance(result, dict) and "assets" in result:
            result = {k: v for k, v in result.items() if k != "assets"}
            result["fixtureUnexpected"] = True
        return ToolResponse(text=json.dumps(result), structured=result)

    def _require_concept(self, args: dict[str, Any], allowed: tuple[str, ...] = ("conceptId",)) -> dict[str, Any]:
        extra = [k for k in args if k not in allowed]
        if extra:
            raise ToolFailure(f"Unexpected argument: {extra[0]}.")
        cid = args.get("conceptId")
        if not isinstance(cid, str) or not UUID_RE.match(cid):
            raise ToolFailure("conceptId must be a valid UUID.")
        concept = self.concepts.get(cid)
        if concept is None:
            raise ToolFailure(f"Concept {cid} not found")
        return concept

    def _new_concept(self, concept_type: str, name: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
        if concept_type not in ("object", "character", "environmentMap", "world"):
            raise ToolFailure("Invalid arguments: conceptType: conceptType must be one of the following values: object, character, environmentMap, world")
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            raise ToolFailure("Invalid arguments: name: name must be longer than or equal to 1 characters")
        uuid = self._next_uuid(0xC0CE)
        concept = {"uuid": uuid, "conceptType": concept_type, "name": name, "ownerOrganizationId": ORG_ID,
                   "createdByUserId": USER_ID, "sharedWithUsers": [], "pendingInvites": [], "assets": [],
                   "resultJobs": [], "executionJobId": None, "thumbnailAssetId": None,
                   "metadata": dict(metadata or {}), "lifecycleStatus": "draft", "sourceConceptId": None,
                   "createdAt": self.now_iso(), "updatedAt": self.now_iso()}
        self.concepts[uuid] = concept
        return concept

    def _reconcile(self, concept: dict[str, Any]) -> None:
        for entry in concept["assets"]:
            op = entry["operation"]
            job_id = op.get("vpJobId")
            if entry["assetId"] is None and job_id and "reconciledAt" not in op:
                job = self.jobs[job_id]
                self._advance_job(job)
                if job.status == "done":
                    asset = self._new_asset(f"concept-{job.uuid[-6:]}.png", "image", "generated",
                                            media_rel="image/concept-64.png")
                    for other in concept["assets"]:
                        other["isActive"] = False
                    entry.update({"assetId": asset["uuid"], "isActive": True, "createdAt": self.now_iso()})
                    op["reconciledAt"] = self.now_iso()
                elif job.status in ("failed", "cancelled"):
                    op["reconciledAt"] = self.now_iso()
                    op["error"] = dict(job.error or {"code": "CANCELLED", "message": "Operation cancelled."})
        concept["updatedAt"] = self.now_iso()

    def _idle(self, concept: dict[str, Any]) -> bool:
        return not any(e["assetId"] is None and "reconciledAt" not in e["operation"] for e in concept["assets"])

    def _asset_id(self, ref: Any) -> str:
        match = ASSET_REF_RE.match(ref) if isinstance(ref, str) else None
        if not match:
            raise ToolFailure("Invalid arguments: assetId must be an asset UUID or vpc::assets/<uuid>.")
        return match.group(1)

    def _queue_image(self, concept: dict[str, Any], action: str, job_inputs: dict[str, Any]) -> None:
        if concept["lifecycleStatus"] != "draft" or not self._idle(concept):
            raise ToolFailure("Concept already has an image operation in progress.")
        if not isinstance(job_inputs, dict) or "prompt" not in job_inputs or "modelId" not in job_inputs:
            raise ToolFailure("Invalid arguments: jobInputs.prompt: prompt should not be null or undefined")
        source_id = None
        if action == "edit":
            if self.scenario.concept_active_swap_on_edit:
                completed = [e for e in concept["assets"] if e["assetId"]]
                if len(completed) >= 2:
                    current = next(i for i, e in enumerate(completed) if e["isActive"])
                    for e in completed:
                        e["isActive"] = False
                    completed[(current + 1) % len(completed)]["isActive"] = True
            active = next((e for e in concept["assets"] if e["isActive"] and e["assetId"]), None)
            if active is None:
                raise ToolFailure("Concept has no active asset to edit")
            source_id = active["assetId"]
        elif job_inputs.get("sourceAsset"):
            source_id = self._asset_id(job_inputs["sourceAsset"])
        source_s3 = None
        if source_id:
            asset = self.assets.get(source_id)
            if asset is None:
                raise ToolFailure(f"Asset {source_id} not found")
            source_s3 = asset["s3Uri"]
        inputs = concept_inputs.build_op_inputs(action, job_inputs, source_s3, concept["conceptType"])
        job = self._create_job(concept_inputs.CONCEPT_FUNCTION, inputs, concept_id=concept["uuid"])
        concept["assets"].append({"assetId": None, "isActive": False, "operation": {
            "type": action, "vpJobId": job.uuid, "submittedAt": self.now_iso(),
            "prompt": copy.deepcopy(job_inputs["prompt"]), "modelId": job_inputs["modelId"],
            "sourceAssetId": source_id}})
        concept["updatedAt"] = self.now_iso()

    def _c_create(self, args: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(self._new_concept(args.get("conceptType"), args.get("name"), args.get("metadata")))

    def _c_create_and_generate(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._new_concept(args.get("conceptType"), args.get("name"), args.get("metadata"))
        self._queue_image(concept, "generate", args.get("jobInputs"))
        return copy.deepcopy(concept)

    def _c_list(self, args: dict[str, Any]) -> dict[str, Any]:
        extra = [k for k in args if k not in ("limit", "offset")]
        if extra:
            raise ToolFailure(f"Unexpected argument: {extra[0]}.")
        limit, offset = int(args.get("limit", 20)), int(args.get("offset", 0))
        if not 1 <= limit <= 100 or offset < 0:
            raise ToolFailure("limit must be an integer in the range 1-100.")
        items = sorted(self.concepts.values(), key=lambda c: c["updatedAt"], reverse=True)[offset: offset + limit]
        return {"concepts": copy.deepcopy(items)}

    def _c_get(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args)
        self._reconcile(concept)
        return copy.deepcopy(concept)

    def _c_get_status(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args)
        self._reconcile(concept)
        op_entries = [e for e in concept["assets"] if e["operation"].get("vpJobId")]
        operation = None
        if op_entries:
            last = op_entries[-1]
            job = self.jobs[last["operation"]["vpJobId"]]
            status = "queued" if job.status == "submitted" else job.status
            operation = {"vpJobId": job.uuid, "action": last["operation"]["type"], "status": status}
            if status in ("failed", "cancelled"):
                operation["error"] = dict(job.error or {"code": "CANCELLED", "message": "Operation cancelled."})
        return {"conceptId": concept["uuid"], "lifecycleStatus": concept["lifecycleStatus"],
                "operation": operation, "resultJobs": list(concept["resultJobs"])}

    def _c_attach_asset(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args, ("conceptId", "assetId", "makeActive"))
        aid = self._asset_id(args.get("assetId"))
        if aid not in self.assets:
            raise ToolFailure(f"Asset {aid} not found")
        if not self._idle(concept):
            raise ToolFailure("Concept already has an image operation in progress.")
        make_active = bool(args.get("makeActive", False))
        if make_active:
            for e in concept["assets"]:
                e["isActive"] = False
        concept["assets"].append({"assetId": aid, "isActive": make_active, "createdAt": self.now_iso(),
                                  "operation": {"type": "upload"}})
        concept["updatedAt"] = self.now_iso()
        return copy.deepcopy(concept)

    def _c_generate(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args, ("conceptId", "jobInputs"))
        self._queue_image(concept, "generate", args.get("jobInputs"))
        return copy.deepcopy(concept)

    def _c_edit(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args, ("conceptId", "jobInputs"))
        self._queue_image(concept, "edit", args.get("jobInputs"))
        return copy.deepcopy(concept)

    def _c_clone(self, args: dict[str, Any]) -> dict[str, Any]:
        source = self._require_concept(args)
        self._reconcile(source)
        clone = self._new_concept(source["conceptType"], source["name"], None)
        clone["sourceConceptId"] = source["uuid"]
        active = next((e for e in source["assets"] if e["isActive"] and e["assetId"]), None)
        if active:
            clone["assets"].append({"assetId": active["assetId"], "isActive": True, "createdAt": self.now_iso(),
                                    "operation": {"type": "clone", "sourceAssetId": active["assetId"]}})
        return copy.deepcopy(clone)

    def _c_set_active_asset(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args, ("conceptId", "assetId"))
        aid = self._asset_id(args.get("assetId"))
        target = next((e for e in concept["assets"] if e["assetId"] == aid), None)
        if target is None:
            raise ToolFailure("Asset is not part of this Concept")
        for e in concept["assets"]:
            e["isActive"] = e is target
        concept["updatedAt"] = self.now_iso()
        return copy.deepcopy(concept)

    def _c_update(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args, ("conceptId", "name", "metadata"))
        if "name" in args:
            if not isinstance(args["name"], str) or not 1 <= len(args["name"]) <= 200:
                raise ToolFailure("Invalid arguments: name: name must be longer than or equal to 1 characters")
            concept["name"] = args["name"]
        if "metadata" in args:
            concept["metadata"] = dict(args["metadata"])  # replaces, never merges
        concept["updatedAt"] = self.now_iso()
        return copy.deepcopy(concept)

    def _c_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        concept = self._require_concept(args)
        deleted = []
        for e in concept["assets"]:
            aid = e["assetId"]
            if aid and self.assets.get(aid, {}).get("source") == "generated" and e["operation"]["type"] in ("generate", "edit"):
                deleted.append(aid)
                self.assets.pop(aid, None)
        del self.concepts[concept["uuid"]]
        return {"uuid": concept["uuid"], "deleted": True, "deletedAssetIds": deleted}

    # ------------------------------------------------------------------ secret channels
    def _canary_url(self, canary_id: str) -> str:
        return f"https://fixture-bucket.s3.invalid/leak/{canary_id}?X-Amz-Signature={canaries.value(canary_id)}"

    def _add_secret_channels(self, name: str, args: dict[str, Any], resp: ToolResponse) -> None:
        if resp.is_error:
            if self.scenario.secret_error == "protocol":
                raise ProtocolFailure(-32002, f"Upstream fetch failed for {self._canary_url('protocol_error_message')}",
                                      {"presignedPost": {"X-Amz-Signature": canaries.value("protocol_error_data")}})
            resp.text = (resp.text or "") + f" (diagnostic: {self._canary_url('error_result_text')})"
        base_blocks = resp.content if resp.content is not None else ([{"type": "text", "text": resp.text}] if resp.text is not None else [])
        embedded = json.dumps({"debug": {"previewUrl": self._canary_url("text_embedded_json")}})
        fenced = json.dumps({"downloadUrl": self._canary_url("text_fenced_json")}, indent=1)
        extra = [
            {"type": "text", "text": f"Your file is ready at {self._canary_url('text_prose_url')} for one hour."},
            {"type": "text", "text": f"Debug payload follows {embedded} end of payload."},
            {"type": "text", "text": f"```json\n{fenced}\n```"},
            {"type": "resource_link", "name": "fixture-output", "uri": self._canary_url("resource_link_uri"),
             "mimeType": "image/png"},
            {"type": "resource", "resource": {"uri": self._canary_url("embedded_resource_uri"), "mimeType": "text/plain",
                                              "text": f"see {self._canary_url('embedded_resource_text')}"}},
            {"type": "resource", "resource": {"uri": "fixture://blob/1", "mimeType": "application/octet-stream",
                                              "blob": canaries.blob_b64()}},
            {"type": "text", "text": "content with metadata",
             "_meta": {"fixture/sourceUrl": self._canary_url("content_meta")}},
        ]
        resp.content = list(base_blocks) + extra
        resp.meta = {"fixture/debugAuthorization": "Bearer " + canaries.value("result_meta")}
        if name in catalog.PLATFORM_TOOLS and not resp.is_error:
            resp.structured = {"fixtureDebug": {
                "signedUrl": self._canary_url("structured_content"),
                "presignedPost": {"fields": {"X-Amz-Signature": canaries.value("structured_content_post_signature")}}}}
        resp.progress.append(f"Downloading from {self._canary_url('progress_message')}")
        resp.logs.append({"event": "fetch", "url": self._canary_url("log_message")})


_SCALAR_OUTPUTS = {
    "rigCheckTaskId": "fixture-rig-check-task-0001",
    "rigType": "biped",
    "contentType": "audio/wav",
    "mode": "generate",
    "model": "gpt-image-2",
    "quality": "medium",
    "size": "1024x1024",
    "sizeRequested": "1024x1024",
    "requestId": "fixture-request-0001",
    "generatedOutput": "// fixture dart translation\nvoid main() {}",
    "conceptType": "object",
}
_NUMERIC_OUTPUTS = {
    "sizeBytes": 48044, "creditCost": 0, "providerCredits": 0, "processingTime": 1.5, "seed": 42,
    "hFovDeg": 30.0, "vFovDeg": 20.0, "pitchDeg": 5.0, "rollDeg": 0.0, "yawDeg": 90.0, "sourceAspect": 1.5,
}


def _tar_entries_match(data: bytes, entries: list[dict[str, Any]]) -> bool:
    import tarfile

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
            actual = [{"name": m.name, "offset": m.offset, "size": m.size} for m in tf.getmembers() if m.isfile()]
    except tarfile.TarError:
        return False
    return actual == [{"name": e.get("name"), "offset": e.get("offset"), "size": e.get("size")} for e in entries]
