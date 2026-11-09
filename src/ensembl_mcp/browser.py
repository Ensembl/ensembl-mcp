"""Genome-browser contracts and server-side biological lookups.

Coordinates use Ensembl's 1-based inclusive convention, as does the website's
adapter to GenomeBrowser.goto. No interval conversion is performed in the UI.
"""

from typing import Annotated, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from .config import Settings
from .graphql import CoreGraphQLClient, LookupError
from .lookup import GENOME_QUERY
from .models import Gene, Genome, UpstreamModel

UI_URI = "ui://ensembl/genome-browser/v1.html"
DEMO_GENOME = "59871324-7803-4234-856e-2a2bd96d7b3c"
GenomeID = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
GeneID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+(?:\.[0-9]+)?$", max_length=128)]
RegionName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+$", max_length=128)]
Coordinate = Annotated[int, Field(ge=1, le=2**53 - 1)]


class BrowserInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    genome_id: GenomeID
    gene_id: GeneID | None = None
    region: RegionName | None = None
    start: Coordinate | None = None
    end: Coordinate | None = None

    @model_validator(mode="after")
    def one_location(self):
        interval = (self.region, self.start, self.end)
        if self.gene_id is not None:
            if any(value is not None for value in interval):
                raise ValueError("Gene and interval are mutually exclusive")
        elif any(value is None for value in interval) or self.start > self.end:
            raise ValueError("Provide a complete ordered interval")
        return self


class Region(UpstreamModel):
    name: RegionName
    length: Coordinate


class Location(UpstreamModel):
    start: Coordinate
    end: Coordinate

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Reversed interval")
        return self


class Slice(UpstreamModel):
    location: Location
    region: Region

    @model_validator(mode="after")
    def in_bounds(self):
        if self.location.end > self.region.length:
            raise ValueError("Interval outside region")
        return self


class LocatedGene(Gene):
    slice: Slice


class GeneDetails(BaseModel):
    genome: Genome
    gene: LocatedGene
    coordinate_system: Literal["1-based inclusive"] = "1-based inclusive"


class BrowserLocation(Location):
    region: RegionName
    region_length: Coordinate


class Track(UpstreamModel):
    track_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: str
    trigger: list[str] = Field(min_length=2, max_length=4)
    display_order: int
    on_by_default: bool
    additional_info: str = ""

    @model_validator(mode="after")
    def valid_trigger(self):
        if self.trigger[0] != "track" or any(not part for part in self.trigger):
            raise ValueError("Invalid track trigger")
        return self


class TrackCategory(UpstreamModel):
    label: str
    track_category_id: str
    track_list: list[Track]


class Catalogue(UpstreamModel):
    track_categories: list[TrackCategory]


class BrowserView(BaseModel):
    schema_version: Literal[1] = 1
    genome: Genome
    gene_id: str | None
    location: BrowserLocation
    coordinate_system: Literal["1-based inclusive"] = "1-based inclusive"
    initial_tracks: list[Track]
    browser_backend_url: str
    ensembl_url: str


GENE_QUERY = """
query BrowserGene($genomeId: String!, $geneId: String!) {
  gene(by_id: {genome_id: $genomeId, stable_id: $geneId}) {
    stable_id symbol name so_term transcript_count alternative_symbols
    slice { location { start end } region { name length } }
  }
}
"""
REGION_QUERY = """
query BrowserRegion($genomeId: String!, $regionName: String!) {
  region(by_name: {genome_id: $genomeId, name: $regionName}) { name length }
}
"""


class BrowserService:
    def __init__(self, http: httpx.AsyncClient, core: CoreGraphQLClient, settings: Settings):
        self.http, self.core, self.settings = http, core, settings

    def validate(self, **arguments) -> BrowserInput:
        try:
            inputs = BrowserInput(**arguments)
        except ValidationError:
            raise LookupError("input_validation", "Provide a genome UUID and either a gene stable ID or a complete 1-based inclusive interval (1 <= start <= end).") from None
        if inputs.genome_id not in self.settings.browser_genome_ids:
            raise LookupError("unsupported_browser_genome", "This genome is not enabled for the configured browser backend; no alternative genome was selected.")
        return inputs

    async def genome(self, genome_id: str) -> Genome:
        genome = await self.core.query_object("GetGenome", GENOME_QUERY,
            {"by_genome_id": {"genome_id": genome_id}}, "genome", Genome,
            not_found_message="The selected genome is unavailable in Core GraphQL.")
        if genome.genome_id != genome_id:
            raise LookupError("upstream_response", "The service returned a different genome UUID.")
        return genome

    async def gene(self, inputs: BrowserInput) -> LocatedGene:
        gene = await self.core.query_object("BrowserGene", GENE_QUERY,
            {"genomeId": inputs.genome_id, "geneId": inputs.gene_id}, "gene", LocatedGene,
            not_found_message="This gene stable ID is unavailable in the selected genome.")
        # A versionless request may resolve to a versioned ID; an explicit version
        # must never be silently replaced.
        if gene.stable_id != inputs.gene_id and not (
            "." not in inputs.gene_id and gene.stable_id.rsplit(".", 1)[0] == inputs.gene_id
        ):
            raise LookupError("upstream_response", "The service returned a different gene stable ID.")
        return gene

    async def gene_details(self, genome_id: str, gene_id: str) -> GeneDetails:
        inputs = self.validate(genome_id=genome_id, gene_id=gene_id)
        return GeneDetails(genome=await self.genome(inputs.genome_id), gene=await self.gene(inputs))

    async def catalogue(self, genome_id: str) -> Catalogue:
        if self.settings.tracks_url is None:
            raise LookupError("tracks_not_configured", "Set ENSEMBL_TRACKS_API_URL to enable the genome browser.")
        try:
            response = await self.http.get(f"{self.settings.tracks_url.rstrip('/')}/track_categories/{genome_id}")
            response.raise_for_status()
            catalogue = Catalogue.model_validate(response.json())
        except (httpx.HTTPError, ValueError):
            raise LookupError("catalogue_unavailable", "The track catalogue is unavailable or invalid for the selected genome.") from None
        ids = [track.track_id for category in catalogue.track_categories for track in category.track_list]
        if len(ids) != len(set(ids)):
            raise LookupError("catalogue_unavailable", "The track catalogue contains duplicate identifiers.")
        return catalogue

    async def show(self, **arguments) -> tuple[BrowserView, Catalogue]:
        inputs = self.validate(**arguments)
        genome = await self.genome(inputs.genome_id)
        gene_id = None
        if inputs.gene_id:
            gene = await self.gene(inputs)
            gene_id = gene.stable_id
            region = gene.slice.region
            location = gene.slice.location
        else:
            region = await self.core.query_object("BrowserRegion", REGION_QUERY,
                {"genomeId": inputs.genome_id, "regionName": inputs.region}, "region", Region,
                not_found_message="This region is unavailable in the selected genome.")
            if region.name != inputs.region:
                raise LookupError("upstream_response", "The service returned a different region.")
            if inputs.end > region.length:
                raise LookupError("input_validation", "The interval extends beyond the selected region's length.")
            location = Location(start=inputs.start, end=inputs.end)
        catalogue = await self.catalogue(inputs.genome_id)
        tracks = [t for c in catalogue.track_categories for t in c.track_list]
        # The pilot supports the renderer's gene tracks and reference sequence.
        initial = sorted([t for t in tracks if t.type == "gene" or t.trigger == ["track", "contig"]], key=lambda t: t.display_order)
        if not any(t.type == "gene" for t in initial) or not any(t.trigger == ["track", "contig"] for t in initial):
            raise LookupError("unsupported_browser_tracks", "The selected genome needs both gene and reference-sequence tracks for this pilot.")
        query = {"location": f"{region.name}:{location.start}-{location.end}"}
        if gene_id:
            query["focus"] = f"gene:{gene_id}"
        return BrowserView(
            genome=genome, gene_id=gene_id,
            location=BrowserLocation(**location.model_dump(), region=region.name, region_length=region.length),
            initial_tracks=initial, browser_backend_url=self.settings.browser_backend_url.rstrip("/"),
            ensembl_url=f"{self.settings.browser_website_url.rstrip('/')}/genome-browser/{genome.genome_id}?{urlencode(query)}",
        ), catalogue
