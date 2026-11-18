import { describe, expect, it } from "vitest";
import bundle from "../src/generated/bundle.json";
import { Store, ToolError, type Bundle } from "../src/data";
import { sha256Hex, verifyKey } from "../src/auth";

const store = new Store(bundle as unknown as Bundle);

describe("search_signals", () => {
  it("never returns FI-only rows and pages through all signals", () => {
    const seen: string[] = [];
    let cursor: string | undefined;
    do {
      const r = store.searchSignals({ limit: 50, cursor });
      seen.push(...r.signals.map((s) => s.id));
      cursor = r.next_cursor ?? undefined;
    } while (cursor);
    expect(new Set(seen).size).toBe(bundle.signals.length);
    expect(bundle.signals.some((s) => s.type === "branch_opening")).toBe(false);
  });
  it("filters by group, state and assets", () => {
    const r = store.searchSignals({ types: ["m_and_a"], states: ["pa"], min_assets_usd: 1e8 });
    for (const s of r.signals) { expect(s.type_group).toBe("m_and_a"); expect(s.state).toBe("PA"); expect(s.assets_usd!).toBeGreaterThanOrEqual(1e8); }
  });
  it("rejects FI-only and unknown types", () => {
    expect(() => store.searchSignals({ types: ["branch_opening"] })).toThrow(ToolError);
  });
});

describe("list_new_signals_since", () => {
  it("is ordered by (added, id), excludes backfill by default, and resumes by cursor", () => {
    const a = store.listNewSince({ since: "2026-01-01", limit: 10 });
    const b = store.listNewSince({ since: "2026-01-01", limit: 10, cursor: a.next_cursor! });
    const all = store.listNewSince({ since: "2026-01-01", limit: 200 });
    expect([...a.signals, ...b.signals].map((s) => s.id)).toEqual(all.signals.slice(0, 20).map((s) => s.id));
    expect(all.signals.every((s) => !s.backfill)).toBe(true);
    expect(store.listNewSince({ since: "2026-01-01", limit: 200, include_backfill: true }).signals.some((s) => s.backfill)).toBe(true);
  });
});

describe("profiles and tech stack", () => {
  it("resolves by fi_id, slug and URL to the same page", () => {
    const a = store.resolve({ fi_id: "fdic-30788" }).fi!;
    const short = a.page_url.replace("https://fisignalweekly.com/fi/", "").replace(/\/$/, "");
    expect(short).toMatch(/^mt\/[a-z0-9-]+$/);
    expect(store.resolve({ slug: short }).fi!.fi_id).toBe(a.fi_id);
    expect(store.resolve({ slug: a.page_url }).fi!.fi_id).toBe(a.fi_id);
    expect(store.resolve({ name: a.name, state: a.state }).fi!.fi_id).toBe(a.fi_id);
  });
  it("returns evidence with every value and never fills core from digital", () => {
    const [g] = store.techStackBatch(["fdic-30788"]) as { fields: Record<string, { value: string | null; evidence_type: string | null; source_url: string | null }> }[];
    expect(g.fields.digital.value).toBeTruthy();
    expect(g.fields.digital.evidence_type).toBeTruthy();
    expect(g.fields.digital.source_url).toBeTruthy();
    const coreRows = (bundle as unknown as Bundle).providers["fdic-30788"]?.core ?? [];
    if (!coreRows.length) expect(g.fields.core.value).toBeNull();
  });
});

describe("api keys", () => {
  const kv = (rec: unknown) => ({ get: async () => rec }) as unknown as KVNamespace;
  const key = "fisw_0123abcd_" + "A".repeat(43);
  it("accepts a matching hash and rejects revoked, wrong or malformed keys", async () => {
    const hash = await sha256Hex(key);
    expect(await verifyKey(key, kv({ hash, label: "t", created_at: "x" }))).toMatchObject({ keyId: "0123abcd" });
    expect(await verifyKey(key, kv({ hash, label: "t", created_at: "x", revoked_at: "y" }))).toBeNull();
    expect(await verifyKey(key, kv({ hash: "0".repeat(64), label: "t", created_at: "x" }))).toBeNull();
    expect(await verifyKey("nope", kv(null))).toBeNull();
    expect(await verifyKey(null, kv(null))).toBeNull();
  });
});
