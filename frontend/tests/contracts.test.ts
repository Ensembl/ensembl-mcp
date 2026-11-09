import { describe, it, expect } from "vitest";
import { selectedFeature, shiftedLocation, selectionContext, contextUrl } from "../src/contracts";
import type { View } from "../src/contracts";

describe("browser interactions", () => {
  it("keeps pan and zoom inside the region, including single-base views", () => {
    const location = { region: "13", start: 1, end: 100, region_length: 1000 };
    expect(shiftedLocation(location, -1, 1)).toEqual(location);
    expect(shiftedLocation(location, 1, 1)).toMatchObject({ start: 101, end: 200 });
    expect(shiftedLocation(location, 0, .5)).toMatchObject({ start: 26, end: 75 });
    expect(shiftedLocation(location, 0, 20)).toMatchObject({ start: 1, end: 1000 });
    expect(shiftedLocation({ ...location, end: 1 }, 0, .5)).toMatchObject({ start: 1, end: 10 });
  });
  it("accepts gene and transcript clicks but ignores hover metadata", () => {
    const gene = { metadata: { type: "gene", versioned_id: "ENSG1.2" } };
    expect(selectedFeature({ variety: [{ type: "track-hover" }], content: [gene] })).toBeNull();
    expect(selectedFeature({ variety: [{ type: "zmenu" }], content: [gene] })).toEqual({ type: "gene", gene_id: "ENSG1.2", feature_id: "ENSG1.2" });
    const transcript = { metadata: { type: "transcript", versioned_id: "ENST1.3", gene_id: "ENSG1.2" } };
    expect(selectedFeature({ variety: [{ type: "zmenu" }], content: [transcript] })).toMatchObject({ gene_id: "ENSG1.2", feature_id: "ENST1.3", type: "transcript" });
    expect(selectedFeature({ variety: [{ type: "zmenu" }], content: [transcript, gene] })?.type).toBe("gene");
  });
  it("binds conversation context and external links to the exact selected genome", () => {
    const view = { genome: { genome_id: "genome-1", assembly_accession: "GCA_1", release_number: 2.5 }, location: { region: "13", start: 100, end: 200, region_length: 1000 }, coordinate_system: "1-based inclusive", ensembl_url: "https://example.org/genome-browser/genome-1?focus=gene:OLD" } as View;
    const selection = { type: "gene", gene_id: "ENSG2.4", feature_id: "ENSG2.4" } as const;
    expect(selectionContext(view, selection)).toMatchObject({ genome_id: "genome-1", release_number: 2.5, selected: selection });
    const url = new URL(contextUrl(view, selection));
    expect(url.pathname).toBe("/genome-browser/genome-1");
    expect(url.searchParams.get("location")).toBe("13:100-200");
    expect(url.searchParams.get("focus")).toBe("gene:ENSG2.4");
  });
});
