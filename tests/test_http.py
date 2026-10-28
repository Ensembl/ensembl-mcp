"""Exercise actual MCP HTTP messages through the SDK's ASGI app, without TCP."""

import asyncio
import json
from unittest.mock import Mock

import httpx
import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from ensembl_mcp.config import Settings
from ensembl_mcp import server as server_module
from ensembl_mcp.smoke import check_server


def rpc_result(response):
    assert response.status_code == 200, response.text
    if response.headers["content-type"].startswith("application/json"):
        message = response.json()
    else:
        assert response.headers["content-type"].startswith("text/event-stream")
        message = next(
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines() if line.startswith("data: ")
        )
    assert "error" not in message, message
    return message["result"]


@pytest.mark.parametrize("outcome", ["found", "not_found", "upstream_error"])
async def test_http_initialize_list_and_call(genome, brca2, outcome):
    requests = []
    closed = False

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body["operationName"] == "ResolveReferenceGenome":
            return httpx.Response(200, json={"data": {"genomes": [genome]}})
        if outcome == "upstream_error":
            return httpx.Response(200, json={"errors": [{"message": "private-backend secret"}]})
        return httpx.Response(200, json={"data": {"genes": [brca2] if outcome == "found" else []}})

    class Backend(httpx.MockTransport):
        async def aclose(self):
            nonlocal closed
            closed = True
            await super().aclose()

    server = server_module.create_server(
        Settings("http://private-backend.invalid", search_url="https://search.invalid/genomes/v3"), transport=Backend(handler),
    )
    app = server.http_app(path="/mcp", transport="streamable-http", stateless_http=True)
    # ASGITransport deliberately does not run lifespan; run it explicitly so the
    # SDK session manager and shared upstream client match the deployed lifecycle.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost",
            headers={"Accept": "application/json, text/event-stream"},
        ) as client:
            initialized = rpc_result(await client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "offline-http-test", "version": "1.0"},
                },
            }))
            assert initialized["serverInfo"]["name"] == "Ensembl MCP"
            assert "tools" in initialized["capabilities"]
            client.headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
            notification = await client.post("/mcp", json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            assert notification.status_code == 202
            listed = rpc_result(await client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
            }))
            assert {tool["name"] for tool in listed["tools"]} == {"find_gene", "find_genomes", "explain_genome", "get_genome_download_links"}
            assert set(listed["tools"][0]["inputSchema"]["required"]) == {"symbol"}
            assert requests == []
            called = rpc_result(await client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {
                    "name": "find_gene", "arguments": {"symbol": "BRCA2", "species": "Homo sapiens"},
                },
            }))
            assert len(requests) == 2
            assert requests[1]["variables"]["by_symbol"]["genome_id"] == genome["genome_id"]
            if outcome == "upstream_error":
                assert called["isError"]
                assert "upstream_graphql" in str(called)
                assert "private-backend" not in str(called) and "secret" not in str(called)
            else:
                assert not called.get("isError", False)
                assert called["structuredContent"] == {
                    "symbol": "BRCA2", "species": "Homo sapiens", "genome": genome,
                    "genes": [brca2] if outcome == "found" else [], "outcome": outcome,
                }
            invalid = rpc_result(await client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "find_gene", "arguments": {"symbol": "BRCA2"}},
            }))
            assert invalid["isError"]
            assert len(requests) == 2
            assert (await client.post("/", json={})).status_code == 404
        assert not closed
    assert closed


@pytest.mark.parametrize("transport,port", [("stdio", "8000"), ("streamable-http", "8000"), ("streamable-http", "8087")])
def test_entry_point_transport_and_binding(monkeypatch, transport, port):
    monkeypatch.setenv("ENSEMBL_CORE_GRAPHQL_URL", "http://example.invalid")
    monkeypatch.setenv("ENSEMBL_GENOME_SEARCH_URL", "https://search.invalid/genomes/v3")
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    monkeypatch.setenv("MCP_PORT", port)
    server = Mock()
    monkeypatch.setattr(server_module, "create_server", lambda settings: server)
    server_module.main()
    expected = {"transport": transport, "show_banner": False}
    if transport == "streamable-http":
        expected.update(host="0.0.0.0", port=int(port), path="/mcp", stateless_http=True)
    server.run.assert_called_once_with(**expected)


async def test_fastmcp_client_over_http(genome, brca2):
    backend = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "data": {"genomes": [genome], "genes": [brca2]},
    }))
    server = server_module.create_server(Settings("http://example.invalid", search_url="https://search.invalid/genomes/v3"), transport=backend)
    app = server.http_app(path="/mcp", transport="streamable-http", stateless_http=True)

    def client_factory(**kwargs):
        # FastMCP 4's MCP client uses httpx2; the application backend uses HTTPX.
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app), **kwargs)

    transport = StreamableHttpTransport(
        "http://localhost/mcp", httpx_client_factory=client_factory,
    )
    async with asyncio.timeout(10):
        async with app.router.lifespan_context(app):
            async with Client(transport, timeout=5) as client:
                result = await check_server(client)
    assert result.genes[0].model_dump() == brca2
