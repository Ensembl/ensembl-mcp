"""Regressions for upstream scalar types and the published MCP result schema."""

import json

import httpx
import pytest
from fastmcp import Client
from pydantic import ValidationError

from ensembl_mcp.config import Settings
from ensembl_mcp.models import Gene, Genome
from ensembl_mcp.server import create_server


# Confirmed development API response, supplied with the release-number bug report.
CONFIRMED_GENOME = {
    "genome_id": "59871324-7803-4234-856e-2a2bd96d7b3c",
    "scientific_name": "Homo sapiens",
    "assembly_accession": "GCA_000001405.29",
    "release_number": 2.0,
    "is_reference": True,
}


@pytest.mark.parametrize("release_number", [2.0, 2.5])
async def test_float_release_survives_lookup_and_mcp_output(brca2, release_number):
    # 2.0 is the real response; 2.5 guards against truncation of future releases.
    genome = {**CONFIRMED_GENOME, "release_number": release_number}
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["operationName"] == "ResolveReferenceGenome":
            return httpx.Response(200, json={"data": {"genomes": [genome]}})
        return httpx.Response(200, json={"data": {"genes": [brca2]}})

    server = create_server(
        Settings("http://example.invalid", search_url="https://search.invalid/genomes/v3"), transport=httpx.MockTransport(handler),
    )
    async with Client(server) as client:
        result = await client.call_tool("find_gene", {
            "symbol": "BRCA2", "species": "Homo sapiens",
        })
        output = result.structured_content
        assert output["genome"] == genome
        assert type(output["genome"]["release_number"]) is float
        assert output["genes"] == [brca2]
        assert output["outcome"] == "found"
        assert len(calls) == 2
        assert calls[1]["variables"]["by_symbol"]["genome_id"] == genome["genome_id"]

        tool = (await client.list_tools())[0]
        release_schema = tool.output_schema["properties"]["genome"]["properties"]["release_number"]
        assert {variant["type"] for variant in release_schema["anyOf"]} == {"number", "null"}


@pytest.mark.parametrize("release_number", [2, 2.0, 2.5, None])
def test_release_number_accepts_numeric_and_null_values(release_number):
    genome = Genome.model_validate({**CONFIRMED_GENOME, "release_number": release_number})
    assert genome.release_number == release_number
    if release_number is not None:
        assert type(genome.release_number) is float


@pytest.mark.parametrize("release_number", ["2.0", True])
def test_release_number_still_rejects_wrong_scalar_types(release_number):
    with pytest.raises(ValidationError):
        Genome.model_validate({**CONFIRMED_GENOME, "release_number": release_number})


def test_recorded_gene_response_matches_model_without_coercion(brca2):
    # Ensembl/ensembl-thoas at 116723fd: common/schemas/gene.graphql declares
    # transcript_count: Int!, with strings and a string list for the other fields.
    gene = Gene.model_validate(brca2, strict=True)
    assert gene.model_dump() == brca2
    assert type(gene.transcript_count) is int


@pytest.mark.parametrize("transcript_count", [19.0, 19.5, "19", True])
def test_transcript_count_retains_integer_contract(brca2, transcript_count):
    with pytest.raises(ValidationError):
        Gene.model_validate({**brca2, "transcript_count": transcript_count}, strict=True)
