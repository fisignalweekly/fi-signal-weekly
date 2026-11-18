import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { Store, ToolError } from "./data";

const DATE = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD");
const RO = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

function ok(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data) }] };
}
function fail(e: unknown) {
  const msg = e instanceof ToolError ? e.message : "internal error";
  return { content: [{ type: "text" as const, text: JSON.stringify({ error: msg }) }], isError: true };
}
const wrap = <A,>(fn: (a: A) => unknown) => async (a: A) => { try { return ok(fn(a)); } catch (e) { return fail(e); } };

export function createServer(store: Store) {
  const types = store.b.types.map((t) => `${t.type} (${t.label})`).join(", ");
  const server = new McpServer(
    { name: "fi-signal-weekly", version: "1.0.0" },
    { instructions: "Read-only access to FI Signal Weekly's published signals and institution data for US banks and credit unions. " +
        "Signal types in priority order: " + types + ". Groups: m_and_a, executive. Every signal links its public source; verify before acting." },
  );

  server.registerTool("search_signals", {
    title: "Search signals",
    description: "Search published FI Signal Weekly signals (M&A and executive moves first, then core, charter and digital banking changes). " +
      "Filter by type or group (m_and_a, executive), state, institution asset size, event date, publish date (added) and free text. " +
      "Newest event first. Paginate with next_cursor. Types: " + types + ".",
    inputSchema: z.object({
      query: z.string().max(200).optional().describe("Words that must all appear in the institution name, summary or type label"),
      types: z.array(z.string()).max(20).optional().describe("Signal types or groups, e.g. [\"m_and_a\", \"executive\"] or [\"merger\"]"),
      states: z.array(z.string().length(2)).max(60).optional().describe("Two-letter state codes, e.g. [\"PA\", \"OH\"]"),
      min_assets_usd: z.number().nonnegative().optional().describe("Minimum institution total assets in USD"),
      max_assets_usd: z.number().nonnegative().optional().describe("Maximum institution total assets in USD"),
      event_date_from: DATE.optional(), event_date_to: DATE.optional(),
      added_from: DATE.optional().describe("Published on the board on or after"), added_to: DATE.optional(),
      fi_id: z.string().optional().describe("Only signals for this institution (fdic-<CERT> or ncua-<charter>)"),
      include_backfill: z.boolean().optional().describe("Include historical backfill rows (default true)"),
      sort: z.enum(["event_date_desc", "added_desc"]).optional(),
      limit: z.number().int().min(1).max(100).optional().describe("Page size, default 25"),
      cursor: z.string().max(200).optional().describe("next_cursor from the previous page"),
    }),
    annotations: { title: "Search signals", ...RO },
  }, wrap((a) => store.searchSignals(a)));

  server.registerTool("get_fi_profile", {
    title: "Get institution profile",
    description: "Profile of one bank or credit union: directory data, fisignalweekly.com page URL, call-report assets with a two-year trend, " +
      "growth versus industry medians, regulator history (mergers, name changes), tech stack with evidence, and its published signals. " +
      "Look up by fi_id (fdic-30788, ncua-62918), page slug (pa/kish-bank or the page URL) or name (+ optional state). " +
      "An ambiguous name returns candidates instead.",
    inputSchema: z.object({
      fi_id: z.string().optional(), slug: z.string().max(300).optional(),
      name: z.string().max(200).optional(), state: z.string().length(2).optional(),
    }),
    annotations: { title: "Get institution profile", ...RO },
  }, wrap((a) => {
    const r = store.resolve(a);
    if (r.candidates) return { ambiguous: true, candidates: r.candidates.map((c) => ({ fi_id: c.fi_id, name: c.name, city: c.city, state: c.state, total_assets_usd: c.total_assets_usd, page_url: c.page_url })) };
    return store.profile(r.fi!);
  }));

  server.registerTool("list_new_signals_since", {
    title: "List new signals since a date",
    description: "Signals published on the board (by their added date) on or after `since`, oldest first in a stable (added, id) order, " +
      "for incremental sync into another system. Pass next_cursor back to continue; store the last next_cursor to resume later. " +
      "Backfilled historical rows are left out unless include_backfill is true. Dedupe on id.",
    inputSchema: z.object({
      since: DATE.describe("Publish date (YYYY-MM-DD), inclusive"),
      types: z.array(z.string()).max(20).optional(),
      include_backfill: z.boolean().optional().describe("Default false"),
      limit: z.number().int().min(1).max(200).optional().describe("Page size, default 100"),
      cursor: z.string().max(200).optional(),
    }),
    annotations: { title: "List new signals since a date", ...RO },
  }, wrap((a) => store.listNewSince(a)));

  server.registerTool("get_tech_stack", {
    title: "Get tech stack",
    description: "Technology providers for up to 100 institutions: digital banking (retail), digital banking (business), core and bill pay. " +
      "Every value carries its evidence type (Login page scan, Vendor press release, FI announcement, Press release, Regulator filing), " +
      "source URL and date. Fields with no evidence say so; core is never inferred from the digital banking vendor.",
    inputSchema: z.object({ fi_ids: z.array(z.string()).min(1).max(100).describe("fi_ids, e.g. [\"fdic-14969\", \"ncua-62918\"]") }),
    annotations: { title: "Get tech stack", ...RO },
  }, wrap((a) => ({ institutions: store.techStackBatch(a.fi_ids) })));

  return server;
}
