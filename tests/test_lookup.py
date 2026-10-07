import json
import logging

import httpx
import pytest

from ensembl_mcp.graphql import CoreGraphQLClient, LookupError
from ensembl_mcp.lookup import EnsemblLookup, GENES_QUERY, GENOMES_QUERY, select_reference_genome
from ensembl_mcp.models import Genome

ENDPOINT = "http://private-backend.invalid:8000"


@pytest.mark.parametrize("genome_id", [
    "59871324-7803-4234-856e-2a2bd96d7b3c",
    "cf06c737-7528-4f21-9a01-07aa29f6ffab",
])
async def test_happy_path_and_dynamic_uuid(genome, brca2, genome_id, caplog):
    genome["genome_id"] = genome_id
    other = {**genome, "genome_id": "other-assembly", "is_reference": False}
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"data": {"genomes": [other, genome]}})
        return httpx.Response(200, json={
            "data": {"genes": [brca2]}, "extensions": {"execution_time_in_seconds": 11.19},
        })

    caplog.set_level(logging.INFO, logger="ensembl_mcp")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await EnsemblLookup(CoreGraphQLClient(http, ENDPOINT)).find_gene(" BRCA2 ", " Homo sapiens ")
    assert result.model_dump() == {
        "symbol": "BRCA2", "species": "Homo sapiens", "genome": genome,
        "genes": [brca2], "outcome": "found",
    }
    assert len(requests) == 2
    bodies = [json.loads(request.content) for request in requests]
    assert bodies[0] == {
        "operationName": "ResolveReferenceGenome", "query": GENOMES_QUERY,
        "variables": {"by_keyword": {"scientific_name": "Homo sapiens"}},
    }
    assert bodies[1] == {
        "operationName": "FindGenesBySymbol", "query": GENES_QUERY,
        "variables": {"by_symbol": {"symbol": "BRCA2", "genome_id": genome_id}},
    }
    assert all(req.method == "POST" and req.headers["content-type"] == "application/json" for req in requests)
    logs = [record.message for record in caplog.records if record.name.startswith("ensembl_mcp")]
    assert len(logs) == 2
    assert all("elapsed_seconds=" in line and "outcome=success http_status=200" in line for line in logs)
    assert all(ENDPOINT not in line and "BRCA2" not in line and "11.19" not in line for line in logs)


@pytest.mark.parametrize("count", [0, 1, 2])
async def test_gene_list_semantics_and_nullable_fields(genome, brca2, count):
    nullable = {key: None for key in brca2}
    nullable["stable_id"] = "ENSG00000000001.4"
    genes = [brca2, nullable][:count]

    def handler(request):
        field, values = ("genomes", [genome]) if json.loads(request.content)["operationName"] == "ResolveReferenceGenome" else ("genes", genes)
        return httpx.Response(200, json={"data": {field: values}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await EnsemblLookup(CoreGraphQLClient(http, ENDPOINT)).find_gene("BRCA2", "Homo sapiens")
    assert result.model_dump()["genes"] == genes
    assert result.genome.model_dump() == genome
    assert result.outcome == ("found" if count else "not_found")


@pytest.mark.parametrize("case,category", [
    ("empty", "species_not_found"), ("non_reference", "no_reference_genome"),
    ("ambiguous", "ambiguous_reference_genome"),
])
async def test_failed_resolution_stops_before_gene_request(genome, case, category):
    values = {
        "empty": [], "non_reference": [{**genome, "is_reference": False}],
        "ambiguous": [genome, {**genome, "genome_id": "second-reference"}],
    }[case]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"genomes": values}})

    with pytest.raises(LookupError, match=category):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await EnsemblLookup(CoreGraphQLClient(http, ENDPOINT)).find_gene("BRCA2", "Homo sapiens")
    assert len(calls) == 1


def test_selection_is_order_independent(genome):
    reference = Genome.model_validate(genome)
    other = reference.model_copy(update={"is_reference": False})
    assert select_reference_genome([reference, other]) is reference
    assert select_reference_genome([other, reference]) is reference


@pytest.mark.parametrize("symbol,species", [("", "Homo sapiens"), ("  \t", "Homo sapiens"), ("BRCA2", "\n ")])
async def test_blank_inputs_never_call_upstream(symbol, species):
    def handler(request):
        pytest.fail("Blank inputs must not reach the backend")

    with pytest.raises(LookupError, match="input_validation"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await EnsemblLookup(CoreGraphQLClient(http, ENDPOINT)).find_gene(symbol, species)


async def test_special_characters_are_only_in_variables(genome):
    symbol, species = 'bRcA2"\\雪', 'Species "quoted"\\\nname'
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"genomes": [genome], "genes": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await EnsemblLookup(CoreGraphQLClient(http, ENDPOINT)).find_gene(symbol, species)
    assert result.symbol == symbol and result.species == species
    assert bodies[0]["variables"]["by_keyword"]["scientific_name"] == species
    assert bodies[1]["variables"]["by_symbol"]["symbol"] == symbol
    assert bodies[0]["query"] == GENOMES_QUERY and bodies[1]["query"] == GENES_QUERY
