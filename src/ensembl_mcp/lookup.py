"""Reference selection and gene lookup, independent of MCP transport."""

from pydantic import ValidationError

from .graphql import CoreGraphQLClient, LookupError
from .models import FindGeneInput, FindGeneResult, Gene, Genome

GENOMES_QUERY = """
query ResolveReferenceGenome($by_keyword: GenomeBySpecificKeywordInput!) {
  genomes(by_keyword: $by_keyword) {
    genome_id
    scientific_name
    assembly_accession
    release_number
    is_reference
  }
}
"""

GENES_QUERY = """
query FindGenesBySymbol($by_symbol: SymbolInput!) {
  genes(by_symbol: $by_symbol) {
    stable_id
    symbol
    name
    so_term
    transcript_count
    alternative_symbols
  }
}
"""

GENOME_QUERY = """
query GetGenome($by_genome_id: GenomeIDInput!) {
  genome(by_genome_id: $by_genome_id) {
    genome_id
    scientific_name
    assembly_accession
    release_number
    is_reference
  }
}
"""


def select_reference_genome(genomes: list[Genome]) -> Genome:
    if not genomes:
        raise LookupError("species_not_found", "The scientific species name did not resolve.")
    references = [genome for genome in genomes if genome.is_reference]
    if not references:
        raise LookupError("no_reference_genome", "No reference assembly is available for the resolved species.")
    if len(references) > 1:
        raise LookupError("ambiguous_reference_genome", "Multiple reference assemblies were returned for the species.")
    return references[0]


class EnsemblLookup:
    def __init__(self, client: CoreGraphQLClient):
        self.client = client

    async def resolve_reference_genome(self, species: str) -> Genome:
        genomes = await self.client.query_list(
            "ResolveReferenceGenome", GENOMES_QUERY,
            {"by_keyword": {"scientific_name": species}}, "genomes", Genome,
        )
        return select_reference_genome(genomes)

    async def find_genes_by_symbol(self, symbol: str, genome_id: str) -> list[Gene]:
        return await self.client.query_list(
            "FindGenesBySymbol", GENES_QUERY,
            {"by_symbol": {"symbol": symbol, "genome_id": genome_id}}, "genes", Gene,
        )

    async def find_gene(self, symbol: str, species: str | None = None, genome_id: str | None = None) -> FindGeneResult:
        try:
            inputs = FindGeneInput(symbol=symbol, species=species, genome_id=genome_id)
        except ValidationError:
            raise LookupError("input_validation", "Provide a non-blank symbol and species or a genome UUID.") from None
        if inputs.genome_id is not None:
            genome = await self.client.query_object(
                "GetGenome", GENOME_QUERY,
                {"by_genome_id": {"genome_id": inputs.genome_id}}, "genome", Genome,
            )
            if genome.genome_id != inputs.genome_id:
                raise LookupError("upstream_response", "The service returned a different genome UUID.")
            if inputs.species is not None and genome.scientific_name.casefold() != inputs.species.casefold():
                raise LookupError("input_validation", "species does not match the supplied genome UUID.")
        else:
            genome = await self.resolve_reference_genome(inputs.species)
        genes = await self.find_genes_by_symbol(inputs.symbol, genome.genome_id)
        return FindGeneResult(
            symbol=inputs.symbol, species=inputs.species, genome=genome,
            genes=genes, outcome="found" if genes else "not_found",
        )
