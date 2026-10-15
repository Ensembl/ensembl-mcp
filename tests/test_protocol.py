import json
import logging

import httpx
import pytest
from fastmcp import Client

from ensembl_mcp.config import Settings
from ensembl_mcp.server import create_server


class TrackingTransport(httpx.MockTransport):
    closed = False

    async def aclose(self):
        self.closed = True
        await super().aclose()


async def test_discovery_call_and_lifecycle(genome, brca2, caplog):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        field = "genomes" if calls[-1]["operationName"] == "ResolveReferenceGenome" else "genes"
        return httpx.Response(200, json={"data": {field: [genome if field == "genomes" else brca2]}})

    transport = TrackingTransport(handler)
    server = create_server(Settings("http://private-cluster.invalid:8000", search_url="https://search.invalid/genomes/v3"), transport=transport)
    caplog.set_level(logging.INFO, logger="ensembl_mcp")
    async with Client(server) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {"find_gene", "find_genomes", "explain_genome", "get_genome_download_links"}
        schema = tools[0].input_schema
        assert set(schema["required"]) == {"symbol"}
        assert set(schema["properties"]) == {"symbol", "species", "genome_id"}
        assert schema["properties"]["symbol"]["type"] == "string"
        assert tools[0].output_schema is not None
        for _ in range(2):
            result = await client.call_tool("find_gene", {"symbol": " BRCA2 ", "species": " Homo sapiens "})
            assert not result.is_error
            assert result.structured_content == {
                "symbol": "BRCA2", "species": "Homo sapiens", "genome": genome,
                "genes": [brca2], "outcome": "found",
            }
            assert "private-cluster" not in str(result.structured_content)
        assert not transport.closed
    assert transport.closed
    assert len(calls) == 4  # Shared client, with no lookup cache.
    assert "operation=find_gene" in caplog.text and "outcome=found" in caplog.text


@pytest.mark.parametrize("arguments", [
    {}, {"symbol": "BRCA2"}, {"species": "Homo sapiens"},
    {"symbol": " ", "species": "Homo sapiens"},
    {"symbol": "BRCA2", "species": "\t"},
    {"symbol": None, "species": "Homo sapiens"},
    {"symbol": 123, "species": "Homo sapiens"},
])
async def test_invalid_protocol_inputs_make_no_request(arguments):
    def handler(request):
        pytest.fail("Invalid inputs must not reach the backend")

    async with Client(create_server(Settings("http://example.invalid", search_url="https://search.invalid/genomes/v3"), transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("find_gene", arguments, raise_on_error=False)
    assert result.is_error
    assert result.structured_content is None


async def test_caller_errors_are_safe_and_cleanup_runs():
    transport = TrackingTransport(lambda request: httpx.Response(200, json={
        "errors": [{"message": "secret trace from http://private-cluster.invalid:8000"}],
    }))
    async with Client(create_server(Settings("http://example.invalid", search_url="https://search.invalid/genomes/v3"), transport=transport)) as client:
        result = await client.call_tool("find_gene", {"symbol": "BRCA2", "species": "Homo sapiens"}, raise_on_error=False)
    assert result.is_error
    text = " ".join(block.text for block in result.content)
    assert "upstream_graphql" in text
    assert "secret" not in text and "private-cluster" not in text and "Traceback" not in text
    assert transport.closed


async def test_protocol_not_found_retains_genome(genome):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": {"genomes": [genome], "genes": []}}))
    async with Client(create_server(Settings("http://example.invalid", search_url="https://search.invalid/genomes/v3"), transport=transport)) as client:
        result = await client.call_tool("find_gene", {"symbol": "ABSENT", "species": "Homo sapiens"})
    assert result.structured_content["outcome"] == "not_found"
    assert result.structured_content["genes"] == []
    assert result.structured_content["genome"] == genome
