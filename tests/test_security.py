"""Exercise rejection, bounded work, cancellation and normal MCP behaviour."""

import asyncio
from dataclasses import replace

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.responses import PlainTextResponse

from ensembl_mcp.config import Settings, ConfigurationError
from ensembl_mcp.security import HTTPProtection
from ensembl_mcp.server import create_server, http_options

SETTINGS = Settings("https://core.invalid", search_url="https://search.invalid",
                    allowed_hosts=("mcp.example.org",), allowed_origins=("https://client.example.org",))
INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-03-26", "capabilities": {},
    "clientInfo": {"name": "security-test", "version": "1"}}}


@pytest.mark.parametrize("host,origin,status", [
    ("mcp.example.org", None, 200), ("mcp.example.org:443", "https://client.example.org", 200),
    ("evil.example", None, 421), ("localhost", None, 421),
    ("mcp.example.org", "https://evil.example", 403), ("mcp.example.org", "null", 403),
    ("mcp.example.org", "https://client.example.org.evil.example", 403),
    ("mcp.example.org", "https://mcp.example.org", 403),
])
async def test_host_origin_at_real_mcp_boundary(host, origin, status):
    server = create_server(SETTINGS)
    app = server.http_app(transport="streamable-http", **http_options(SETTINGS))
    headers = {"Host": host, "Accept": "application/json, text/event-stream",
               "X-Forwarded-Host": "mcp.example.org", "X-Forwarded-For": "127.0.0.1"}
    if origin is not None:
        headers["Origin"] = origin
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://192.0.2.10") as client:
            response = await client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == status


async def ok(scope, receive, send):
    await PlainTextResponse("ok")(scope, receive, send)


def http_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://mcp.example.org")


async def test_chunked_body_limit_and_duplicate_headers():
    app = HTTPProtection(ok, replace(SETTINGS, max_request_bytes=8))
    async def chunks():
        yield b"12345"
        yield b"6789"
    async with http_client(app) as client:
        assert (await client.post("/mcp", content=chunks())).status_code == 413
        assert (await client.post("/mcp", content=b"12345678")).status_code == 200
        assert (await client.get("/mcp", headers=[("Host", "mcp.example.org"), ("Host", "evil.example")])).status_code == 421
        assert (await client.get("/mcp", headers=[("Origin", "https://client.example.org")] * 2)).status_code == 403
    assert app.active == 0


async def test_global_rate_limit_cannot_be_bypassed_with_forwarded_ip():
    app = HTTPProtection(ok, replace(SETTINGS, requests_per_minute=1))
    async with http_client(app) as client:
        assert (await client.get("/mcp")).status_code == 200
        response = await client.get("/mcp", headers={"X-Forwarded-For": "203.0.113.12"})
        assert response.status_code == 429 and response.headers["retry-after"] == "1"


async def test_request_concurrency_and_timeout_release_capacity():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def slow(scope, receive, send):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    app = HTTPProtection(slow, replace(SETTINGS, max_concurrent_requests=1, request_timeout_seconds=0.05))
    async with http_client(app) as client:
        pending = asyncio.create_task(client.get("/mcp"))
        await entered.wait()
        assert (await client.get("/mcp")).status_code == 503
        assert (await pending).status_code == 504
        assert cancelled.is_set() and app.active == 0
        app.app = ok
        assert (await client.get("/mcp")).status_code == 200


async def test_slow_request_body_has_total_deadline():
    async def chunks():
        yield b"{"
        await asyncio.Event().wait()
    app = HTTPProtection(ok, replace(SETTINGS, request_timeout_seconds=0.02))
    async with http_client(app) as client:
        assert (await client.post("/mcp", content=chunks())).status_code == 504
    assert app.active == 0


async def test_tool_deadline_and_concurrency_also_apply_to_stdio():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    server = create_server(replace(SETTINGS, max_concurrent_tools=1, tool_timeout_seconds=0.1))
    @server.tool
    async def slow() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "unreachable"
    @server.tool
    async def quick() -> str:
        return "ok"
    async with Client(server) as client:
        pending = asyncio.create_task(client.call_tool("slow", {}))
        await entered.wait()
        with pytest.raises(ToolError, match="server_busy"):
            await client.call_tool("quick", {})
        with pytest.raises(ToolError, match="operation_timeout"):
            await pending
        assert cancelled.is_set()
        assert (await client.call_tool("quick", {})).data == "ok"


@pytest.mark.parametrize("name,value", [
    ("MCP_ALLOWED_HOSTS", "*"), ("MCP_ALLOWED_HOSTS", ""),
    ("MCP_ALLOWED_HOSTS", "https://mcp.example.org"), ("MCP_ALLOWED_HOSTS", "mcp.example.org:443"),
    ("MCP_ALLOWED_ORIGINS", "null"), ("MCP_ALLOWED_ORIGINS", "https://*.example.org"),
    ("MCP_ALLOWED_ORIGINS", "https://client.example.org/"),
    ("MCP_REQUEST_TIMEOUT_SECONDS", "nan"), ("MCP_TOOL_TIMEOUT_SECONDS", "0"),
    ("MCP_REQUESTS_PER_MINUTE", "-1"), ("MCP_MAX_CONCURRENT_TOOLS", "no"),
    ("MCP_MAX_REQUEST_BYTES", "0"),
])
def test_invalid_security_configuration_fails_closed(name, value):
    with pytest.raises(ConfigurationError, match=name):
        Settings.from_env({"ENSEMBL_CORE_GRAPHQL_URL": "https://core.invalid",
                           "ENSEMBL_GENOME_SEARCH_URL": "https://search.invalid", name: value})
