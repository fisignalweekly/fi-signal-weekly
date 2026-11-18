// End-to-end check against a running server (wrangler dev or deployed) with the official MCP client.
//   MCP_URL=http://127.0.0.1:8787/mcp MCP_KEY_FILE=/path/key.txt node test/e2e.mjs
// Prints only pass/fail lines and summaries, never the key.
import { readFileSync } from "node:fs";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const url = process.env.MCP_URL ?? "http://127.0.0.1:8787/mcp";
const key = readFileSync(process.env.MCP_KEY_FILE, "utf8").trim();
const FI_ONLY_IDS = (process.env.FI_ONLY_IDS ?? "").split(",").filter(Boolean);
let failed = 0;
const check = (name, cond, info = "") => { console.log(`${cond ? "PASS" : "FAIL"} ${name}${info ? " — " + info : ""}`); if (!cond) failed++; };

const post = (headers) => fetch(url, { method: "POST", headers: { "content-type": "application/json", accept: "application/json, text/event-stream", ...headers },
  body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }) });
check("no key -> 401", (await post({})).status === 401);
check("bad key -> 401", (await post({ authorization: "Bearer fisw_00000000_" + "x".repeat(43) })).status === 401);
check("garbage auth -> 401", (await post({ authorization: "Basic abc" })).status === 401);

const client = new Client({ name: "fisw-e2e", version: "1.0.0" });
await client.connect(new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers: { authorization: `Bearer ${key}` } } }));
const tools = (await client.listTools()).tools.map((t) => t.name).sort();
check("tools/list", JSON.stringify(tools) === JSON.stringify(["get_fi_profile", "get_tech_stack", "list_new_signals_since", "search_signals"]), tools.join(","));
const call = async (name, args) => {
  const r = await client.callTool({ name, arguments: args });
  return { err: !!r.isError, data: JSON.parse(r.content[0].text) };
};
const seen = new Set();
const all = []; let cursor;
do { const { data } = await call("search_signals", { limit: 100, cursor }); data.signals.forEach((s) => all.push(s)); cursor = data.next_cursor; } while (cursor);
all.forEach((s) => seen.add(s.id));
check("search_signals pages through everything", all.length > 0 && seen.size === all.length, `${all.length} signals`);
check("no branch_opening / fi_only rows", all.every((s) => s.type !== "branch_opening" && !("fi_only" in s)) && FI_ONLY_IDS.every((id) => !seen.has(id)), `checked ids ${FI_ONLY_IDS.join(",")}`);
check("no internal fields", all.every((s) => !("assets_note" in s) && !("assets_source" in s) && !("fi_match" in s)));
const ma = await call("search_signals", { types: ["m_and_a"], states: ["PA", "OH", "MI"], min_assets_usd: 5e8, limit: 5 });
check("search_signals m_and_a filter", !ma.err && ma.data.signals.every((s) => s.type_group === "m_and_a" && ["PA", "OH", "MI"].includes(s.state) && s.assets_usd >= 5e8),
  `${ma.data.total} hits; first: ${ma.data.signals[0]?.id} (${ma.data.signals[0]?.type_label}, ${ma.data.signals[0]?.event_date})`);
const ex = await call("search_signals", { types: ["executive"], query: "chief", event_date_from: "2026-10-01", limit: 3 });
check("search_signals executive + text + date", !ex.err && ex.data.signals.every((s) => s.type_group === "executive" && s.event_date >= "2026-10-01"), `${ex.data.total} hits`);
const bad = await call("search_signals", { types: ["branch_opening"] });
check("branch_opening type rejected", bad.err, bad.data.error?.slice(0, 60));

const p = await call("get_fi_profile", { fi_id: "fdic-14969" });
check("get_fi_profile by fi_id", !p.err && p.data.fi_id === "fdic-14969" && /^https:\/\/fisignalweekly\.com\/fi\/pa\/[a-z0-9-]+\/$/.test(p.data.page_url) && p.data.financials?.asset_trend?.length === 9,
  `${p.data.page_url}, assets ${p.data.financials?.total_assets_usd}, 1y growth ${p.data.financials?.asset_growth_1y}, ${p.data.signals?.length} signals`);
const ps = await call("get_fi_profile", { slug: p.data.page_url });
check("get_fi_profile by page URL", !ps.err && ps.data.fi_id === "fdic-14969");
const pn = await call("get_fi_profile", { name: p.data.name, state: p.data.state });
check("get_fi_profile by name + state", !pn.err && pn.data.fi_id === "fdic-14969");

const n1 = await call("list_new_signals_since", { since: "2026-11-01", limit: 20 });
let rows = [...n1.data.signals], cur = n1.data.next_cursor, more = n1.data.has_more;
while (more) { const n = await call("list_new_signals_since", { since: "2026-11-01", limit: 20, cursor: cur }); rows.push(...n.data.signals); cur = n.data.next_cursor; more = n.data.has_more; }
const sortedOk = rows.every((s, i) => i === 0 || rows[i - 1].added < s.added || (rows[i - 1].added === s.added && rows[i - 1].id < s.id));
check("list_new_signals_since: stable order, no backfill, added >= since", sortedOk && rows.every((s) => !s.backfill && s.added >= "2026-11-01") && new Set(rows.map((r) => r.id)).size === rows.length, `${rows.length} rows`);
const tail = await call("list_new_signals_since", { since: "2026-11-01", cursor: cur });
check("list_new_signals_since: resume cursor at end returns 0", tail.data.count === 0);
const nb = await call("list_new_signals_since", { since: "2026-01-01", include_backfill: true, limit: 200 });
check("include_backfill returns backfill rows", nb.data.signals.some((s) => s.backfill));

const ts = await call("get_tech_stack", { fi_ids: ["fdic-30788", "fdic-58979", "ncua-62918", "fdic-999999999"] });
const f0 = ts.data.institutions[0].fields;
check("get_tech_stack batch", !ts.err && ts.data.institutions.length === 4 && ts.data.institutions[3].error,
  Object.entries(f0).map(([k, v]) => `${k}=${v.value ? "identified" : "none"}${v.evidence_type ? " [" + v.evidence_type + "]" : ""}`).join("; "));
check("every tech value has evidence type + source", ts.data.institutions.slice(0, 3).every((i) => Object.values(i.fields).every((v) => !v.value || (v.evidence_type && v.source_url))));
await client.close();
console.log(failed ? `${failed} FAILED` : "ALL PASSED");
process.exit(failed ? 1 : 0);
