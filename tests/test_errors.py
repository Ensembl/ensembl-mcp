import logging

import httpx
import pytest

from ensembl_mcp.graphql import CoreGraphQLClient, LookupError
from ensembl_mcp.lookup import EnsemblLookup

SECRET = "http://private-cluster.invalid:8000 secret-body"


@pytest.mark.parametrize("stage", ["genomes", "genes"])
@pytest.mark.parametrize("failure,category", [
    ("http", "upstream_http"), ("redirect", "upstream_http"),
    ("connection", "upstream_connection"), ("timeout", "upstream_timeout"),
    ("graphql", "upstream_graphql"), ("partial", "upstream_graphql"),
    ("json", "upstream_response"), ("null_body", "upstream_response"),
    ("list_body", "upstream_response"), ("missing_data", "upstream_response"),
    ("null_data", "upstream_response"), ("list_data", "upstream_response"),
    ("missing_list", "upstream_response"), ("null_list", "upstream_response"),
    ("object_list", "upstream_response"), ("missing_fields", "upstream_response"),
    ("wrong_type", "upstream_response"), ("null_entry", "upstream_response"),
    ("bad_errors", "upstream_response"),
])
async def test_upstream_failures(genome, brca2, stage, failure, category, caplog):
    calls = []
    value = genome if stage == "genomes" else brca2
    bad_type = {**value, ("is_reference" if stage == "genomes" else "transcript_count"): "1"}
    payloads = {
        "graphql": {"errors": [{"message": SECRET}]},
        "partial": {"data": {stage: [value]}, "errors": [{"message": SECRET}]},
        "null_body": None, "list_body": [], "missing_data": {},
        "null_data": {"data": None}, "list_data": {"data": []},
        "missing_list": {"data": {}}, "null_list": {"data": {stage: None}},
        "object_list": {"data": {stage: {}}}, "missing_fields": {"data": {stage: [{}]}},
        "wrong_type": {"data": {stage: [bad_type]}}, "null_entry": {"data": {stage: [None]}},
        "bad_errors": {"data": {stage: [value]}, "errors": SECRET},
    }

    def handler(request):
        calls.append(request)
        if stage == "genes" and len(calls) == 1:
            return httpx.Response(200, json={"data": {"genomes": [genome]}})
        if failure == "http":
            return httpx.Response(503, text=SECRET)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "http://another-private-host/"})
        if failure == "connection":
            raise httpx.ConnectError(SECRET)
        if failure == "timeout":
            raise httpx.ReadTimeout(SECRET)
        if failure == "json":
            return httpx.Response(200, text=SECRET)
        if failure == "null_body":
            return httpx.Response(200, content=b"null")
        return httpx.Response(200, json=payloads[failure])

    caplog.set_level(logging.INFO, logger="ensembl_mcp")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LookupError) as exc:
            await EnsemblLookup(CoreGraphQLClient(http, "http://private-cluster.invalid:8000")).find_gene("BRCA2", "Homo sapiens")
    assert exc.value.category == category
    assert "private-cluster" not in str(exc.value) and "secret-body" not in str(exc.value)
    assert len(calls) == (1 if stage == "genomes" else 2)
    logs = [record.message for record in caplog.records if record.name.startswith("ensembl_mcp")]
    assert f"outcome={category}" in logs[-1]
    assert "elapsed_seconds=" in logs[-1] and "http_status=" in logs[-1]
    assert all(SECRET not in line for line in logs)
