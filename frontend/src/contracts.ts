export type Genome = {
  genome_id: string; scientific_name: string; assembly_accession: string | null;
  release_number: number | null; is_reference: boolean;
};
export type Location = { region: string; start: number; end: number; region_length: number };
export type Track = {
  track_id: string; label: string; type: string; trigger: string[];
  additional_info: string; display_order: number; on_by_default: boolean;
};
export type Catalogue = { track_categories: { track_list: Track[] }[] };
export type View = {
  schema_version: 1; genome: Genome; gene_id: string | null; location: Location;
  coordinate_system: "1-based inclusive"; initial_tracks: Track[];
  browser_backend_url: string; ensembl_url: string;
};
export type Selection = { gene_id: string; feature_id: string; type: "gene" | "transcript" };

export function locationLabel(location: Location): string {
  return `${location.region}:${location.start.toLocaleString("en-GB")}-${location.end.toLocaleString("en-GB")}`;
}

export function shiftedLocation(location: Location, pan: number, scale: number): Location {
  const width = Math.min(location.region_length, Math.max(10, Math.round((location.end - location.start + 1) * scale)));
  const centre = (location.start + location.end) / 2 + pan * (location.end - location.start + 1);
  const start = Math.max(1, Math.min(location.region_length - width + 1, Math.round(centre - (width - 1) / 2)));
  return { ...location, start, end: start + width - 1 };
}

export function selectedFeature(payload: unknown): Selection | null {
  const value = payload as { variety?: { type: string }[]; content?: { metadata?: Record<string, unknown> }[] };
  if (!value?.variety?.some(item => item.type === "zmenu") || !Array.isArray(value.content)) return null;
  // A gene-and-transcript menu contains two objects. Prefer the gene; never
  // interpret hover/track-summary payloads as a deliberate feature selection.
  for (const type of ["gene", "transcript"] as const) {
    for (const item of value.content) {
      const metadata = item.metadata;
      if (metadata?.type !== type || typeof metadata.versioned_id !== "string") continue;
      if (metadata.versioned_id.length > 128 || !/^[A-Za-z0-9_-]+(?:\.[0-9]+)?$/.test(metadata.versioned_id)) continue;
      const gene = type === "gene" ? metadata.versioned_id : metadata.gene_id;
      if (typeof gene !== "string" || !/^[A-Za-z0-9_-]+(?:\.[0-9]+)?$/.test(gene)) continue;
      return { gene_id: gene, feature_id: metadata.versioned_id, type };
    }
  }
  return null;
}

export function selectionContext(view: View, selection: Selection) {
  return {
    genome_id: view.genome.genome_id, assembly_accession: view.genome.assembly_accession,
    release_number: view.genome.release_number, viewport: view.location,
    coordinate_system: view.coordinate_system, selected: selection,
    evidence_tool: "get_browser_gene",
    instruction: "Retrieve annotation for this exact genome and gene before explaining it; viewport is not the feature's bounds.",
  };
}

export function contextUrl(view: View, selection: Selection | null): string {
  const url = new URL(view.ensembl_url);
  url.searchParams.set("location", `${view.location.region}:${view.location.start}-${view.location.end}`);
  if (selection) url.searchParams.set("focus", `gene:${selection.gene_id}`);
  else url.searchParams.delete("focus");
  return url.href;
}

// Data comes from our typed server, but fail clearly on old/missing host results.
export function parseView(value: unknown): View {
  const view = value as View;
  if (!view || view.schema_version !== 1 || !view.genome?.genome_id ||
      !view.location?.region || !Number.isSafeInteger(view.location.start) ||
      !Number.isSafeInteger(view.location.end) || view.location.start < 1 ||
      view.location.end < view.location.start || view.location.end > view.location.region_length ||
      view.coordinate_system !== "1-based inclusive" || !view.initial_tracks?.length ||
      new URL(view.browser_backend_url).protocol !== "https:" || new URL(view.ensembl_url).protocol !== "https:") {
    throw new Error("The host returned an invalid or incompatible browser view.");
  }
  return view;
}
