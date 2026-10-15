# Ensembl MCP

An Ensembl server for the **Model Context Protocol (MCP)**, which allows AI applications to discover and use tools for accessing Ensembl data.

This pilot supports the development and evaluation of the [EMBL-EBI MCP guidelines](https://github.com/EMBL-EBI-ABC/ebi-mcp-guidelines).

## Status and purpose

The pilot exposes four read-only tools using Python and the `fastmcp` package:

```text
find_genomes(query="human", reference_only=True)
find_gene(symbol="BRCA2", species="Homo sapiens")
find_gene(symbol="BRCA2", genome_id="<UUID returned by find_genomes>")
explain_genome(id_or_accession="GCA_000001405.29")
get_genome_download_links(genome_id="<selected genome UUID>")
```

For `find_gene`, `symbol` is required, along with either `species` or `genome_id`. Surrounding whitespace is removed and blank values are rejected before any upstream request. Symbol case is preserved. `species` must be a scientific name. A supplied genome UUID skips species resolution and permits non-reference genomes. If both selectors are supplied, the scientific name must match the UUID’s genome (case-insensitively).

Without a UUID, `find_gene` resolves the species reference genome through Ensembl Core GraphQL. With a UUID, it fetches that genome’s context directly and uses exactly that UUID for the gene query. Both paths return all symbol matches. No tool automatically substitutes a newer genome UUID.

This is early development, not a production service. Offline unit and MCP protocol tests use mocked upstream responses. Prior manual requests established the query examples and cluster connectivity; they did **not** demonstrate this MCP implementation against the real service. Live verification requires the separate smoke command below and a reachable endpoint. The initial image has been deployed to the development cluster in `mcp-poc-public`, as reported by the deployment team. The application now supports Streamable HTTP for that environment; this transport update still needs image build and cluster verification. Kubernetes manifests are not changed here.

## Install and run locally

The supported runtime for v0.1 is **Python 3.12** with **FastMCP 4.0.11**, pinned in `pyproject.toml`. HTTP calls use HTTPX 0.28.1. From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
export ENSEMBL_CORE_GRAPHQL_URL='https://your-reachable-core-graphql-endpoint/graphql'
export ENSEMBL_GENOME_SEARCH_URL='https://your-reachable-genome-search-endpoint/api/search/genomes/v3'
MCP_TRANSPORT=stdio .venv/bin/ensembl-mcp
```

Replace the example URL with your actual Core GraphQL endpoint. Local execution defaults to **stdio** and waits for MCP messages; an MCP client normally starts the process itself. The equivalent module entry point is `.venv/bin/python -m ensembl_mcp.server`. Configuration is read from the process environment; `.env` files are not automatically loaded.

To run the HTTP server locally with the same transport as the container:

```sh
MCP_TRANSPORT=streamable-http MCP_PORT=8000 .venv/bin/ensembl-mcp
```

This listens on **`0.0.0.0:8000`** and exposes **`/mcp`**. Connect locally using `http://localhost:8000/mcp`. The existing FastMCP package and its MCP Python SDK implement [Streamable HTTP](https://gofastmcp.com/deployment/running-server#http-transport-streamable); this is not the legacy SSE transport. HTTP requests are stateless, so they do not require a pod-specific MCP session. The server supports `initialize`, `notifications/initialized`, `tools/list` and `tools/call` through this endpoint, including SDK-managed response streaming.

### Configuration

| Variable | Requirement and default |
| --- | --- |
| `MCP_TRANSPORT` | `stdio` or `streamable-http` only. Defaults to `stdio` when unset locally; the Docker image sets `streamable-http`. Surrounding whitespace is trimmed. |
| `MCP_PORT` | Integer from `1` to `65535`, default `8000`. Validated at startup; used only for HTTP. The HTTP bind address is fixed at `0.0.0.0` and the endpoint path at `/mcp`. |
| `ENSEMBL_GENOME_SEARCH_URL` | Required full Search Hub search URL. No default or fallback. Missing, blank, or invalid values stop startup. |
| `ENSEMBL_METADATA_API_URL` | Metadata API base URL, including its API prefix (for example `https://your-host/api/metadata`). No default; metadata tools report a configuration error when omitted. |
| `ENSEMBL_CORE_GRAPHQL_URL` | Required absolute `http://` or `https://` URL with a host. Surrounding whitespace is trimmed. Credentials in the URL, fragments, internal whitespace and invalid ports are rejected. There is no runtime default or fallback. |
| `ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS` | Optional finite positive number, default `30`. Used for HTTPX read, write and connection-pool timeouts. Connection timeout is separately fixed at `5` seconds. |

Invalid configured URLs or missing required Core or Search Hub configuration stop startup with an error on stderr and exit status 2. Search and metadata URL overrides must not contain credentials, query strings, fragments, or whitespace. All upstream clients share the configured HTTP timeout. Configure all three services against compatible environments/releases; a public Search Hub endpoint may not match development Thoas data. Keep credentials and deployment secrets outside the repository.

The historically tested **cluster-only** configuration is:

```sh
export ENSEMBL_CORE_GRAPHQL_URL='http://graphql-core-svc.ensembl-dev:8000'
export ENSEMBL_GENOME_SEARCH_URL='http://metadata-api-svc.ensembl-dev:8014'
```

That ClusterIP service is in `ensembl-dev`; connectivity from a pod in `mcp-poc-public` was previously reported as successful. This hostname is not a public endpoint. Running locally requires a reachable endpoint or an existing approved access route. The server is not deployed by these instructions.

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
docker build -t ensembl-mcp:0.1 .
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

The image uses the [official Python 3.12 slim image](https://hub.docker.com/_/python), installs the package without test dependencies and runs as a non-root user. The `.dockerignore` allowlist excludes local environments, secrets, Git history and tests from the build context. The endpoint is supplied at runtime, never baked into the image. `EXPOSE 8000` documents the default port; it does not publish the port or configure Kubernetes networking.

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

Reference filtering happens across the complete upstream candidate set, preserving upstream order and retaining multiple references. Totals, pagination, and `next_page` then refer to reference matches only. This requires scanning search pages, so broad searches can make many upstream calls. Searches exceeding 10000 candidates fail with `search_too_broad`; narrow them using the exact species selector or a more specific query. Changed totals, duplicate genomes, malformed records, and inconsistent pages fail rather than producing misleading partial results. The index does not provide snapshot isolation: a change that preserves the total and introduces no duplicates may not be detected.

`explain_genome(id_or_accession)` calls `/genome/{id_or_accession}/explain`. It returns the requested identifier, the resolved genome (including suppression details), and a separate `newer_genome` only if upstream reports a different, non-suppressed genome. `newer_genome_status` is `available`, `suppressed`, or `not_reported`. Absence of a reported replacement is not proof that none exists. UUID inputs must be preserved exactly; accession inputs resolve according to the metadata API’s public accession mapping. `/genomeid` is not exposed.

`get_genome_download_links(genome_id)` calls `/genome/{UUID}/explain` followed by `/genome/{UUID}/ftplinks`, always for the original UUID. It returns `links` containing `dataset` and `url`, plus separately reported newer-genome information. A failure of either metadata request fails the tool; it never becomes an empty successful result. An upstream empty links list is preserved.

**Release selection is deliberately not applied to download links**, as the upstream API does not support it. The result includes `release_selection="not_applied"` and an explicit notice; it makes no latest-integrated guarantee. There is no release argument to silently ignore. The tool returns authoritative metadata links and does not browse directories, build paths, download files, or follow newer UUIDs automatically.

All tools publish typed output schemas and read-only annotations. HTTP failures, timeouts, redirects, invalid JSON, and malformed result fields produce sanitised MCP tool errors. New metadata tools require `ENSEMBL_METADATA_API_URL`; existing species/gene queries continue to work without it.

## Tests

Default offline suite (no Kubernetes access or live requests):

```sh
.venv/bin/python -m pytest -q
```

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
