import initialize, { GenomeBrowser } from "@ensembl/ensembl-genome-browser";
import type { Catalogue, View, Location } from "./contracts";

declare const __WASM_GZIP_BASE64__: string;
let initialized: Promise<unknown> | undefined;

// Renderer 0.6.14 uses catalogue UUIDs under track/expand, as in ensembl-client's
// getTrackPath(). The API still returns legacy trigger paths (gene-pc-fwd,
// contig, etc.); these silently do nothing in this renderer. Keep them only as
// catalogue metadata; never pass them through as renderer commands.
export function trackPath(trackId: string): string[] { return ["track", "expand", trackId]; }

async function initWasm() {
  const compressed = Uint8Array.from(atob(__WASM_GZIP_BASE64__), character => character.charCodeAt(0));
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip"));
  const bytes = await new Response(stream).arrayBuffer();
  return initialize({ module_or_path: bytes });
}

// The WASM renderer owns fetch calls. Enforce credential-free requests at this
// narrow boundary even if a future renderer release changes its fetch defaults.
// Other requests are untouched; there is no global credential or cookie access.
export function installBackendFetchPolicy(base: string, onFailure: (message: string) => void): () => void {
  const original = window.fetch;
  const backend = new URL(base);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    const isBackend = url.origin === backend.origin &&
      (url.pathname === `${backend.pathname}/hi` || url.pathname === `${backend.pathname}/lo`);
    if (!isBackend) return original.call(window, input, init);
    try {
      const response = await original.call(window, input, { ...init, credentials: "omit", mode: "cors" });
      if (!response.ok) onFailure(`Browser data request failed (HTTP ${response.status}).`);
      return response;
    } catch (error) {
      onFailure("Browser data could not be reached. Check the app's network policy and both priority routes.");
      throw error;
    }
  };
  return () => { window.fetch = original; };
}

export class Renderer {
  private browser: GenomeBrowser;
  private restoreFetch: () => void;

  private constructor(container: HTMLElement, view: View, catalogue: Catalogue,
      reporter: (type: string, payload: unknown) => void, failure: (message: string) => void) {
    this.restoreFetch = installBackendFetchPolicy(view.browser_backend_url, failure);
    this.browser = new GenomeBrowser();
    this.browser.set_message_reporter(reporter);
    this.browser.go({ backend_url: view.browser_backend_url, target_element: container });
    this.browser.switch(["settings", "tab-selected"], "Genomic");
    const enabled = new Set(view.initial_tracks.map(track => track.track_id));
    for (const category of catalogue.track_categories) {
      for (const track of category.track_list) this.browser.switch(trackPath(track.track_id), enabled.has(track.track_id));
    }
    for (const track of view.initial_tracks) {
      if (track.type === "gene") this.browser.switch([...trackPath(track.track_id), "label"], true);
    }
    this.navigate(view.genome.genome_id, view.location);
    if (view.gene_id) {
      this.browser.switch(["track", "focus"], true);
      this.browser.switch(["track", "focus", "label"], true);
      this.browser.switch(["track", "focus", "item", "gene"], {
        genome_id: view.genome.genome_id, item_id: view.gene_id,
      });
    }
  }

  static async create(container: HTMLElement, view: View, catalogue: Catalogue,
      reporter: (type: string, payload: unknown) => void, failure: (message: string) => void) {
    if (typeof WebAssembly === "undefined" || typeof DecompressionStream === "undefined") {
      throw new Error("This host cannot initialise the bundled WebAssembly renderer.");
    }
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl");
    if (!gl) throw new Error("WebGL is unavailable in this host. Open this location in Ensembl.");
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    initialized ??= initWasm().catch(error => { initialized = undefined; throw error; });
    await initialized;
    return new Renderer(container, view, catalogue, reporter, failure);
  }

  navigate(genomeId: string, location: Location) {
    this.browser.set_stick(`${genomeId}:${location.region}`);
    this.browser.goto(location.start, location.end);
    this.browser.wait();
  }
  toggle(trackId: string, enabled: boolean) { this.browser.switch(trackPath(trackId), enabled); }
  dispose() {
    this.browser.set_message_reporter(() => {});
    this.browser.free();
    this.restoreFetch();
  }
}
