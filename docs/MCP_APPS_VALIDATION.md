# MCP Apps implementation and validation

Recorded 9 November 2026. The baseline website/HTTP observations remain in
`MCP_APPS_PLAN.md`. This report records checks of the implementation in this
repository, not acceptance inside ChatGPT desktop.

## Implemented

- Versioned MCP Apps HTML resource, standard UI metadata/CSP and plain-text fallback.
- `show_genome_browser`, fixed-interval `demo_genome_browser`, and narrow
  `get_browser_gene` annotation retrieval. Existing four tools remain available.
- Explicit genome allowlist, exact identity checks, gene-version checks, region
  bounds and 1-based inclusive coordinates. Catalogue access stays server-side.
- TypeScript UI wrapping the real Ensembl WebAssembly/WebGL renderer: pan/zoom,
  gene navigation with explicit ambiguity selection, initial gene/sequence tracks,
  track toggles, status/error states, larger-view requests and context links.
- Feature selection and explicit explanation requests through the MCP Apps bridge.
  Pan/hover events stay local. Reopening uses the tool-declared state.
- Locked frontend build, self-contained compressed WASM, Python package data,
  a wheel build guard and a multi-stage Docker build. `/mcp` is unchanged.

## Observed results

| Layer | Evidence | Boundary |
| --- | --- | --- |
| Python offline | **228 tests pass**: validation, mismatched genomes/genes/regions, malformed/missing catalogues, unsupported tracks, resource retrieval/CSP over MCP and `/mcp` HTTP, plain-text fallback and existing-tool regression. | Upstreams mocked; no TCP. |
| TypeScript offline | Six tests cover interval bounds, gene/transcript selection, context identity/links, UUID track commands, credential omission and network failures. | No biological data rendering. |
| Browser interaction | Three Chrome tests exercise the actual MCP Apps SDK in an iframe with a local test host: pan/zoom, selection messages, ambiguous/empty gene search, unrelated results, missing catalogue, larger view and reopening. | Renderer and biological results mocked. |
| Live MCP calls | `scripts/browser_live_fixture.py --live` calls this implementation through FastMCP using the development HTTPS Core and Tracks routes; both browser tools and selected-gene lookup pass. | Local MCP process; does not exercise the deployed pod or discovery endpoint. |
| Live renderer | Renderer **0.6.14**, MCP Apps SDK **2.0.4**, Chrome **156.0.8078.80**. BRCA2 and chromosome 17 render real gene tracks; pan/zoom settle to new positions. Both `/hi` and `/lo` return HTTP 200 CBOR. Observed fetch options use `credentials: omit`; no page errors. | Local `http://127.0.0.1:4175` test host and sandboxed iframe, not ChatGPT's origin or CSP. |
| Live selection | A click on the chromosome 17 ICAM2 track selects **ENSG00000108622.13**. The explanation button sends a context/message request to the local host with the selected genome and identifier. | No ChatGPT model response was generated or evaluated. |
| Packaging | Python wheel built successfully; archive inspection confirms the compiled HTML is included (approximately 2.27 MiB before wheel compression). | Docker daemon was unavailable; image and Kubernetes runtime not verified. |

Live MCP lookup resolved BRCA2 to `ENSG00000139618.19`, interval
`13:32,315,086-32,400,268`, in genome
`59871324-7803-4234-856e-2a2bd96d7b3c`, assembly `GCA_000001405.29`, Core release
`2.0`. This establishes that lookup works through Core for this genome. The
reported website BRCA2 zero-result search remains unresolved and is outside this
implementation's repair scope.

The live catalogue's legacy `trigger` entries initially enabled no genomic tracks
with renderer 0.6.14. Inspection of the website adapter and the live interval test
established the required command: `['track', 'expand', track_id]`. The corrected
adapter uses server-supplied UUIDs, with a regression test. Focus-gene rendering
alone was not counted as an interval-rendering success.

Screenshots and network summaries are reproducible local outputs under
`frontend/test-results/`; live tool fixtures are in `frontend/.live-fixtures/`.
Both directories are ignored by Git and excluded from the image. Run the commands
in the README to regenerate them. The local host is a test harness, not a
replacement MCP transport or a proxy for biological data.

## Remaining deployment and desktop acceptance

The plan's final acceptance criterion is **not yet established**. No app was
installed in ChatGPT and no updated image was deployed in this work.

1. Verify the complete Search Hub URL and response schema from the MCP pod. The
   checked-in ConfigMap still uses a metadata service base URL as discovery URL;
   this server expects a full Search Hub endpoint returning `matches` and `meta`.
   Configure `ENSEMBL_METADATA_API_URL` independently if using metadata tools.
2. Verify pod access to the Tracks service and add `ENSEMBL_TRACKS_API_URL` to
   deployment configuration. The proposed internal base is
   `http://ensembl-track-api-svc.ensembl-dev:8012`; no in-pod reachability claim is made.
3. Build/deploy the image, refresh the development app connection, and record its
   connection method, ChatGPT desktop version and actual app origin.
4. Run `demo_genome_browser`, then the human BRCA2 discovery/selection journey.
   Check actual WebAssembly/WebGL availability, resource-size/CSP limits, both
   priority-route preflights/responses, and credential-free requests in the host.
5. Check track toggles, sequence at base resolution, resizing/larger view, both
   loci, closing/reopening, and failure recovery in that client.
6. Select another gene and ask for an explanation. Confirm the assistant retrieves
   `get_browser_gene` using the exact selected genome/ID and distinguishes annotation
   from functional evidence. Record whether new tool results update the active view
   or create a separate view.

Do not infer these outcomes from the successful local sandbox tests. In particular,
the local sandbox does not reproduce ChatGPT's CSP or prove that the 2.27 MiB
resource is accepted by the target client.

## Sources used for integration

- [MCP Apps overview](https://modelcontextprotocol.io/extensions/apps/overview)
- [ChatGPT UI integration](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Renderer repository](https://github.com/Ensembl/ensembl-genome-browser)
- [Renderer priority routing](https://github.com/Ensembl/ensembl-dauphin-style-compiler/blob/master/febe-network/src/networkchannel.rs)
- Local `ensembl-client` adapters: `genomeBrowserCommands.ts`, `useGenomeBrowser.ts`,
  `useGenomicTracks.ts`, `genomeBrowserLocation.ts`, and `zmenu.ts`.

The exact renderer-backend deployment revision has not been recorded.
