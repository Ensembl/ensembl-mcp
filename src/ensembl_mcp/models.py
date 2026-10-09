"""Input and result contracts; nullable fields remain present in results."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

NonBlankString = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]


class FindGeneInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    symbol: NonBlankString
    species: NonBlankString


class UpstreamModel(BaseModel):
    model_config = ConfigDict(strict=True)


class Genome(UpstreamModel):
    genome_id: Annotated[str, StringConstraints(min_length=1)]
    scientific_name: Annotated[str, StringConstraints(min_length=1)]
    assembly_accession: str | None
    release_number: float | None  # Upstream GraphQL Float; do not truncate releases.
    is_reference: bool


class Gene(UpstreamModel):
    stable_id: Annotated[str, StringConstraints(min_length=1)]
    symbol: str | None
    name: str | None
    so_term: str | None
    transcript_count: int | None
    alternative_symbols: list[str | None] | None


class FindGeneResult(BaseModel):
    symbol: str
    species: str
    genome: Genome
    genes: list[Gene]
    outcome: Literal["found", "not_found"]
