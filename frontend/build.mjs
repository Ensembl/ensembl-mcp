import { build } from "esbuild";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";

// Package WASM inside the resource: no same-origin asset paths, CDN, blob-script
// allowance or additional ingress route is needed in a sandboxed MCP App.
const wasm = await readFile(new URL("node_modules/@ensembl/ensembl-genome-browser/dist/peregrine_ensembl_bg.wasm", import.meta.url));
const result = await build({
  entryPoints: ["src/main.ts"], bundle: true, write: false, format: "iife",
  target: "es2022", minify: true, legalComments: "inline",
  define: { __WASM_GZIP_BASE64__: JSON.stringify(gzipSync(wasm, { level: 9 }).toString("base64")) },
});
const template = await readFile("index.html", "utf8");
const script = result.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");
const html = template.replace("<!-- APP_SCRIPT -->", () => `<script>${script}</script>`);
const destination = new URL("../src/ensembl_mcp/ui/", import.meta.url);
await mkdir(destination, { recursive: true });
await writeFile(new URL("genome-browser.html", destination), html);
console.log(`Built self-contained MCP resource (${(Buffer.byteLength(html) / 1024 / 1024).toFixed(2)} MiB); renderer 0.6.14`);
