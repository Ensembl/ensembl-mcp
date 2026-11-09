// Local test host only. No biological endpoint proxy; live renderer traffic is
// cross-origin from the iframe just as it will be from an MCP App sandbox.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { build } from "esbuild";
const template = await readFile("index.html", "utf8");
const mock = await build({ entryPoints: ["src/main.ts"], bundle: true, write: false, format: "iife", plugins: [{
  name: "mock-renderer", setup(builder) { builder.onResolve({ filter: /^\.\/renderer$/ }, () => ({ path: new URL("mock-renderer.ts", import.meta.url).pathname })); }
}] });
const mockHtml = template.replace("<!-- APP_SCRIPT -->", () => `<script>${mock.outputFiles[0].text}</script>`);
const fixture = {
  structuredContent: {
    schema_version: 1, genome: { genome_id: "59871324-7803-4234-856e-2a2bd96d7b3c", scientific_name: "Homo sapiens", assembly_accession: "GCA_000001405.29", release_number: 2, is_reference: true },
    gene_id: "ENSG00000139618.19", location: { region: "13", start: 32315086, end: 32400268, region_length: 114364328 }, coordinate_system: "1-based inclusive",
    initial_tracks: [{ track_id: "genes", type: "gene", label: "Protein coding genes", additional_info: "Forward strand", trigger: ["track", "gene-pc-fwd"], display_order: -110, on_by_default: true }, { track_id: "sequence", type: "regular", label: "Reference sequence", additional_info: "", trigger: ["track", "contig"], display_order: 0, on_by_default: true }],
    browser_backend_url: "https://mcp-poc-public.review.ensembl.org/api/browser/data", ensembl_url: "https://mcp-poc-public.review.ensembl.org/genome-browser/59871324-7803-4234-856e-2a2bd96d7b3c?location=13:32315086-32400268&focus=gene:ENSG00000139618.19",
  }, content: [{ type: "text", text: "Offline browser fixture" }],
};
fixture._meta = { "ensembl/trackCatalogue": { track_categories: [{ track_list: fixture.structuredContent.initial_tracks }] } };
const host = `<!doctype html><html><body style="margin:0"><iframe id="app" sandbox="allow-scripts allow-same-origin" style="width:100%;height:950px;border:0"></iframe><script>
  window.calls=[];window.result=${JSON.stringify(fixture)};
  const frame=document.getElementById('app');
  window.sendResult = (result) => frame.contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result},'*');
  window.addEventListener('message',async event=>{
    if(event.source!==frame.contentWindow)return;
    const m=event.data;if(m.jsonrpc!=='2.0')return;
    window.calls.push(m);
    let result={};
    if(m.method==='ui/initialize') result={protocolVersion:m.params.protocolVersion,hostInfo:{name:'Local test host',version:'1'},hostCapabilities:{serverTools:{},openLinks:{},message:{text:{}},updateModelContext:{text:{}}},hostContext:{displayMode:'inline',availableDisplayModes:['inline','fullscreen']}};
    if(m.method==='ui/notifications/initialized') {sendResult(window.result);return;}
    if(m.method==='tools/call') {
      if(m.params.name==='find_gene') result={structuredContent:{genome:window.result.structuredContent.genome,genes: m.params.arguments.symbol==='ABSENT'?[]:[{stable_id:'ENSG1.1',symbol:'DUP'},{stable_id:'ENSG2.1',symbol:'DUP'}]},content:[]};
      else result=window.result;
    }
    if(m.method==='ui/request-display-mode') { result={mode:m.params.mode};frame.contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:{displayMode:m.params.mode}},'*'); }
    if(m.id!==undefined)frame.contentWindow.postMessage({jsonrpc:'2.0',id:m.id,result},'*');
  });
  const live=new URLSearchParams(location.search).get('live');
  if(live) fetch('/live-result?locus='+live).then(r=>r.json()).then(r=>{window.result=r;frame.src='/real';});
  else frame.src='/mock';
</script></body></html>`;
createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    let content = host, type = "text/html";
    if (url.pathname === "/mock") content = mockHtml;
    if (url.pathname === "/real") content = await readFile("../src/ensembl_mcp/ui/genome-browser.html", "utf8");
    if (url.pathname === "/live-result") { content = await readFile(`.live-fixtures/live-${url.searchParams.get("locus") === "demo" ? "demo" : "brca2"}.json`, "utf8"); type = "application/json"; }
    response.writeHead(200, { "Content-Type": type }); response.end(content);
  } catch { response.writeHead(404); response.end("Fixture unavailable"); }
}).listen(4175, "127.0.0.1", () => console.log("Test host on http://127.0.0.1:4175"));
