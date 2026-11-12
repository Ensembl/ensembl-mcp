"""Opt-in live MCP checks; emit tool results for the local renderer harness.

Run after configuring the normal server environment. This performs only reads
and does not install or change a connector or deployed server.
"""
import argparse
import asyncio
import json
from pathlib import Path

from fastmcp import Client
from ensembl_mcp.browser import DEMO_GENOME
from ensembl_mcp.config import Settings
from ensembl_mcp.server import create_server


async def run(output: Path):
    async with Client(create_server(Settings.from_env())) as client:
        found = await client.call_tool("find_gene", {"symbol": "BRCA2", "genome_id": DEMO_GENOME})
        genes = found.structured_content["genes"]
        if len(genes) != 1:
            raise RuntimeError("BRCA2 lookup did not yield one unambiguous match")
        for locus, name, arguments in [
            ("brca2", "show_genome_browser", {"genome_id": DEMO_GENOME, "gene_id": genes[0]["stable_id"]}),
            ("demo", "demo_genome_browser", {}),
        ]:
            result = await client.call_tool(name, arguments)
            output.mkdir(parents=True, exist_ok=True)
            payload = {"structuredContent": result.structured_content, "_meta": result.meta,
                       "content": [{"type": "text", "text": "Live MCP result; rendering not yet verified"}]}
            (output / f"live-{locus}.json").write_text(json.dumps(payload), encoding="utf-8")
            print(f"{locus}: live tool result passed; genome={result.structured_content['genome']['genome_id']}")
        details = await client.call_tool("get_browser_gene", {"genome_id": DEMO_GENOME, "gene_id": genes[0]["stable_id"]})
        if details.structured_content["gene"]["symbol"] != "BRCA2":
            raise RuntimeError("Selected-gene annotation did not identify BRCA2")
        print("Selected-gene annotation retrieval passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=Path("frontend/.live-fixtures"))
    args = parser.parse_args()
    asyncio.run(run(args.output))
