import type { View, Catalogue, Location } from "../src/contracts";
export class Renderer {
  static async create(container: HTMLElement, view: View, _catalogue: Catalogue,
      reporter: (type: string, payload: unknown) => void) {
    const canvas = document.createElement("canvas"); canvas.setAttribute("aria-label", "Mock tracks");
    container.append(canvas);
    const select = document.createElement("button"); select.textContent = "Mock gene selection";
    select.onclick = () => reporter("hotspot", { variety: [{ type: "zmenu" }], content: [{ metadata: { type: "gene", versioned_id: "ENSG00000012048.24" } }] });
    container.append(select);
    setTimeout(() => reporter("track_summary", { summary: [{ "switch-id": "genes" }] }), 10);
    return new Renderer(reporter);
  }
  constructor(private reporter: (type: string, payload: unknown) => void) {}
  navigate(genomeId: string, location: Location) { this.reporter("current_position", { stick: `${genomeId}:${location.region}`, start: location.start, end: location.end }); }
  toggle() {}
  dispose() {}
}
