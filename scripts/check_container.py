"""Offline smoke check for the packaged runtime, run with restricted privileges."""

import asyncio
import json
import os
import sqlite3
from importlib.metadata import version
from pathlib import Path

from fastmcp import Client

from ensembl_mcp.browser import UI_URI
from ensembl_mcp.config import Settings
from ensembl_mcp.server import create_server


async def check():
    if os.getuid() != 10001:
        raise RuntimeError("Container must run as UID 10001")
    status = Path("/proc/self/status").read_text()
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if int(fields["CapEff"].strip(), 16) != 0 or fields["NoNewPrivs"].strip() != "1":
        raise RuntimeError("Container must drop capabilities and forbid privilege escalation")
    if sqlite3.sqlite_version_info < (3, 54, 1):
        raise RuntimeError("SQLite security release 3.54.1 or newer is required")
    with sqlite3.connect(":memory:") as connection:
        connection.execute("create virtual table words using fts5(word, detail=none, prefix='2')")
        connection.executemany("insert into words(rowid, word) values (?, ?)", [(-1, "security"), (1, "service")])
        rows = connection.execute("select count(*) from words where words match 'se*'").fetchone()
        if rows != (2,):
            raise RuntimeError("SQLite FTS5 smoke check failed")
    server = create_server(Settings("https://core.invalid", search_url="https://search.invalid"))
    async with Client(server) as client:
        tools = await client.list_tools()
        if len(tools) != 7:
            raise RuntimeError("Expected seven MCP tools")
        resources = await client.read_resource(UI_URI)
        if not resources or "<html" not in resources[0].text.lower():
            raise RuntimeError("Packaged browser resource is missing")
    print(json.dumps({"uid": os.getuid(), "sqlite": sqlite3.sqlite_version,
                      "fastmcp": version("fastmcp"), "tools": len(tools), "browser_resource": "passed"}))


if __name__ == "__main__":
    asyncio.run(check())
