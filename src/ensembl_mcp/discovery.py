"""Genome discovery and metadata operations, independent of the MCP transport."""

import logging
import re
from time import perf_counter
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from pydantic import Field, TypeAdapter, ValidationError, model_validator

from .graphql import LookupError
from .models import NonBlankString, UpstreamModel

logger = logging.getLogger(__name__)
UUIDString = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
PageSize = Annotated[int, Field(ge=1, le=100, strict=True)]


class Assembly(UpstreamModel):
    accession_id: NonBlankString
    name: NonBlankString


class Release(UpstreamModel):
    name: NonBlankString
    type: NonBlankString


class GenomeType(UpstreamModel):
    kind: str
    value: str | None


class GenomeSummary(UpstreamModel):
    genome_id: UUIDString
    scientific_name: NonBlankString
    common_name: str | None
    species_taxonomy_id: NonBlankString
    assembly: Assembly
    is_reference: bool
    release: Release
    genome_tag: str | None = None
    type: GenomeType | None = None


class SearchGenome(GenomeSummary):
    taxonomy_id: NonBlankString
    annotation_provider: str
    annotation_method: str
    coding_genes_count: Annotated[int, Field(ge=0)]


class SearchMeta(UpstreamModel):
    total_hits: Annotated[int, Field(ge=0)]
    page: PositiveInt
    per_page: PageSize


class SearchPage(UpstreamModel):
    meta: SearchMeta
    matches: list[SearchGenome]


class FindGenomesInput(UpstreamModel):
    query: NonBlankString | None = None
    species_taxonomy_id: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")] | None = None
    reference_only: bool = False
    page: PositiveInt = 1
    per_page: PageSize = 20
    release: NonBlankString | None = None

    @model_validator(mode="after")
    def one_selector(self):
        if (self.query is None) == (self.species_taxonomy_id is None):
            raise ValueError("Provide exactly one of query or species_taxonomy_id")
        if self.species_taxonomy_id is not None and int(self.species_taxonomy_id) >= 2**64:
            raise ValueError("Taxonomy ID exceeds upstream range")
        if self.query is not None and len(self.query) < 2:
            raise ValueError("Query must have at least two characters")
        return self


class FindGenomesResult(UpstreamModel):
    meta: SearchMeta
    matches: list[SearchGenome]
    reference_only: bool
    next_page: int | None


class ExplainedGenome(GenomeSummary):
    is_suppressed: bool
    suppression_details: str | None


class ExplainPayload(ExplainedGenome):
    latest_genome: ExplainedGenome | None = None


class ExplainGenomeResult(UpstreamModel):
    requested_id: str
    genome: ExplainedGenome
    newer_genome: ExplainedGenome | None
    newer_genome_status: Literal["available", "suppressed", "not_reported"]


class DownloadLink(UpstreamModel):
    dataset: NonBlankString
    url: NonBlankString

    @model_validator(mode="after")
    def public_link(self):
        try:
            url = httpx.URL(self.url)
        except httpx.InvalidURL:
            raise ValueError("Invalid download link") from None
        if url.scheme not in {"http", "https", "ftp"} or not url.host or url.userinfo or any(c.isspace() or ord(c) < 32 for c in self.url):
            raise ValueError("Invalid download link")
        return self


class DownloadLinksResult(UpstreamModel):
    genome_id: UUIDString
    links: list[DownloadLink]
    release_selection: Literal["not_applied"] = "not_applied"
    notice: str = "The metadata API does not support release selection; these links are not guaranteed to represent the latest integrated release."
    newer_genome: ExplainedGenome | None
    newer_genome_status: Literal["available", "suppressed", "not_reported"]


class GenomeServices:
    # Reference filtering needs the complete candidate set for correct totals/pages.
    # Fail explicitly rather than silently return an incomplete filtered result.
    MAX_REFERENCE_CANDIDATES = 1_000

    def __init__(self, http: httpx.AsyncClient, search_url: str, metadata_url: str | None):
        self.http = http
        self.search_url = search_url
        self.metadata_url = metadata_url.rstrip("/") if metadata_url else None

    async def get(self, url: str, params: dict | None, model):
        start = perf_counter()
        outcome, status = "internal_error", None
        try:
            response = await self.http.get(url, params=params)
            status = response.status_code
            response.raise_for_status()
            try:
                result = TypeAdapter(model).validate_python(response.json(), strict=True)
            except (ValueError, ValidationError):
                raise LookupError("upstream_response", "The service returned invalid result data.") from None
            outcome = "success"
            return result
        except httpx.TimeoutException:
            outcome = "upstream_timeout"
            raise LookupError(outcome, "The Ensembl service request timed out.") from None
        except httpx.HTTPStatusError:
            outcome = "upstream_http"
            raise LookupError(outcome, "The Ensembl service returned an unsuccessful HTTP status.") from None
        except httpx.RequestError:
            outcome = "upstream_connection"
            raise LookupError(outcome, "Could not communicate with the Ensembl service.") from None
        except LookupError as exc:
            outcome = exc.category
            raise
        finally:
            logger.info("rest elapsed_seconds=%.3f outcome=%s http_status=%s", perf_counter() - start, outcome, status)

    async def search_page(self, params: dict) -> SearchPage:
        result = await self.get(self.search_url, params, SearchPage)
        meta = result.meta
        expected = min(meta.per_page, max(0, meta.total_hits - (meta.page - 1) * meta.per_page))
        if meta.page != params["page"] or meta.per_page != params["per_page"] or len(result.matches) != expected:
            raise LookupError("upstream_response", "The service returned inconsistent pagination.")
        return result

    async def find_genomes(self, **arguments) -> FindGenomesResult:
        try:
            inputs = FindGenomesInput(**arguments)
        except ValidationError:
            raise LookupError("input_validation", "Provide exactly one valid query or species_taxonomy_id, positive page, and per_page from 1 to 100.") from None
        params = inputs.model_dump(exclude={"reference_only"}, exclude_none=True)
        if not inputs.reference_only:
            result = await self.search_page(params)
        else:
            params.update(page=1, per_page=100)
            first = await self.search_page(params)
            total = first.meta.total_hits
            if total > self.MAX_REFERENCE_CANDIDATES:
                raise LookupError("search_too_broad", "Narrow the query before filtering reference genomes (more than 1000 candidates).")
            candidates = first.matches[:]
            for page in range(2, (total + 99) // 100 + 1):
                params["page"] = page
                batch = await self.search_page(params)
                if batch.meta.total_hits != total:
                    raise LookupError("upstream_response", "Search results changed during pagination; retry the query.")
                candidates.extend(batch.matches)
            if len({g.genome_id for g in candidates}) != len(candidates):
                raise LookupError("upstream_response", "Search returned duplicate genomes during pagination.")
            references = [genome for genome in candidates if genome.is_reference]
            offset = (inputs.page - 1) * inputs.per_page
            result = SearchPage(
                meta=SearchMeta(total_hits=len(references), page=inputs.page, per_page=inputs.per_page),
                matches=references[offset:offset + inputs.per_page],
            )
        return FindGenomesResult(
            meta=result.meta, matches=result.matches, reference_only=inputs.reference_only,
            next_page=inputs.page + 1 if inputs.page * inputs.per_page < result.meta.total_hits else None,
        )

    def metadata_path(self, identifier: str, suffix: str) -> str:
        if self.metadata_url is None:
            raise LookupError("configuration", "ENSEMBL_METADATA_API_URL is required for metadata tools.")
        # Encode caller input as one path segment, never as a route or query.
        return f"{self.metadata_url}/genome/{quote(identifier, safe='')}/{suffix}"

    async def explain_genome(self, id_or_accession: str) -> ExplainGenomeResult:
        try:
            identifier = TypeAdapter(NonBlankString).validate_python(id_or_accession)
        except ValidationError:
            raise LookupError("input_validation", "Provide a genome UUID or assembly accession.") from None
        # Explicitly restrict identifiers to the upstream UUID/accession contract.
        if not re.fullmatch(r"(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|GC[AF]_[0-9]+(?:\.[0-9]+)?)", identifier):
            raise LookupError("input_validation", "Provide a genome UUID or GCA/GCF assembly accession.")
        payload = await self.get(self.metadata_path(identifier, "explain"), None, ExplainPayload)
        if "_" not in identifier and payload.genome_id != identifier:
            raise LookupError("upstream_response", "The service returned a different genome UUID.")
        newer = payload.latest_genome
        if newer is not None and newer.genome_id == payload.genome_id:
            raise LookupError("upstream_response", "The service reported the same genome as its replacement.")
        status = "not_reported" if newer is None else "suppressed" if newer.is_suppressed else "available"
        return ExplainGenomeResult(
            requested_id=identifier,
            genome=ExplainedGenome.model_validate(payload.model_dump()),
            newer_genome=newer if status == "available" else None,
            newer_genome_status=status,
        )

    async def get_genome_download_links(self, genome_id: str) -> DownloadLinksResult:
        try:
            identifier = TypeAdapter(UUIDString).validate_python(genome_id, strict=True)
        except ValidationError:
            raise LookupError("input_validation", "Provide a genome UUID.") from None
        explanation = await self.explain_genome(identifier)
        links = await self.get(self.metadata_path(identifier, "ftplinks"), None, list[DownloadLink])
        return DownloadLinksResult(
            genome_id=identifier, links=links, newer_genome=explanation.newer_genome,
            newer_genome_status=explanation.newer_genome_status,
        )
