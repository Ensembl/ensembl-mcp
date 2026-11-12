# Ensembl MCP

An Ensembl server for the **Model Context Protocol (MCP)**, which allows AI applications to discover and use tools for accessing Ensembl data.

This pilot supports the development and evaluation of the [EMBL-EBI MCP guidelines](https://github.com/EMBL-EBI-ABC/ebi-mcp-guidelines).

## Status and purpose

The pilot exposes seven read-only tools using Python and the `fastmcp` package, including an MCP App for the Ensembl genome browser:

```text
find_genomes(query="human", reference_only=True)
find_gene(symbol="BRCA2", species="Homo sapiens")
find_gene(symbol="BRCA2", genome_id="<UUID returned by find_genomes>")
explain_genome(id_or_accession="GCA_000001405.29")
get_genome_download_links(genome_id="<selected genome UUID>")
show_genome_browser(genome_id="<selected supported genome UUID>", gene_id="<gene stable ID>")
demo_genome_browser()
get_browser_gene(genome_id="<selection genome UUID>", gene_id="<selected gene stable ID>")
```

For `find_gene`, `symbol` is required, along with either `species` or `genome_id`. Surrounding whitespace is removed and blank values are rejected before any upstream request. Symbol case is preserved. `species` must be a scientific name. A supplied genome UUID skips species resolution and permits non-reference genomes. If both selectors are supplied, the scientific name must match the UUID’s genome (case-insensitively).

Without a UUID, `find_gene` resolves the species reference genome through Ensembl Core GraphQL. With a UUID, it fetches that genome’s context directly and uses exactly that UUID for the gene query. Both paths return all symbol matches. No tool automatically substitutes a newer genome UUID.

This is early development, not a production service. Offline tests use mocked upstream responses. On 9 November 2026, the browser tools were also checked against live development services, and real tracks were rendered in a local Chrome sandbox. These checks do **not** establish rendering or conversation behaviour in ChatGPT desktop. The initial server has previously been deployed in `mcp-poc-public`; this implementation does not deploy the updated image or change Kubernetes manifests.

## Install and run locally

The supported runtime for v0.1 is **Python 3.12** with **FastMCP 4.1.2**, pinned in `pyproject.toml`. HTTP calls use HTTPX 0.28.1. From the repository root:

```sh
python3.12 -m pip install uv==0.13.7
uv sync --frozen --extra test
(cd frontend && npm ci && npm run build)
export ENSEMBL_CORE_GRAPHQL_URL='https://your-reachable-core-graphql-endpoint/graphql'
export ENSEMBL_GENOME_SEARCH_URL='https://your-reachable-genome-search-endpoint/api/search/genomes/v3'
MCP_TRANSPORT=stdio .venv/bin/ensembl-mcp
```

After changing Python dependencies, run `uv lock` and `uv export --frozen --no-dev --no-emit-project --no-header --format requirements-txt --output-file requirements.lock`, then commit both lockfiles. Docker installs the hash-checked runtime export.

Replace the example URL with your actual Core GraphQL endpoint. Local execution defaults to **stdio** and waits for MCP messages; an MCP client normally starts the process itself. The equivalent module entry point is `.venv/bin/python -m ensembl_mcp.server`. Configuration is read from the process environment; `.env` files are not automatically loaded.

To run the HTTP server locally with the same transport as the container:

```sh
MCP_TRANSPORT=streamable-http MCP_PORT=8000 .venv/bin/ensembl-mcp
```

This listens on **`0.0.0.0:8000`** and exposes **`/mcp`**. Connect locally using `http://localhost:8000/mcp`. The existing FastMCP package and its MCP Python SDK implement [Streamable HTTP](https://gofastmcp.com/deployment/running-server#http-transport-streamable); this is not the legacy SSE transport. HTTP requests are stateless, so they do not require a pod-specific MCP session. The server supports `initialize`, `notifications/initialized`, `tools/list` and `tools/call` through this endpoint, including SDK-managed response streaming.

HTTP now permits only loopback Host names by default and rejects every supplied Origin unless explicitly allowed. For a public host, set `MCP_ALLOWED_HOSTS` and any required `MCP_ALLOWED_ORIGINS`. Request size, rate, concurrency and total-operation limits are enabled.

The proxy must preserve the original Host header. Forwarding headers are not trusted, and these limits apply per process; configure shared quotas at the ingress when using multiple replicas. Host/Origin checks do not provide authentication or enable CORS.

### Configuration

| Variable | Requirement and default |
| --- | --- |
| `MCP_TRANSPORT` | `stdio` or `streamable-http` only. Defaults to `stdio` when unset locally; the Docker image sets `streamable-http`. Surrounding whitespace is trimmed. |
| `MCP_PORT` | Integer from `1` to `65535`, default `8000`. Validated at startup; used only for HTTP. The HTTP bind address is fixed at `0.0.0.0` and the endpoint path at `/mcp`. |
| `MCP_ALLOWED_HOSTS` | Comma-separated hostnames without schemes or ports. Defaults to `localhost,127.0.0.1,[::1]`; set the actual public hostname for remote HTTP access. Wildcards are rejected. |
| `MCP_ALLOWED_ORIGINS` | Comma-separated exact HTTP(S) origins, including any port and without a trailing slash. Defaults to empty: requests with an Origin header are denied. Native clients normally omit Origin. |
| `MCP_REQUESTS_PER_MINUTE` | Process-wide token bucket, default `120`; burst capacity equals this number. |
| `MCP_MAX_CONCURRENT_REQUESTS` | Maximum active HTTP requests, default `16`; overload is rejected without queueing. |
| `MCP_MAX_REQUEST_BYTES` | Maximum actual request-body size before JSON parsing, default `65536` bytes, including chunked requests. |
| `MCP_REQUEST_TIMEOUT_SECONDS` | Total HTTP request lifetime, including body upload and streaming, default `30` seconds. |
| `MCP_MAX_CONCURRENT_TOOLS` | Maximum active tool calls across HTTP and stdio, default `8`. |
| `MCP_TOOL_TIMEOUT_SECONDS` | Total tool execution deadline across all upstream calls, default `20` seconds. |
| `ENSEMBL_GENOME_SEARCH_URL` | Required full Search Hub search URL. No default or fallback. Missing, blank, or invalid values stop startup. |
| `ENSEMBL_METADATA_API_URL` | Metadata API base URL, including its API prefix (for example `https://your-host/api/metadata`). No default; metadata tools report a configuration error when omitted. |
| `ENSEMBL_CORE_GRAPHQL_URL` | Required absolute `http://` or `https://` URL with a host. Surrounding whitespace is trimmed. Credentials in the URL, fragments, internal whitespace and invalid ports are rejected. There is no runtime default or fallback. |
| `ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS` | Optional finite positive number, default `30`. Used for HTTPX read, write and connection-pool timeouts. Connection timeout is separately fixed at `5` seconds. |
| `ENSEMBL_TRACKS_API_URL` | Tracks API base URL. No default. Browser tools report `tracks_not_configured` when absent; existing tools remain available. |
| `ENSEMBL_BROWSER_BACKEND_URL` | Absolute HTTPS browser data base URL, **without** `/hi` or `/lo`. Default `https://mcp-poc-public.review.ensembl.org/api/browser/data`. |
| `ENSEMBL_BROWSER_WEBSITE_URL` | HTTPS website base for context-preserving links. Default `https://mcp-poc-public.review.ensembl.org`. Must support the same genome and release. |
| `ENSEMBL_BROWSER_GENOME_IDS` | Comma-separated canonical UUID allowlist for the configured browser backend. Default `59871324-7803-4234-856e-2a2bd96d7b3c`. Expand only after checking data compatibility. No automatic genome substitution. |

Invalid configured URLs or missing required Core or Search Hub configuration stop startup with an error on stderr and exit status 2. Search and metadata URL overrides must not contain credentials, query strings, fragments, or whitespace. All upstream clients share the configured HTTP timeout. Configure all three services against compatible environments/releases; a public Search Hub endpoint may not match development Thoas data. Keep credentials and deployment secrets outside the repository.

The observed **cluster-only** Core GraphQL configuration is:

```sh
export ENSEMBL_CORE_GRAPHQL_URL='http://graphql-core-svc.ensembl-dev:8000'
```

That ClusterIP service is in `ensembl-dev`; connectivity from a pod in `mcp-poc-public` was previously reported as successful. The checked-in ConfigMap sets `ENSEMBL_GENOME_SEARCH_URL` to `http://metadata-api-svc.ensembl-dev:8014`, but this client sends its search GET directly to the configured URL and expects Search Hub's `matches`/`meta` response. A service base URL is not established as a compatible search endpoint. Verify its complete path and schema before relying on `find_genomes`; do not silently redirect discovery to a different dataset. The ConfigMap also omits `ENSEMBL_METADATA_API_URL` and `ENSEMBL_TRACKS_API_URL`. Configure metadata separately, and verify `http://ensembl-track-api-svc.ensembl-dev:8012/track_categories/<UUID>` from the MCP pod before using that Tracks API base. The server is not deployed by these instructions.

## Genome browser MCP App

The UI uses the [MCP Apps resource and bridge protocol](https://modelcontextprotocol.io/extensions/apps/overview), supported by the [ChatGPT UI integration](https://developers.openai.com/plugins/build/chatgpt-ui). `show_genome_browser` and the temporary `demo_genome_browser` diagnostic declare `_meta.ui.resourceUri = ui://ensembl/genome-browser/v1.html`. Resource reads return `text/html;profile=mcp-app`, with a CSP connection allowlist derived from the configured browser backend origin.

Build with Node 22+ and npm. The lockfile pins the MCP Apps SDK and renderer (`@ensembl/ensembl-genome-browser` **0.6.14**, from Ensembl's public GitLab npm registry). The generated HTML includes JavaScript, CSS and gzip-compressed WebAssembly. At about 2.27 MiB it needs no CDN, asset ingress route or same-origin `/api` assumption. The host must permit WebAssembly compilation, WebGL and `DecompressionStream`; failures are reported in the view. Resource size limits and actual ChatGPT sandbox policy still need desktop verification.

```sh
(cd frontend && npm ci && npm run build)
.venv/bin/python -m pip wheel . --no-deps --wheel-dir dist
```

Build before creating wheels/sdists. The wheel build fails explicitly if the UI is missing. Docker performs the frontend build in a Node stage, copies the result into the Python package and preserves the existing non-root `/mcp` service. Generated assets and `node_modules` are not committed. Frontend source changes require rebuilding the HTML and the package/image. Change the versioned resource URI when releasing a host-cached incompatible UI revision.

For a local process reaching the existing development ingress, add:

```sh
export ENSEMBL_TRACKS_API_URL='https://mcp-poc-public.review.ensembl.org/api/tracks'
```

Keep the normal Core GraphQL and Search Hub configuration. Core lookups and catalogue requests run **server-side**. Only high-frequency binary track data goes from the renderer to `.../api/browser/data/hi` and `/lo`; both existing HTTPS routes are required. Fetches to those routes explicitly use `credentials: "omit"` and CORS mode. Do not add cookies or authentication to these wildcard-CORS requests. The Tracks API's missing CORS response is irrelevant to the app because the browser never fetches its catalogue directly.

### Browser contract and supported pilot

`show_genome_browser(genome_id, gene_id=None, region=None, start=None, end=None)` requires exactly one of a gene stable ID or a complete interval. Coordinates are **1-based inclusive** throughout; the website's `setBrowserLocation` adapter passes this convention to `GenomeBrowser.goto` without subtracting one. The server checks region length and rejects incompatible genome UUIDs, gene versions, returned region names and out-of-bounds intervals. Missing catalogues, invalid catalogues and missing supported tracks are errors rather than empty successes.

Only the explicitly configured human genome is enabled by default: UUID `59871324-7803-4234-856e-2a2bd96d7b3c`, assembly `GCA_000001405.29`, Core release `2.0` as observed on 9 November. Those assembly/release values are retrieved on each call, never substituted from this documentation. Gene and reference-sequence tracks are supported. Track identifiers come from the server-fetched catalogue; renderer 0.6.14 uses `['track', 'expand', track_id]`, matching the website. The catalogue's legacy `trigger` paths are retained as metadata but are not passed to this renderer. Regulation, variants, private tracks and uploads are outside this pilot.

`structuredContent` contains a versioned `BrowserView`: genome/assembly/release, exact gene ID when requested, validated location, initial supported tracks, browser backend URL and website URL. The catalogue is sent in `_meta['ensembl/trackCatalogue']` for the component only. Model-visible text includes the coordinates and an Ensembl link and does not claim that rendering succeeded. Ordinary MCP clients can use those results without displaying HTML.

The UI provides pan/zoom, gene-symbol or stable-ID navigation, track toggles, loading/failure/empty-search states, and a larger-view request when offered by the host. Ambiguous gene matches require an explicit choice. Gene/transcript clicks send exact selected identifiers, genome, assembly, release and viewport to the model; continuous motion and pointer hover stay local. **Explain this selection** requests an explanation that first retrieves `get_browser_gene` for the selected gene. This narrow tool provides Core annotation and location, not experimental evidence of function or causality.

New browser-tool results update a view when delivered to it; unrelated annotation results do not replace it. A host can instead create a separate view. Reopening and Reset restore the last tool-declared state for that instance; transient pan, track toggles and clicks are not persisted across reopening.

### Connect and demonstrate

Build and run the HTTP service, then add its reachable HTTPS `/mcp` endpoint as a development app in an authorised ChatGPT developer-mode workspace. Refresh the app's tool definitions after updating the server. Follow the current [ChatGPT integration documentation](https://developers.openai.com/plugins/build/chatgpt-ui) for host setup; this repository does not install a connector or expose localhost automatically.

1. Call `demo_genome_browser` first: human `17:63,992,802-64,038,237` checks the known interval independently of gene lookup.
2. Ask: “Find BRCA2 in genome `59871324-7803-4234-856e-2a2bd96d7b3c` and show it in the genome browser.” Check the returned genome and all gene matches before selecting one. Live MCP lookup returned `ENSG00000139618.19` on 9 November, despite the separately reported website-search failure.
3. Pan, zoom, switch a gene track off/on, then select another gene and choose **Explain this selection**. Check the follow-up tool uses that exact genome and stable ID.
4. Open the Ensembl link, try larger view, reopen the widget, and record whether follow-up browser results update it or open another widget.

The broader “Show human BRCA2” journey depends on a correctly configured discovery endpoint. A broken Search Hub configuration must be fixed in deployment before claiming that journey works. The website's zero-result BRCA2 search is still a separate unresolved diagnostic, not evidence that the gene is absent.

### MCP client connection

For a client supporting Streamable HTTP via `mcpServers`, point it at the running server:

```json
{
  "mcpServers": {
    "ensembl": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Replace `localhost:8000` with the reachable development service address for a remote client. The application's `/mcp` endpoint does not itself create Kubernetes Service or ingress access.

For local stdio, replace the absolute path and endpoint in this configuration:

```json
{
  "mcpServers": {
    "ensembl": {
      "command": "/absolute/path/to/ensembl-mcp/.venv/bin/python",
      "args": ["-m", "ensembl_mcp.server"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "ENSEMBL_CORE_GRAPHQL_URL": "https://your-reachable-core-graphql-endpoint/graphql",
        "ENSEMBL_GENOME_SEARCH_URL": "https://your-reachable-genome-search-endpoint/api/search/genomes/v3",
        "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS": "30"
      }
    }
  }
}
```

The editable install makes the module available without a client-specific working directory. Configure the MCP client's tool-call timeout separately: **90 seconds is a starting point**, as used by the smoke command, not a service guarantee. Timeout settings differ between clients and are not a portable `mcpServers` configuration field.

### Docker

Build the image and run the HTTP server with runtime configuration:

```sh
docker build --pull -t ensembl-mcp:0.1 .
export ENSEMBL_CORE_GRAPHQL_URL='https://your-reachable-core-graphql-endpoint/graphql'
export ENSEMBL_GENOME_SEARCH_URL='https://your-reachable-genome-search-endpoint/api/search/genomes/v3'
docker run --rm -p 8000:8000 \
  -e ENSEMBL_GENOME_SEARCH_URL -e ENSEMBL_CORE_GRAPHQL_URL \
  ensembl-mcp:0.1
```

The image sets `MCP_TRANSPORT=streamable-http` and `MCP_PORT=8000`. Clients connect to `http://localhost:8000/mcp` using the HTTP configuration above. To change the listening port, change both the environment variable and published container port:

```sh
docker run --rm -p 8080:8080 \
  -e MCP_PORT=8080 -e ENSEMBL_GENOME_SEARCH_URL -e ENSEMBL_CORE_GRAPHQL_URL \
  ensembl-mcp:0.1
```

The image uses the [official Python 3.12 Alpine image](https://hub.docker.com/_/python), installs the package without test dependencies and runs as a non-root user. The `.dockerignore` allowlist excludes local environments, secrets, Git history and tests from the build context. The endpoint is supplied at runtime, never baked into the image. `EXPOSE 8000` documents the default port; it does not publish the port or configure Kubernetes networking.

The runtime builds checksum-verified SQLite 3.54.1 in a separate stage and installs it as a local APK, replacing the older library supplied by Alpine 3.24. Review the pinned SQLite version and checksum when updating dependencies; retire this custom package once the supported base supplies a verified fixed version. Compilers remain outside the final image, and runtime package installers and SUID/SGID bits are removed. Rebuild the image to update dependencies.

Run deployments with a read-only root filesystem, dropped Linux capabilities, no privilege escalation and UID 10001. `scripts/check_container.py` checks this security context, SQLite FTS5, MCP tool discovery and the packaged browser resource without network access.

To explicitly use stdio in the container instead:

```sh
docker run --rm -i -e MCP_TRANSPORT=stdio \
  -e ENSEMBL_GENOME_SEARCH_URL -e ENSEMBL_CORE_GRAPHQL_URL ensembl-mcp:0.1
```

For stdio, use `-i` to keep stdin open and omit `-t`. HTTP mode does not need either option. The GraphQL endpoint must be reachable **from inside the container**; `localhost` refers to the container itself, and the cluster-only hostname still requires an appropriate access route.

To explicitly run the existing live MCP smoke command inside the image:

```sh
docker run --rm -e ENSEMBL_GENOME_SEARCH_URL -e ENSEMBL_CORE_GRAPHQL_URL \
  ensembl-mcp:0.1 ensembl-mcp-smoke --live
```

This smoke command always starts its own **stdio** subprocess, overriding the image's HTTP default. It verifies the live lookup but does not test a running HTTP listener. To check the running HTTP server through an MCP client, run this separately from the installed local environment (it makes a real upstream lookup):

```sh
.venv/bin/python - <<'PYTHON'
import asyncio
from fastmcp import Client

async def check():
    async with Client("http://localhost:8000/mcp", timeout=90) as client:
        # Connecting performs MCP initialisation.
        print(await client.list_tools())
        result = await client.call_tool(
            "find_gene", {"symbol": "BRCA2", "species": "Homo sapiens"}
        )
        print(result.structured_content)

asyncio.run(check())
PYTHON
```

## Lookup and result contract

When resolving by species, two sequential HTTP POST requests use JSON bodies, `Content-Type: application/json` and GraphQL variables:

1. `genomes(by_keyword: $by_keyword)` with `GenomeBySpecificKeywordInput`, containing the supplied `scientific_name`.
2. `genes(by_symbol: $by_symbol)` with `SymbolInput`, containing the supplied symbol and dynamically resolved `genome_id`.

Genome selection is explicit: no entries is a species-resolution error; entries with no reference assembly is a no-reference error; more than one reference is an ambiguity error. In the species path, only exactly one `is_reference: true` entry permits the gene request. With `genome_id`, the first request instead uses `genome(by_genome_id: ...)` to retrieve context and verify the UUID, followed by the gene request. A UUID may select a non-reference genome. No release-selection rule or historical UUID fallback is used.

FastMCP publishes input and output schemas. A successful MCP response contains a structured result with:

| Field | Contents |
| --- | --- |
| `symbol`, `species` | Trimmed caller inputs; `species` is null when omitted in the UUID path |
| `genome` | Selected `genome_id`, `scientific_name`, `assembly_accession`, `release_number`, `is_reference` |
| `genes` | Every upstream match, in upstream order, with `stable_id`, `symbol`, `name`, `so_term`, `transcript_count`, `alternative_symbols` |
| `outcome` | `found` when the list is non-empty; `not_found` for an empty list |

Versioned stable IDs are preserved. Nullable biological values, including `symbol` and `name`, remain `null`; missing fields are errors, not fabricated defaults. Genome assembly accession and release number may also be null. `release_number` follows the upstream GraphQL `Float` type: the MCP schema permits a number or null, and values such as `2.0` and `2.5` are preserved without integer truncation. `transcript_count` retains its integer type. Result models validate scalar/list types without coercing strings into numbers or booleans. No internal endpoint is included in successful results.

`genes: []` is a normal `not_found` result with selected genome context. Species-resolution failures and upstream failures are MCP tool errors, not biological no-match results. Safe error categories distinguish `input_validation`, `species_not_found`, `no_reference_genome`, `ambiguous_reference_genome`, `upstream_graphql`, `upstream_http`, `upstream_connection`, `upstream_timeout` and `upstream_response`. Missing or wrongly typed tool arguments are rejected by FastMCP's input validation.

GraphQL errors fail the operation even with HTTP 200 or partial data. HTTP failures (including redirects), connection/DNS failures, timeouts, malformed JSON, missing/null lists and invalid response fields cannot become empty biological results. Caller-facing errors omit raw upstream bodies and stack traces.

## Genome discovery and metadata contracts

`find_genomes` accepts exactly one of `query` or `species_taxonomy_id`. The latter is an exact **species** taxonomy ID, supplied as a positive decimal string; it is not a descendant-clade search or a strain-level `taxonomy_id` filter. Free text supports species/common names and assembly accessions/names according to Search Hub semantics. Search can match multiple species; ranked results do not constitute unique genome resolution.

Inputs also include `reference_only=False`, `page=1`, `per_page=20` (maximum 100), and optional Search Hub `release` label. With no release, upstream includes current genomes and partial releases according to its policy. Search Hub currently returns the genome’s first-release label/type in its `release` field; this is not necessarily the requested/effective release. This label is not a Thoas numeric release version.

Results contain `meta` (`total_hits`, `page`, `per_page`), `matches`, `reference_only`, and `next_page` (null at the end). Each match contains the UUID, names, species and organism taxonomy IDs, assembly, reference status, release, annotation provider/method, and coding-gene count. Optional genome tags and strain/type metadata are preserved when present.

Reference filtering happens across the complete upstream candidate set, preserving upstream order and retaining multiple references. Totals, pagination, and `next_page` then refer to reference matches only. This requires scanning search pages, so broad searches can make many upstream calls. Searches exceeding 1000 candidates fail with `search_too_broad`; narrow them using the exact species selector or a more specific query. Changed totals, duplicate genomes, malformed records, and inconsistent pages fail rather than producing misleading partial results. The index does not provide snapshot isolation: a change that preserves the total and introduces no duplicates may not be detected.

`explain_genome(id_or_accession)` calls `/genome/{id_or_accession}/explain`. It returns the requested identifier, the resolved genome (including suppression details), and a separate `newer_genome` only if upstream reports a different, non-suppressed genome. `newer_genome_status` is `available`, `suppressed`, or `not_reported`. Absence of a reported replacement is not proof that none exists. UUID inputs must be preserved exactly; accession inputs resolve according to the metadata API’s public accession mapping. `/genomeid` is not exposed.

`get_genome_download_links(genome_id)` calls `/genome/{UUID}/explain` followed by `/genome/{UUID}/ftplinks`, always for the original UUID. It returns `links` containing `dataset` and `url`, plus separately reported newer-genome information. A failure of either metadata request fails the tool; it never becomes an empty successful result. An upstream empty links list is preserved.

**Release selection is deliberately not applied to download links**, as the upstream API does not support it. The result includes `release_selection="not_applied"` and an explicit notice; it makes no latest-integrated guarantee. There is no release argument to silently ignore. The tool returns authoritative metadata links and does not browse directories, build paths, download files, or follow newer UUIDs automatically.

All tools publish typed output schemas and read-only annotations. HTTP failures, timeouts, redirects, invalid JSON, and malformed result fields produce sanitised MCP tool errors. New metadata tools require `ENSEMBL_METADATA_API_URL`; existing species/gene queries continue to work without it.

## Tests

Default offline suite (no Kubernetes access or live requests):

```sh
(cd frontend && npm ci && npm run build && npm test && npm run test:browser)
.venv/bin/python -m pytest -q
```

Browser tests use local Chrome (`channel: chrome`) and a loopback MCP Apps test host. Three interaction tests use a mock renderer and six TypeScript tests check bounds, selection context, track commands and credential policy. Real renderer tests are skipped unless explicitly enabled:

```sh
# With reachable Core GraphQL, Search Hub and Tracks settings already exported:
.venv/bin/python scripts/browser_live_fixture.py --live
(cd frontend && MCP_BROWSER_LIVE=1 npm run test:browser -- tests/live.spec.ts)
```

The live fixture command calls this implementation's `find_gene`, both browser tools and `get_browser_gene`. It does not exercise Search Hub. The resulting `.live-fixtures` are local test evidence, not shipped data. Live browser checks contact both priority routes and save screenshots/network summaries in `frontend/test-results`. They test a local sandbox, **not ChatGPT desktop**. Do not treat these as final desktop acceptance.

The suite covers dynamic reference selection, historical and synthetic fixtures, multiple/nullable gene matches, input validation, GraphQL variables, configuration, upstream failure handling, sanitised errors, request logs and lifecycle cleanup. Protocol tests discover and invoke the tool through FastMCP; a subprocess test also checks stdio with a mocked HTTP backend. HTTP tests send MCP initialise, initialised notification, tool discovery and tool invocation requests through the SDK ASGI application at `/mcp`, checking structured successes, no-match results, sanitised failures and lifecycle cleanup. A FastMCP client also exercises the HTTP transport against that ASGI app. The tests check startup transport, host and port selection as well. These HTTP tests run without opening network sockets; they do not verify a deployed listener or Kubernetes routing. Tests block accidental TCP connections in the test process.

The **separate, explicitly enabled live smoke check** starts a local stdio server subprocess, connects through a FastMCP client, discovers `find_gene` and invokes the exact BRCA2 example against the configured real endpoint:

```sh
export ENSEMBL_CORE_GRAPHQL_URL='https://your-reachable-core-graphql-endpoint/graphql'
export ENSEMBL_GENOME_SEARCH_URL='https://your-reachable-genome-search-endpoint/api/search/genomes/v3'
.venv/bin/ensembl-mcp-smoke --live
# Optional longer MCP request timeout:
.venv/bin/ensembl-mcp-smoke --live --client-timeout 120
```

The command requires `--live` even if the endpoint variable exists. It checks the structured result, selected reference genome, non-empty gene list and BRCA2 match, without fixing genome UUIDs, gene versions, transcript counts or aliases. It closes the subprocess after the check and exits nonzero on failure. The default tests never run this live path. Report live results separately from offline tests; absent configuration or connectivity leaves live integration unverified.

## Timing and logging

One historical BRCA2 response reported **11.19 seconds of upstream execution time**. This is not an end-to-end MCP measurement or latency target. The implementation measures client-side elapsed time with a monotonic clock; it does not treat upstream timing extensions as equivalent measurements.

Per [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/), read timeout limits the wait for a chunk of data, write timeout the wait to send a chunk, pool timeout the wait for a connection and connect timeout the establishment of a connection. These are inactivity/phase limits, **not a total request deadline**. Two sequential requests plus protocol overhead can exceed 30 seconds, or even 60 seconds; increasing the configured HTTP timeout may also require increasing the MCP client's timeout.

One asynchronous HTTP client is shared for the server lifespan and closed on shutdown. No automatic retries or lookup caching are implemented. Logs go to stderr, leaving protocol stdout clear. Each upstream request logs its operation name, elapsed seconds, outcome category and HTTP status where available. Tool handlers log overall elapsed duration and outcome. Framework validation rejects missing/wrongly typed arguments before the handler runs. Full request/response bodies and the configured URL are not logged by default; HTTPX's URL-bearing INFO logs are suppressed by the server entry point.

FastMCP's [typed structured output and tool errors](https://gofastmcp.com/servers/tools) and [lifespan support](https://gofastmcp.com/servers/lifespan) provide the MCP boundary and resource lifecycle.

## Project structure

```text
pyproject.toml                 Dependencies and console commands
Dockerfile                    Non-root Python 3.12 image; HTTP by default
.dockerignore                 Minimal package-only build context
src/ensembl_mcp/
  config.py                   Startup configuration and HTTP timeout policy
  models.py                   Typed inputs, genome metadata and results
  graphql.py                  Async HTTP/GraphQL handling and safe errors
  lookup.py                   Queries, reference selection and lookup service
discovery.py                Search Hub and metadata contracts, REST handling and services
  server.py                   FastMCP registration, lifecycle and transport entry point
  smoke.py                    Explicit live MCP smoke command
tests/                        Offline unit and protocol tests
```

## Aims and evaluation

- Provide useful tools for accessing Ensembl data, starting with `find_gene`.
- Test the proposed EMBL-EBI conventions against a working implementation.
- Evaluate correctness, completeness and performance using representative tasks with trusted expected results.
- Develop a reusable reference implementation maintained by Ensembl.

The pilot assesses three aspects separately: **protocol behaviour**, **service performance** and **agent task success**. Each evaluation task should have expected results and acceptance criteria defined before execution. Offline protocol checks do not establish live service performance or biological validity of an agent's conclusions.

## Current limitations

Gene retrieval remains symbol-based. Genome discovery supports broader names and assemblies, and callers can pass a selected UUID into `find_gene`. There is no separate stable-ID gene lookup or gene-alias search. FTP release selection is unsupported upstream; no latest-integrated guarantee is made. Returning upstream `alternative_symbols` does not establish alias-search behaviour. Upstream schema compatibility and current biological data require live verification.

Transcripts, proteins, sequences, variants, coordinates, external references and literature retrieval are outside v0.1. So are Kubernetes resources, deployment, public hosting, caching, retries and a broad observability stack. The reported development deployment is in `mcp-poc-public`; image rollout and verification of this HTTP update are separate from the application changes here.

## Licence

[Apache License 2.0](LICENSE).
