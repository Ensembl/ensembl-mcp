"""FastMCP registration and stdio entry point."""

import logging
import sys
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from .config import ConfigurationError, Settings
from .graphql import CoreGraphQLClient, LookupError
from .lookup import EnsemblLookup
from .models import FindGeneResult

logger = logging.getLogger(__name__)


def create_server(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> FastMCP:
    """The optional HTTP transport enables offline protocol tests."""
    @asynccontextmanager
    async def lifespan(server: FastMCP):
        async with httpx.AsyncClient(
            timeout=settings.http_timeout, transport=transport, follow_redirects=False,
        ) as http:
            yield {"lookup": EnsemblLookup(CoreGraphQLClient(http, settings.endpoint))}

    server = FastMCP(
        "Ensembl MCP", lifespan=lifespan, mask_error_details=True,
        strict_input_validation=True,
    )

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def find_gene(symbol: str, species: str, ctx: Context) -> FindGeneResult:
        """Find all gene matches by symbol in a species' reference genome.

        symbol: Gene symbol, preserving case (for example BRCA2).
        species: Scientific species name (for example Homo sapiens).
            Common names and fuzzy matching are not supported.
        """
        start = perf_counter()
        outcome = "internal_error"
        try:
            result = await ctx.lifespan_context["lookup"].find_gene(symbol, species)
            outcome = result.outcome
            return result
        except LookupError as exc:
            outcome = exc.category
            raise ToolError(str(exc)) from None
        finally:
            logger.info(
                "tool operation=find_gene elapsed_seconds=%.3f outcome=%s",
                perf_counter() - start, outcome,
            )

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
    # HTTPX's INFO request logs include the configured URL; use our safe diagnostics.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(2) from None
    create_server(settings).run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
