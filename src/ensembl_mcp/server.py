"""FastMCP registration and configurable stdio/Streamable HTTP entry point."""

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
from .discovery import GenomeServices, FindGenomesResult, ExplainGenomeResult, DownloadLinksResult

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
            yield {
                "lookup": EnsemblLookup(CoreGraphQLClient(http, settings.endpoint)),
                "genomes": GenomeServices(http, settings.search_url, settings.metadata_url),
            }

    server = FastMCP(
        "Ensembl MCP", lifespan=lifespan, mask_error_details=True,
        strict_input_validation=True,
    )

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def find_gene(symbol: str, ctx: Context, species: str | None = None, genome_id: str | None = None) -> FindGeneResult:
        """Find all gene matches by symbol in a selected genome.

        symbol: Gene symbol, preserving case (for example BRCA2).
        species: Scientific species name (for example Homo sapiens).
            Common names and fuzzy matching are not supported.
            Required only when genome_id is omitted; selects the unique reference.
        genome_id: Known genome UUID, for example from find_genomes.
            Skips species resolution and permits non-reference genomes.
            If species is also supplied, it must match this genome's scientific name.
        """
        start = perf_counter()
        outcome = "internal_error"
        try:
            result = await ctx.lifespan_context["lookup"].find_gene(symbol, species, genome_id)
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

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def find_genomes(
        ctx: Context, query: str | None = None, species_taxonomy_id: str | None = None,
        reference_only: bool = False, page: int = 1, per_page: int = 20,
        release: str | None = None,
    ) -> FindGenomesResult:
        """Discover candidate genome UUIDs for subsequent gene and metadata queries.

        Supply exactly one of query (species/common name or assembly accession/name)
        or species_taxonomy_id (exact species taxonomy ID as a decimal string).
        Search may match multiple species or assemblies; do not automatically choose
        the first hit. reference_only excludes is_reference=false, retaining all
        reference matches. Pages are 1-based with 1-100 results; filtered totals and
        pages count reference genomes only. Reference filtering scans at most 10000
        candidates; narrow larger searches. release is a Search Hub release label,
        not a Thoas numeric release; omission uses Search Hub's current/partial policy.
        """
        try:
            return await ctx.lifespan_context["genomes"].find_genomes(
                query=query, species_taxonomy_id=species_taxonomy_id,
                reference_only=reference_only, page=page, per_page=per_page, release=release,
            )
        except LookupError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def explain_genome(id_or_accession: str, ctx: Context) -> ExplainGenomeResult:
        """Explain a genome UUID or GCA/GCF assembly accession using metadata.

        Preserves a supplied UUID. Reports suppression, assembly, release, and any
        newer non-suppressed genome separately. A missing replacement means only
        that the upstream API did not report one, not that none exists.
        """
        try:
            return await ctx.lifespan_context["genomes"].explain_genome(id_or_accession)
        except LookupError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def get_genome_download_links(genome_id: str, ctx: Context) -> DownloadLinksResult:
        """Get FTP download links for exactly the supplied genome UUID.

        Returns links without downloading files. Release selection is not supported
        upstream: links are not guaranteed to be from the latest integrated release.
        Any newer non-suppressed genome is reported separately, never substituted.
        """
        try:
            return await ctx.lifespan_context["genomes"].get_genome_download_links(genome_id)
        except LookupError as exc:
            raise ToolError(str(exc)) from None

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
    server = create_server(settings)
    if settings.mcp_transport == "streamable-http":
        server.run(
            transport="streamable-http", host="0.0.0.0", port=settings.mcp_port,
            path="/mcp", stateless_http=True, show_banner=False,
        )
    else:
        server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
