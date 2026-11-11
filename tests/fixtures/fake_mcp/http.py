"""Loopback HTTP harness: fake StudioTwin over Streamable HTTP plus a fake object store.

    with serve(FakeStudioTwin(scenario("http_rate_limited"))) as h:
        h.mcp_url          # http://127.0.0.1:<port>/mcp   (needs x-api-key: h.api_key)
        h.storage_base     # signed GET URLs and the presigned POST target live here

Routes:
  POST /mcp                Streamable HTTP MCP (JSON responses like live; SSE when
                           scenario.http_json_response is False). Wrapped by the scenario's
                           auth / 429 / redirect / 5xx behaviour.
  POST /mcp-moved          same-origin redirect target.
  GET  /storage/<key>?...  signed GET; 403 when the signature is unknown or expired.
  POST /storage/upload     presigned multipart POST; every returned field must be echoed.

Binds 127.0.0.1 only. Never contacts StudioTwin.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import parse_qs

import uvicorn
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from . import canaries
from .server import build_server
from .state import FakeStudioTwin

FOREIGN_REDIRECT = "https://redirect-target.invalid/mcp?X-Amz-Signature={}"


@dataclass
class HttpHarness:
    fake: FakeStudioTwin
    host: str
    port: int
    api_key: str
    requests: list[dict[str, Any]]

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return self.base + "/mcp"

    @property
    def storage_base(self) -> str:
        return self.base + "/storage"


class _App:
    def __init__(self, fake: FakeStudioTwin, mcp_app: Any, api_key: str, log: list[dict[str, Any]]):
        self.fake, self.mcp_app, self.api_key, self.log = fake, mcp_app, api_key, log
        self.posts = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.mcp_app(scope, receive, send)
        path = scope["path"]
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        self.log.append({"method": scope["method"], "path": path, "has_api_key": "x-api-key" in headers})
        if path.startswith("/storage"):
            return await self._storage(scope, receive, send)
        if path not in ("/mcp", "/mcp-moved"):
            return await PlainTextResponse("not found", 404)(scope, receive, send)
        s = self.fake.scenario
        if s.http_require_api_key and headers.get("x-api-key") != self.api_key:
            return await PlainTextResponse("Unauthorized", 401)(scope, receive, send)
        if scope["method"] == "POST":
            self.posts += 1
            if self.posts <= s.http_rate_limit_first:
                return await PlainTextResponse("Too Many Requests", 429, headers={"Retry-After": s.http_retry_after})(
                    scope, receive, send)
            if s.http_error_status:
                body = ("upstream error; diagnostic fetch of https://fixture-bucket.s3.invalid/diag?X-Amz-Signature="
                        + canaries.value("http_error_body"))
                return await PlainTextResponse(body, s.http_error_status)(scope, receive, send)
            if s.http_redirect == "foreign":
                loc = FOREIGN_REDIRECT.format(canaries.value("redirect_location"))
                return await Response(status_code=307, headers={"Location": loc})(scope, receive, send)
            if s.http_redirect == "same_origin" and path == "/mcp":
                return await Response(status_code=307, headers={"Location": "/mcp-moved"})(scope, receive, send)
        scope = dict(scope, path="/mcp", raw_path=b"/mcp")
        return await self.mcp_app(scope, receive, send)

    async def _storage(self, scope, receive, send):
        request = Request(scope, receive)
        if scope["method"] == "GET":
            url = self.fake.storage_base + scope["path"].removeprefix("/storage") + "?" + scope.get("query_string", b"").decode()
            try:
                data = self.fake.fetch_signed(url)
            except PermissionError as exc:
                return await PlainTextResponse(str(exc), 403)(scope, receive, send)
            return await Response(data, 200, media_type="application/octet-stream")(scope, receive, send)
        if scope["method"] == "POST" and scope["path"] == "/storage/upload":
            query = parse_qs(scope.get("query_string", b"").decode())
            if query.get("fixture-post") != [canaries.value("upload_post_url")]:
                return await PlainTextResponse("bad upload target", 403)(scope, receive, send)
            form = await request.form()
            required = {"Policy": canaries.value("upload_post_policy"),
                        "X-Amz-Signature": canaries.value("upload_post_signature")}
            if any(form.get(k) != v for k, v in required.items()):
                return await PlainTextResponse("missing or wrong presigned fields", 403)(scope, receive, send)
            key = str(form.get("key", ""))
            upload = form.get("file")
            session_id = next((u for u, s in self.fake.uploads.items() if key.startswith(s["key"])), None)
            if session_id is None or upload is None or isinstance(upload, str):
                return await PlainTextResponse("no session or file", 400)(scope, receive, send)
            data = await upload.read()
            self.fake.put_upload(session_id, upload.filename or "upload.bin", data)
            return await Response(status_code=204)(scope, receive, send)
        return await PlainTextResponse("method not allowed", 405)(scope, receive, send)


def _free_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def serve(fake: FakeStudioTwin | None = None, *, host: str = "127.0.0.1", api_key: str | None = None) -> Iterator[HttpHarness]:
    fake = fake or FakeStudioTwin()
    api_key = api_key or canaries.value("api_key")
    port = _free_port(host)
    fake.storage_base = f"http://{host}:{port}/storage"
    server = build_server(fake)
    mcp_app = server.streamable_http_app(
        stateless_http=fake.scenario.http_json_response,
        json_response=fake.scenario.http_json_response,
        host=host,
    )
    log: list[dict[str, Any]] = []
    app = _App(fake, mcp_app, api_key, log)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with server.session_manager.run():
            yield

    async def asgi(scope, receive, send):
        if scope["type"] == "lifespan":
            message = await receive()
            async with lifespan(None):
                await send({"type": "lifespan.startup.complete"})
                message = await receive()
                assert message["type"] == "lifespan.shutdown"
            await send({"type": "lifespan.shutdown.complete"})
            return
        await app(scope, receive, send)

    config = uvicorn.Config(asgi, host=host, port=port, log_level="warning", lifespan="on", access_log=False)
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, name="fake-studiotwin-http", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("fake StudioTwin HTTP harness failed to start")
        time.sleep(0.01)
    try:
        yield HttpHarness(fake, host, port, api_key, log)
    finally:
        uv.should_exit = True
        thread.join(10)
