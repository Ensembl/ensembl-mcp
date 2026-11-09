import { App } from "@modelcontextprotocol/ext-apps";
import { contextUrl, locationLabel, parseView, selectedFeature, selectionContext, shiftedLocation } from "./contracts";
import type { Catalogue, Location, Selection, View } from "./contracts";
import { Renderer } from "./renderer";

const app = new App({ name: "Ensembl genome browser", version: "1.0.0" }, {});
const element = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let view: View | undefined;
let declared: { view: View; catalogue: Catalogue } | undefined;
let selection: Selection | null = null;
let renderer: Renderer | undefined;
let sequence = 0;
let renderTimer: ReturnType<typeof setTimeout> | undefined;
let stopped = false;
// Serialise creation/teardown: WASM initialisation can finish after a new result.
let renderQueue = Promise.resolve();

function status(message: string, error = false) {
  element("status").textContent = message;
  element("status").dataset.error = String(error);
}
function failure(error: unknown) {
  status(error instanceof Error ? error.message : String(error), true);
}
function labels() {
  if (!view) return;
  element("title").textContent = view.genome.scientific_name;
  element("identity").textContent = `${view.genome.assembly_accession ?? "Assembly unreported"} · release ${view.genome.release_number ?? "unreported"} · ${view.genome.genome_id}`;
  element("location").textContent = locationLabel(view.location);
  const link = element<HTMLAnchorElement>("external");
  link.href = contextUrl(view, selection); link.hidden = false;
  element("selection").textContent = selection ? `Selected ${selection.type}: ${selection.feature_id}` : "Select a gene in the browser to discuss it.";
  element<HTMLButtonElement>("explain").disabled = !selection;
}
async function shareSelection() {
  if (!view || !selection) return;
  await app.updateModelContext({ content: [{ type: "text", text: JSON.stringify(selectionContext(view, selection)) }] });
}
function reporter(type: string, payload: unknown) {
  if (!view || stopped) return;
  if (type === "error" || type === "out-of-date") {
    clearTimeout(renderTimer);
    status("The renderer could not load this view. Check genome/backend compatibility or open it in Ensembl.", true);
  } else if (type === "current_position") {
    const position = payload as { stick?: string; start?: number; end?: number };
    if (position.stick === `${view.genome.genome_id}:${view.location.region}` &&
        Number.isFinite(position.start) && Number.isFinite(position.end)) {
      const start = Math.max(1, Math.round(position.start!));
      const end = Math.min(view.location.region_length, Math.round(position.end!));
      if (start <= end) { view = { ...view, location: { ...view.location, start, end } }; labels(); }
    }
    // Continuous motion stays local; never send model-context updates here.
  } else if (type === "track_summary") {
    const summary = (payload as { summary?: unknown[] })?.summary;
    if (summary?.length && element("status").dataset.error !== "true") {
      clearTimeout(renderTimer); status("Tracks loaded. Select a gene to discuss its annotation.");
    }
  } else if (type === "hotspot") {
    const feature = selectedFeature(payload);
    if (feature) { selection = feature; labels(); void shareSelection().catch(failure); }
  }
}

function show(next: View, catalogue: Catalogue) {
  const revision = ++sequence;
  renderQueue = renderQueue.then(async () => {
    if (revision !== sequence || stopped) return;
    renderer?.dispose(); renderer = undefined;
    clearTimeout(renderTimer);
    element("browser").replaceChildren();
    view = structuredClone(next);
    selection = view.gene_id ? { gene_id: view.gene_id, feature_id: view.gene_id, type: "gene" } : null;
    labels(); status("Loading Ensembl tracks…");
    for (const id of ["left", "right", "zoom-in", "zoom-out", "reset"]) element<HTMLButtonElement>(id).disabled = true;
    const controls = element("tracks"); controls.replaceChildren();
    const created = await Renderer.create(element("browser"), view, catalogue, reporter, message => status(message, true));
    if (revision !== sequence || stopped) { created.dispose(); return; }
    renderer = created;
    for (const track of view.initial_tracks) {
      const label = document.createElement("label");
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = true;
      checkbox.addEventListener("change", () => renderer?.toggle(track.track_id, checkbox.checked));
      label.append(checkbox, ` ${track.label}${track.additional_info ? ` (${track.additional_info})` : ""}`);
      controls.append(label);
    }
    for (const id of ["left", "right", "zoom-in", "zoom-out", "reset"]) element<HTMLButtonElement>(id).disabled = false;
    renderTimer = setTimeout(() => status("Tracks have not finished loading. Check the browser connection or open this location in Ensembl.", true), 45000);
  }).catch(failure);
  return renderQueue;
}

type Result = { isError?: boolean; structuredContent?: unknown; _meta?: Record<string, unknown>; content?: unknown };
async function receive(result: Result, declare = true) {
  if (result.isError) throw new Error("The requested view could not be loaded. Check the genome, gene or interval and try again.");
  // Unrelated follow-up gene-detail results must not overwrite the active view.
  if ((result.structuredContent as Partial<View>)?.schema_version !== 1) return;
  const next = parseView(result.structuredContent);
  const catalogue = result._meta?.["ensembl/trackCatalogue"] as Catalogue;
  if (!Array.isArray(catalogue?.track_categories)) throw new Error("The host did not supply the server-fetched track catalogue.");
  if (declare) declared = { view: structuredClone(next), catalogue };
  await show(next, catalogue);
}

async function navigateGene(geneId: string) {
  if (!view) return;
  status("Looking up this gene…");
  const result = await app.callServerTool({ name: "show_genome_browser", arguments: { genome_id: view.genome.genome_id, gene_id: geneId } });
  await receive(result);
}
element("search").addEventListener("click", async () => {
  if (!view) return;
  const query = element<HTMLInputElement>("gene-input").value.trim();
  if (!query) return;
  const search = element<HTMLButtonElement>("search"); search.disabled = true;
  const matches = element<HTMLSelectElement>("matches"); matches.hidden = true; matches.replaceChildren();
  try {
    // A stable ID returned by the selection can go straight to the exact lookup.
    if (/^ENS[A-Z]*G\d+(?:\.\d+)?$/.test(query)) { await navigateGene(query); return; }
    status("Finding genes in this genome…");
    const result = await app.callServerTool({ name: "find_gene", arguments: { genome_id: view.genome.genome_id, symbol: query } });
    if (result.isError) throw new Error("Gene lookup failed. Try again or open Ensembl.");
    const data = result.structuredContent as { genome?: { genome_id: string }; genes?: { stable_id: string; symbol: string | null }[] };
    if (data?.genome?.genome_id !== view.genome.genome_id || !Array.isArray(data.genes)) throw new Error("Gene lookup returned an incompatible genome or result.");
    if (!data.genes.length) { status("No matching genes in the selected genome."); return; }
    if (data.genes.length === 1) { await navigateGene(data.genes[0].stable_id); return; }
    matches.append(new Option("Choose a gene match…", ""));
    for (const gene of data.genes) matches.append(new Option(`${gene.symbol ?? "Gene"} · ${gene.stable_id}`, gene.stable_id));
    matches.hidden = false; status("Several genes matched. Choose the intended stable identifier.");
  } catch (error) { failure(error); } finally { search.disabled = false; }
});
element("gene-input").addEventListener("keydown", event => {
  if (event.key === "Enter") element<HTMLButtonElement>("search").click();
});
element<HTMLSelectElement>("matches").addEventListener("change", event => {
  const id = (event.target as HTMLSelectElement).value;
  if (id) void navigateGene(id).catch(failure);
});
for (const [id, pan, scale] of [["left", -.5, 1], ["right", .5, 1], ["zoom-in", 0, .5], ["zoom-out", 0, 2]] as const) {
  element(id).addEventListener("click", () => {
    if (!view || !renderer) return;
    view = { ...view, location: shiftedLocation(view.location, pan, scale) };
    renderer.navigate(view.genome.genome_id, view.location); labels();
  });
}
element("reset").addEventListener("click", () => { if (declared) void show(declared.view, declared.catalogue); });
element("explain").addEventListener("click", async () => {
  if (!view || !selection) return;
  try {
    await shareSelection();
    await app.sendMessage({ role: "user", content: [{ type: "text", text:
      `Explain selected ${selection.type} ${selection.feature_id} in genome ${view.genome.genome_id}, assembly ${view.genome.assembly_accession ?? "unreported"}, release ${view.genome.release_number ?? "unreported"}. Retrieve get_browser_gene for gene ${selection.gene_id} in this exact genome and distinguish annotation from functional evidence.` }] });
  } catch (error) { failure(error); }
});
element("external").addEventListener("click", event => {
  event.preventDefault();
  if (view) void app.openLink({ url: contextUrl(view, selection) }).catch(failure);
});
element("expand").addEventListener("click", async () => {
  try { await app.requestDisplayMode({ mode: document.body.classList.contains("fullscreen") ? "inline" : "fullscreen" }); }
  catch (error) { failure(error); }
});
app.onhostcontextchanged = context => {
  if (context.displayMode) {
    document.body.classList.toggle("fullscreen", context.displayMode === "fullscreen");
    element("expand").textContent = context.displayMode === "fullscreen" ? "Inline view" : "Larger view";
  }
};
app.ontoolresult = result => { void receive(result).catch(failure); };
app.ontoolcancelled = () => status("The browser request was cancelled. Request a view to try again.");
app.onteardown = async () => {
  stopped = true; sequence++; clearTimeout(renderTimer);
  await renderQueue; renderer?.dispose(); renderer = undefined;
  element("browser").replaceChildren(); return {};
};
void app.connect().then(() => {
  element<HTMLButtonElement>("search").disabled = !app.getHostCapabilities()?.serverTools;
  element("expand").hidden = !app.getHostContext()?.availableDisplayModes?.includes("fullscreen");
  if (!view) status("Connected. Waiting for a genome-browser tool result…");
}).catch(() => status("The MCP App connection failed. Reopen this view in a compatible host or use the Ensembl link in the tool result.", true));
