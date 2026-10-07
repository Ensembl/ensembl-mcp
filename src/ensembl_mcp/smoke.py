"""Explicitly enabled live MCP check; never collected by the default tests."""

import argparse
import asyncio
import math
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from .config import ConfigurationError, Settings
from .models import FindGeneResult


async def check_server(client: Client) -> FindGeneResult:
    """Validate discovery and an MCP invocation without historical data pins."""
    tools = await client.list_tools()
    tool = next((tool for tool in tools if tool.name == "find_gene"), None)
    if tool is None or set(tool.input_schema.get("required", [])) != {"symbol", "species"}:
        raise ValueError("find_gene is missing or its required inputs differ from the contract")
    result = await client.call_tool("find_gene", {"symbol": "BRCA2", "species": "Homo sapiens"})
    parsed = FindGeneResult.model_validate(result.structured_content, strict=True)
    if (
        parsed.symbol != "BRCA2"
        or parsed.species != "Homo sapiens"
        or parsed.genome.scientific_name != "Homo sapiens"
        or not parsed.genome.is_reference
        or parsed.outcome != "found"
        or not any(gene.symbol == "BRCA2" for gene in parsed.genes)
    ):
        raise ValueError("The MCP result did not contain a reference-genome BRCA2 match")
    return parsed


async def run_live(settings: Settings, client_timeout: float) -> FindGeneResult:
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "ensembl_mcp.server"],
        env={
            "ENSEMBL_CORE_GRAPHQL_URL": settings.endpoint,
            "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS": str(settings.timeout_seconds),
        },
        keep_alive=False,
    )
    async with Client(transport, timeout=client_timeout) as client:
        return await check_server(client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live BRCA2 lookup through a local stdio MCP server.")
    parser.add_argument("--live", action="store_true", help="Explicitly allow real upstream network requests")
    parser.add_argument("--client-timeout", type=float, default=90.0, help="MCP request timeout in seconds (default: 90)")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this command contacts the real configured upstream service")
    if not math.isfinite(args.client_timeout) or args.client_timeout <= 0:
        parser.error("--client-timeout must be a finite positive number")
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        parser.error(str(exc))
    try:
        result = asyncio.run(run_live(settings, args.client_timeout))
    except Exception as exc:
        # Transport exceptions can contain internals; server stderr has safe timings/categories.
        print(f"LIVE MCP check failed ({type(exc).__name__}); inspect server stderr for diagnostics.", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"LIVE MCP check passed: reference genome selected; {len(result.genes)} gene match(es), including BRCA2.")


if __name__ == "__main__":
    main()
