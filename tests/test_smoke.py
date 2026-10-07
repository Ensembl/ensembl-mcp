import os
import subprocess
import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from ensembl_mcp.smoke import check_server


def test_live_command_requires_explicit_opt_in():
    # Even a configured endpoint must not trigger a live test on its own.
    result = subprocess.run(
        [sys.executable, "-m", "ensembl_mcp.smoke"],
        env={**os.environ, "ENSEMBL_CORE_GRAPHQL_URL": "http://example.invalid"},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "--live is required" in result.stderr
    assert result.stdout == ""


async def test_smoke_over_stdio_with_mocked_backend(tmp_path, genome, brca2):
    # Running subprocess and the same client check used by --live, without TCP.
    script = tmp_path / "mock_server.py"
    script.write_text(
        "import httpx\n"
        "from ensembl_mcp.config import Settings\n"
        "from ensembl_mcp.server import create_server\n"
        f"payload = {{'data': {{'genomes': [{genome!r}], 'genes': [{brca2!r}]}}}}\n"
        "transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))\n"
        "create_server(Settings('http://example.invalid'), transport=transport).run(transport='stdio', show_banner=False)\n"
    )
    transport = StdioTransport(sys.executable, [str(script)], keep_alive=False)
    async with Client(transport, timeout=10) as client:
        result = await check_server(client)
    assert result.genome.genome_id == genome["genome_id"]
    assert result.genes[0].model_dump() == brca2


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-5"])
def test_invalid_live_client_timeout(timeout):
    result = subprocess.run(
        [sys.executable, "-m", "ensembl_mcp.smoke", "--live", f"--client-timeout={timeout}"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "finite positive number" in result.stderr
