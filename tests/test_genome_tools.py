"""Offline API and MCP contracts for discovery, explicit UUIDs and metadata."""

import json
from contextlib import AsyncExitStack
from uuid import UUID

import httpx
import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from ensembl_mcp.config import ConfigurationError, Settings
from ensembl_mcp.discovery import GenomeServices
from ensembl_mcp.graphql import CoreGraphQLClient, LookupError
from ensembl_mcp.lookup import EnsemblLookup
from ensembl_mcp.server import create_server

SEARCH = "https://search.invalid/genomes/v3"
METADATA = "https://metadata.invalid/api/metadata"
GENOME_ID = "cf06c737-7528-4f21-9a01-07aa29f6ffab"
NEWER_ID = "59871324-7803-4234-856e-2a2bd96d7b3c"


def summary(genome_id=GENOME_ID, **changes):
    return {
        "genome_id": genome_id, "scientific_name": "Homo sapiens", "common_name": "Human",
        "species_taxonomy_id": "9606", "assembly": {"accession_id": "GCA_000001405.29", "name": "GRCh38.p14"},
        "is_reference": True, "release": {"name": "2026-07", "type": "integrated"},
        "is_suppressed": False, "suppression_details": None, **changes,
    }


def candidate(genome_id=GENOME_ID, **changes):
    return {**summary(genome_id), "taxonomy_id": "9606", "annotation_provider": "Ensembl",
            "annotation_method": "Ensembl", "coding_genes_count": 20000, **changes}


async def test_reference_filter_uses_all_pages_with_filtered_total():
    genomes = [candidate(str(UUID(int=i + 1)), is_reference=i in {1, 100, 102}) for i in range(103)]
    requests = []

    def handler(request):
        requests.append(request)
        page, size = int(request.url.params["page"]), int(request.url.params["per_page"])
        return httpx.Response(200, json={"meta": {"total_hits": 103, "page": page, "per_page": size},
                                        "matches": genomes[(page - 1) * size:page * size]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await GenomeServices(http, SEARCH, METADATA).find_genomes(
            query="human", reference_only=True, page=2, per_page=2,
        )
    assert [g.genome_id for g in result.matches] == [genomes[102]["genome_id"]]
    assert result.meta.model_dump() == {"total_hits": 3, "page": 2, "per_page": 2}
    assert result.next_page is None
    assert [r.url.params["page"] for r in requests] == ["1", "2"]
    assert all("reference_only" not in r.url.params for r in requests)


@pytest.mark.parametrize("total,expected_requests", [(1000, 10), (1001, 1)])
async def test_reference_search_work_is_bounded(total, expected_requests):
    requests = []
    def handler(request):
        requests.append(request)
        page = int(request.url.params["page"])
        offset = (page - 1) * 100
        matches = [candidate(str(UUID(int=i + 1))) for i in range(offset, min(total, offset + 100))]
        return httpx.Response(200, json={"meta": {"total_hits": total, "page": page, "per_page": 100},
                                        "matches": matches})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = GenomeServices(http, SEARCH, METADATA)
        if total > 1000:
            with pytest.raises(LookupError, match="search_too_broad"):
                await service.find_genomes(query="human", reference_only=True, per_page=1)
        else:
            result = await service.find_genomes(query="human", reference_only=True, per_page=1)
            assert len(result.matches) == 1 and result.meta.total_hits == 1000
    assert len(requests) == expected_requests


async def test_reference_filter_retains_multiple_references_and_empty_pages():
    def handler(request):
        return httpx.Response(200, json={"meta": {"total_hits": 2, "page": 1, "per_page": 100},
                                        "matches": [candidate(), candidate(NEWER_ID)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = GenomeServices(http, SEARCH, METADATA)
        result = await service.find_genomes(species_taxonomy_id="9606", reference_only=True, per_page=1)
        assert result.next_page == 2
        result = await service.find_genomes(species_taxonomy_id="9606", reference_only=True, page=3)
        assert result.matches == [] and result.meta.total_hits == 2


@pytest.mark.parametrize("arguments", [
    {}, {"query": " "}, {"query": "h"}, {"query": "human", "species_taxonomy_id": "9606"},
    {"species_taxonomy_id": "-1"}, {"species_taxonomy_id": str(2**64)},
    {"query": "human", "per_page": 101}, {"query": "human", "page": 0},
])
async def test_invalid_search_never_requests(arguments):
    def handler(request):
        pytest.fail("Invalid selector reached upstream")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LookupError, match="input_validation"):
            await GenomeServices(http, SEARCH, METADATA).find_genomes(**arguments)


async def test_search_forwards_release_and_taxonomy_without_fuzzy_resolution():
    def handler(request):
        assert dict(request.url.params) == {"species_taxonomy_id": "9606", "page": "1", "per_page": "20", "release": "2026-07"}
        return httpx.Response(200, json={"meta": {"total_hits": 1, "page": 1, "per_page": 20}, "matches": [candidate()]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await GenomeServices(http, SEARCH, METADATA).find_genomes(species_taxonomy_id="9606", release="2026-07")
    assert result.matches[0].genome_id == GENOME_ID


@pytest.mark.parametrize("case", ["changed", "duplicates", "too_broad", "bad_pagination"])
async def test_incomplete_reference_search_is_an_error(case):
    def handler(request):
        page = int(request.url.params["page"])
        total = 10001 if case == "too_broad" else 101
        matches = [candidate(str(UUID(int=i + 1))) for i in range(100)] if page == 1 else [candidate(str(UUID(int=1 if case == "duplicates" else 101)))]
        if case == "changed" and page == 2:
            total = 102
            matches.append(candidate(str(UUID(int=102))))
        if case == "bad_pagination":
            matches = []
        return httpx.Response(200, json={"meta": {"total_hits": total, "page": page, "per_page": 100}, "matches": matches})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LookupError, match="search_too_broad" if case == "too_broad" else "upstream_response"):
            await GenomeServices(http, SEARCH, METADATA).find_genomes(query="human", reference_only=True)


async def test_explicit_uuid_skips_species_resolution_and_accepts_nonreference(genome, brca2):
    calls = []
    genome = {**genome, "is_reference": False}
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["operationName"] != "ResolveReferenceGenome"
        if body["operationName"] == "GetGenome":
            assert body["variables"] == {"by_genome_id": {"genome_id": GENOME_ID}}
            return httpx.Response(200, json={"data": {"genome": genome}})
        assert body["variables"]["by_symbol"]["genome_id"] == GENOME_ID
        return httpx.Response(200, json={"data": {"genes": [brca2]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await EnsemblLookup(CoreGraphQLClient(http, "https://core.invalid")).find_gene("BRCA2", genome_id=GENOME_ID)
    assert result.species is None
    assert result.genome.genome_id == GENOME_ID and not result.genome.is_reference
    assert len(calls) == 2


@pytest.mark.parametrize("case", ["different_uuid", "species_mismatch", "missing_genome"])
async def test_direct_lookup_never_queries_genes_for_invalid_genome(genome, case):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"genome": None if case == "missing_genome" else {**genome, "genome_id": NEWER_ID if case == "different_uuid" else GENOME_ID}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LookupError):
            await EnsemblLookup(CoreGraphQLClient(http, "https://core.invalid")).find_gene(
                "BRCA2", species="Mus musculus" if case == "species_mismatch" else None, genome_id=GENOME_ID,
            )
    assert len(calls) == 1


@pytest.mark.parametrize("replacement,expected", [(None, "not_reported"), (False, "available"), (True, "suppressed")])
async def test_download_links_preserve_uuid_and_report_only_unsuppressed_replacement(replacement, expected):
    requests = []
    payload = summary()
    if replacement is not None:
        payload["latest_genome"] = summary(NEWER_ID, is_suppressed=replacement)
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("explain"):
            return httpx.Response(200, json=payload)
        assert request.url.path == f"/api/metadata/genome/{GENOME_ID}/ftplinks"
        assert not request.url.params
        return httpx.Response(200, json=[{"dataset": "genebuild", "url": "https://ftp.ebi.ac.uk/example/"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await GenomeServices(http, SEARCH, METADATA).get_genome_download_links(GENOME_ID)
    assert result.genome_id == GENOME_ID
    assert result.newer_genome_status == expected
    assert (result.newer_genome is not None) == (expected == "available")
    assert result.release_selection == "not_applied"
    assert "not guaranteed" in result.notice
    assert len(requests) == 2


async def test_explain_accession_preserves_original_and_suppression():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=summary(is_suppressed=True, suppression_details="Withdrawn")))) as http:
        result = await GenomeServices(http, SEARCH, METADATA).explain_genome("GCA_000001405.29")
    assert result.requested_id == "GCA_000001405.29"
    assert result.genome.is_suppressed and result.genome.suppression_details == "Withdrawn"


@pytest.mark.parametrize("identifier", ["", "../releases", "https://other.invalid", "GCA_123/../releases"])
async def test_invalid_identifier_never_requests(identifier):
    def handler(request):
        pytest.fail("Invalid identifier reached upstream")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = GenomeServices(http, SEARCH, METADATA)
        for method in (service.explain_genome, service.get_genome_download_links):
            with pytest.raises(LookupError, match="input_validation"):
                await method(identifier)


@pytest.mark.parametrize("response,category", [
    (httpx.Response(503, json={"secret": "private"}), "upstream_http"),
    (httpx.Response(302, headers={"location": "https://other.invalid"}), "upstream_http"),
    (httpx.Response(200, content="not JSON"), "upstream_response"),
    (httpx.Response(200, json={"matches": []}), "upstream_response"),
    (httpx.Response(200, json={"meta": {"total_hits": "0", "page": 1, "per_page": 20}, "matches": []}), "upstream_response"),
])
async def test_rest_failures_cannot_become_empty_searches(response, category):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as http:
        with pytest.raises(LookupError, match=category) as error:
            await GenomeServices(http, SEARCH, METADATA).find_genomes(query="human")
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("exception,category", [(httpx.ReadTimeout, "upstream_timeout"), (httpx.ConnectError, "upstream_connection")])
async def test_rest_network_failures_are_safe(exception, category):
    def handler(request):
        raise exception("secret upstream address")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LookupError, match=category) as error:
            await GenomeServices(http, SEARCH, METADATA).find_genomes(query="human")
    assert "secret" not in str(error.value)


async def test_missing_metadata_configuration_is_explicit():
    async with httpx.AsyncClient() as http:
        with pytest.raises(LookupError, match="configuration"):
            await GenomeServices(http, SEARCH, None).explain_genome(GENOME_ID)


@pytest.mark.parametrize("variable", ["ENSEMBL_GENOME_SEARCH_URL", "ENSEMBL_METADATA_API_URL"])
@pytest.mark.parametrize("value", [
    'ftp://host',
    'https://user:secret@host',  # gitleaks:allow -- deliberate rejected URL fixture
    'http://host/?q=1',
    'https://host/#x',
    'http://host:0',
    'http://bad host',
])
def test_rest_configuration_rejects_unsafe_urls(variable, value):
    with pytest.raises(ConfigurationError, match=variable):
        Settings.from_env({"ENSEMBL_CORE_GRAPHQL_URL": "https://core.invalid", "ENSEMBL_GENOME_SEARCH_URL": SEARCH, variable: value})


@pytest.mark.parametrize("over_http", [False, True])
async def test_new_tools_over_mcp(genome, brca2, over_http):
    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["operationName"] != "ResolveReferenceGenome"
            return httpx.Response(200, json={"data": {"genome": genome, "genes": [brca2]}})
        if request.url.path.endswith("explain"):
            return httpx.Response(200, json=summary())
        if request.url.path.endswith("ftplinks"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"meta": {"total_hits": 1, "page": 1, "per_page": 100}, "matches": [candidate()]})
    settings = Settings("https://core.invalid", search_url=SEARCH, metadata_url=METADATA)
    server = create_server(settings, transport=httpx.MockTransport(handler))
    async with AsyncExitStack() as stack:
        target = server
        if over_http:
            app = server.http_app(path="/mcp", transport="streamable-http", stateless_http=True)
            await stack.enter_async_context(app.router.lifespan_context(app))
            target = StreamableHttpTransport(
                "http://localhost/mcp",
                httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(transport=httpx2.ASGITransport(app), **kwargs),
            )
        client = await stack.enter_async_context(Client(target, timeout=5))
        for tool, arguments in [
            ("find_genomes", {"query": "human", "reference_only": True}),
            ("find_gene", {"symbol": "BRCA2", "genome_id": GENOME_ID}),
            ("explain_genome", {"id_or_accession": GENOME_ID}),
            ("get_genome_download_links", {"genome_id": GENOME_ID}),
        ]:
            result = await client.call_tool(tool, arguments)
            assert not result.is_error and result.structured_content is not None
        for tool, arguments in [
            ("find_genomes", {"query": "human", "reference_only": "true"}),
            ("find_gene", {"symbol": "BRCA2", "genome_id": "wrong"}),
            ("get_genome_download_links", {"genome_id": GENOME_ID, "release": "2026-07"}),
        ]:
            assert (await client.call_tool(tool, arguments, raise_on_error=False)).is_error


@pytest.mark.parametrize("changes", [
    {"genome_id": NEWER_ID},
    {"latest_genome": summary()},
    {"latest_genome": {k: v for k, v in summary(NEWER_ID).items() if k != "is_suppressed"}},
])
async def test_untrustworthy_metadata_is_an_error(changes):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={**summary(), **changes}))) as http:
        with pytest.raises(LookupError, match="upstream_response"):
            await GenomeServices(http, SEARCH, METADATA).explain_genome(GENOME_ID)


@pytest.mark.parametrize("url", [
    'https://user:secret@host/path',  # gitleaks:allow -- deliberate rejected URL fixture
    'javascript:alert(1)',
    'http://host:bad',
    'http://has space/path',
])
async def test_download_links_reject_invalid_urls(url):
    def handler(request):
        return httpx.Response(200, json=summary() if request.url.path.endswith("explain") else [{"dataset": "genebuild", "url": url}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LookupError, match="upstream_response") as error:
            await GenomeServices(http, SEARCH, METADATA).get_genome_download_links(GENOME_ID)
    assert "secret" not in str(error.value)
