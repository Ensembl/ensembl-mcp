"""Offline biological validation and MCP Apps wire-contract tests."""
import copy
import json
from dataclasses import replace
from importlib.resources import files

import httpx
import pytest
from fastmcp import Client

from ensembl_mcp.browser import BrowserView, UI_URI
from ensembl_mcp.config import Settings, ConfigurationError
from ensembl_mcp.server import create_server


@pytest.fixture
def catalogue():
    return {"track_categories": [{"label": "Genes", "track_category_id": "genes", "track_list": [
        {"track_id": "genes", "label": "Protein coding genes", "type": "gene", "trigger": ["track", "gene-pc-fwd"], "display_order": -110, "on_by_default": True},
        {"track_id": "sequence", "label": "Reference sequence", "type": "regular", "trigger": ["track", "contig"], "display_order": 0, "on_by_default": True},
        {"track_id": "variants", "label": "Variants", "type": "variant", "trigger": ["track", "expand", "variants"], "display_order": 1000, "on_by_default": True},
    ]}]}


@pytest.fixture
def browser_setup(genome, brca2, catalogue):
    gene = {**brca2, "slice": {"location": {"start": 32315086, "end": 32400268}, "region": {"name": "13", "length": 114364328}}}
    settings = Settings("https://core.invalid", search_url="https://search.invalid/genomes/v3",
                        tracks_url="http://tracks.internal:8012", browser_genome_ids=(genome["genome_id"],))
    data = {"GetGenome": {"genome": genome}, "BrowserGene": {"gene": gene},
            "BrowserRegion": {"region": {"name": "17", "length": 83257441}}}
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            assert str(request.url) == f"http://tracks.internal:8012/track_categories/{genome['genome_id']}"
            return httpx.Response(200, json=catalogue)
        body = json.loads(request.content)
        if body["operationName"] == "BrowserGene":
            assert body["variables"]["genomeId"] == genome["genome_id"]
        return httpx.Response(200, json={"data": data[body["operationName"]]})

    return settings, data, requests, handler


async def test_view_fallback_metadata_and_identity(browser_setup, genome):
    settings, _, requests, handler = browser_setup
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["show_genome_browser"]
        assert tool.meta["ui"]["resourceUri"] == UI_URI
        assert tool.annotations.read_only_hint
        assert set(tool.input_schema["required"]) == {"genome_id"}
        assert "location" in tool.output_schema["properties"]
        result = await client.call_tool("show_genome_browser", {"genome_id": genome["genome_id"], "gene_id": "ENSG00000139618"})
    view = BrowserView.model_validate(result.structured_content)
    assert view.genome.model_dump() == genome
    assert view.gene_id == "ENSG00000139618.19"
    assert view.location.start == 32315086 and view.location.region == "13"
    assert [track.track_id for track in view.initial_tracks] == ["genes", "sequence"]
    assert "focus=gene%3AENSG00000139618.19" in view.ensembl_url
    assert "trackCatalogue" in str(result.meta)
    assert "track_categories" not in result.structured_content
    assert "1-based inclusive" in result.content[0].text
    assert "rendering in the client is not confirmed" in result.content[0].text
    assert "tracks.internal" not in str(result)
    assert len(requests) == 3


async def test_interval_and_selected_gene_details(browser_setup, genome):
    settings, _, _, handler = browser_setup
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("show_genome_browser", {"genome_id": genome["genome_id"], "region": "17", "start": 63992802, "end": 64038237})
        assert result.structured_content["location"] == {"region": "17", "start": 63992802, "end": 64038237, "region_length": 83257441}
        details = await client.call_tool("get_browser_gene", {"genome_id": genome["genome_id"], "gene_id": "ENSG00000139618.19"})
        assert details.structured_content["gene"]["symbol"] == "BRCA2"
        assert details.structured_content["genome"] == genome


@pytest.mark.parametrize("arguments", [
    {}, {"gene_id": "BRCA2", "region": "17", "start": 1, "end": 10},
    {"region": "17", "start": 1}, {"region": "17", "start": 0, "end": 10},
    {"region": "17", "start": 10, "end": 1}, {"region": "17", "start": True, "end": 10},
    {"region": "17", "start": 1.5, "end": 10}, {"region": "../17", "start": 1, "end": 10},
    {"gene_id": "../ENSG1"}, {"gene_id": ""}, {"gene_id": "ENSG1", "start": 1},
    {"region": "17", "start": 1, "end": 2**53},
])
async def test_invalid_inputs_do_not_request(browser_setup, genome, arguments):
    settings, _, requests, handler = browser_setup
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("show_genome_browser", {"genome_id": genome["genome_id"], **arguments}, raise_on_error=False)
    assert result.is_error and not requests


async def test_backend_genome_allowlist_before_network(browser_setup):
    settings, _, requests, handler = browser_setup
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("show_genome_browser", {"genome_id": "59871324-7803-4234-856e-2a2bd96d7b3c", "gene_id": "ENSG1"}, raise_on_error=False)
    assert result.is_error and "unsupported_browser_genome" in result.content[0].text
    assert not requests


@pytest.mark.parametrize("change, category", [
    ("genome", "upstream_response"), ("gene", "upstream_response"),
    ("region", "upstream_response"), ("bounds", "input_validation"),
    ("bad_slice", "upstream_response"), ("missing_gene", "not_found"),
])
async def test_mismatches_and_bounds(browser_setup, genome, change, category):
    settings, data, _, handler = browser_setup
    arguments = {"genome_id": genome["genome_id"], "gene_id": "ENSG00000139618.19"}
    if change == "genome":
        data["GetGenome"]["genome"] = {**genome, "genome_id": "different"}
    elif change == "gene":
        data["BrowserGene"]["gene"]["stable_id"] = "ENSG00000139618.20"
    elif change == "bad_slice":
        data["BrowserGene"]["gene"]["slice"]["location"]["end"] = 999999999
    elif change == "missing_gene":
        data["BrowserGene"]["gene"] = None
    else:
        arguments = {"genome_id": genome["genome_id"], "region": "17", "start": 1, "end": 999999999 if change == "bounds" else 10}
        if change == "region": data["BrowserRegion"]["region"]["name"] = "18"
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("show_genome_browser", arguments, raise_on_error=False)
    assert result.is_error and category in result.content[0].text


@pytest.mark.parametrize("failure", ["404", "500", "redirect", "timeout", "json", "shape", "empty", "no_genes", "no_sequence", "duplicate"])
async def test_catalogue_failures(browser_setup, genome, catalogue, failure):
    settings, _, _, base_handler = browser_setup
    def handler(request):
        if request.method != "GET": return base_handler(request)
        if failure == "timeout": raise httpx.ReadTimeout("private secret", request=request)
        if failure == "json": return httpx.Response(200, text="private secret")
        if failure == "shape": return httpx.Response(200, json={"private": "secret"})
        if failure in {"404", "500", "redirect"}: return httpx.Response(302 if failure == "redirect" else int(failure))
        payload = copy.deepcopy(catalogue)
        tracks = payload["track_categories"][0]["track_list"]
        if failure == "empty": tracks.clear()
        elif failure == "no_genes": tracks.pop(0)
        elif failure == "no_sequence": tracks.pop(1)
        elif failure == "duplicate": tracks.append(tracks[0])
        return httpx.Response(200, json=payload)
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("show_genome_browser", {"genome_id": genome["genome_id"], "gene_id": "ENSG00000139618"}, raise_on_error=False)
    assert result.is_error
    assert "secret" not in result.content[0].text
    assert ("unsupported_browser_tracks" if failure in {"empty", "no_genes", "no_sequence"} else "catalogue_unavailable") in result.content[0].text


async def test_resource_content_and_csp(browser_setup):
    settings, _, requests, handler = browser_setup
    assert files("ensembl_mcp").joinpath("ui/genome-browser.html").is_file(), "Build frontend before running integration tests"
    async with Client(create_server(settings, transport=httpx.MockTransport(handler))) as client:
        resources = await client.list_resources()
        resource = next(item for item in resources if str(item.uri) == UI_URI)
        assert resource.mime_type == "text/html;profile=mcp-app"
        content = (await client.read_resource(UI_URI))[0]
        assert content.mime_type == "text/html;profile=mcp-app"
        assert "Explain this selection" in content.text
        assert "<!-- APP_SCRIPT -->" not in content.text
        assert content.meta["ui"]["csp"]["connectDomains"] == ["https://mcp-poc-public.review.ensembl.org"]
        assert content.meta["ui"]["csp"]["resourceDomains"] == []
        assert not requests


async def test_missing_tracks_configuration_is_a_clear_tool_error(browser_setup, genome):
    settings, _, _, handler = browser_setup
    async with Client(create_server(replace(settings, tracks_url=None), transport=httpx.MockTransport(handler))) as client:
        result = await client.call_tool("show_genome_browser", {"genome_id": genome["genome_id"], "gene_id": "ENSG00000139618"}, raise_on_error=False)
    assert result.is_error and "tracks_not_configured" in result.content[0].text


async def test_app_wire_contract_over_existing_mcp_http_path(browser_setup, genome):
    from test_http import rpc_result
    settings, _, _, handler = browser_setup
    app = create_server(settings, transport=httpx.MockTransport(handler)).http_app(
        path="/mcp", transport="streamable-http", stateless_http=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost",
                                     headers={"Accept": "application/json, text/event-stream"}) as client:
            initial = rpc_result(await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "browser-test", "version": "1"}}}))
            client.headers["MCP-Protocol-Version"] = initial["protocolVersion"]
            result = rpc_result(await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": UI_URI}}))
            assert result["contents"][0]["mimeType"] == "text/html;profile=mcp-app"
            assert result["contents"][0]["_meta"]["ui"]["csp"]["connectDomains"] == ["https://mcp-poc-public.review.ensembl.org"]
            called = rpc_result(await client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "show_genome_browser", "arguments": {"genome_id": genome["genome_id"], "gene_id": "ENSG00000139618"}}}))
            assert called["structuredContent"]["genome"] == genome
            assert called["_meta"]["ensembl/trackCatalogue"]["track_categories"]


@pytest.mark.parametrize("name,value", [
    ("ENSEMBL_TRACKS_API_URL", "https://user:secret@example.com"),  # gitleaks:allow -- deliberate rejected URL fixture
    ("ENSEMBL_BROWSER_BACKEND_URL", "http://example.com/data"),
    ("ENSEMBL_BROWSER_BACKEND_URL", "https://example.com/data/hi"),
    ("ENSEMBL_BROWSER_WEBSITE_URL", "javascript:alert(1)"),
    ("ENSEMBL_BROWSER_GENOME_IDS", ""), ("ENSEMBL_BROWSER_GENOME_IDS", "*"),
])
def test_browser_configuration(name, value):
    with pytest.raises(ConfigurationError, match=name):
        Settings.from_env({"ENSEMBL_CORE_GRAPHQL_URL": "https://core.invalid", "ENSEMBL_GENOME_SEARCH_URL": "https://search.invalid", name: value})
