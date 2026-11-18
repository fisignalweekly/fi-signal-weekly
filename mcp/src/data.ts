// Read-only queries over the sanitized bundle built by scripts/build_bundle.py.
// The bundle already contains only published, allowlisted data; nothing here adds fields.

export type Signal = {
  id: string; type: string; type_label: string; type_group: string;
  institution: string; state: string; event_date: string; added: string; backfill: boolean;
  summary: string; source_url: string; fi_id: string | null; fi_name: string | null;
  charter_type: string | null; assets_usd: number | null; assets_basis: string | null;
  assets_as_of: string | null; fi_page_url: string | null; board_url: string;
};
export type Evidence = {
  value: string; status: string; source_type: string; source_url: string | null;
  last_updated: string | null; note: string | null;
};
export type Bundle = {
  meta: { site: string; data_updated: string; assets_as_of: string; trend_quarters: string[]; built_at: string; source_commit?: string; sources: string };
  types: { type: string; label: string; group: string; priority: number }[];
  signals: Signal[];
  institutions: { cols: string[]; rows: unknown[][] };
  financials: Record<string, {
    assets_usd: (number | null)[]; deposits_usd: number | null; loans_usd: number | null; established: string | null;
    members?: number; offices?: number; sites?: Record<string, number>; history?: Record<string, string>[];
  }>;
  benchmarks: Record<string, { filers: number; median_growth_1y: number | null; median_growth_5y: number | null; industry_growth_1y: number | null; industry_growth_5y: number | null }>;
  providers: Record<string, Record<string, Evidence[]>>;
  renewal_windows: Record<string, Record<string, { text: string; source_url: string | null }>>;
};
export type Institution = {
  fi_id: string; name: string; charter_type: string; charter_class: string | null; city: string | null;
  state: string; website: string | null; total_assets_usd: number | null; assets_as_of: string | null;
  holding_company: string | null; also_known_as: string | null; page_url: string;
};

export const PROVIDER_FIELDS = ["digital", "digital_business", "core", "billpay"] as const;
const FIELD_LABEL: Record<string, string> = {
  digital: "Digital banking (retail)", digital_business: "Digital banking (business)",
  core: "Core provider", billpay: "Bill pay provider",
};
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export class ToolError extends Error {}

const b64 = (s: string) => btoa(s).replace(/=+$/, "");
const unb64 = (s: string) => { try { return atob(s); } catch { throw new ToolError("invalid cursor"); } };

export class Store {
  readonly typeSet: Set<string>;
  readonly groups: Record<string, string[]>;
  private inst = new Map<string, Institution>();
  private byPath = new Map<string, string>();
  private byFi = new Map<string, Signal[]>();
  private sortedByAdded: Signal[];

  constructor(readonly b: Bundle) {
    this.typeSet = new Set(b.types.map((t) => t.type));
    this.groups = {};
    for (const t of b.types) (this.groups[t.group] ??= []).push(t.type);
    const c = b.institutions.cols;
    for (const r of b.institutions.rows) {
      const o = Object.fromEntries(c.map((k, i) => [k, r[i]])) as Record<string, unknown>;
      const path = o.path as string;
      delete o.path;
      const x = { ...(o as Omit<Institution, "page_url">), page_url: b.meta.site + path } as Institution;
      this.inst.set(x.fi_id, x);
      this.byPath.set(path.replace(/^\/fi\/|\/$/g, ""), x.fi_id);
    }
    for (const s of b.signals) if (s.fi_id) (this.byFi.get(s.fi_id) ?? this.byFi.set(s.fi_id, []).get(s.fi_id)!).push(s);
    this.sortedByAdded = [...b.signals].sort((a, z) => cmp(a.added, z.added) || cmp(a.id, z.id));
  }

  /** Expand type names and group names (m_and_a, executive) into board types; reject unknown ones. */
  expandTypes(types?: string[]): Set<string> | null {
    if (!types || !types.length) return null;
    const out = new Set<string>();
    for (const t of types) {
      if (this.groups[t]) this.groups[t].forEach((x) => out.add(x));
      else if (this.typeSet.has(t)) out.add(t);
      else throw new ToolError(`unknown type "${t}". Valid: ${[...Object.keys(this.groups), ...this.typeSet].join(", ")}`);
    }
    return out;
  }

  searchSignals(q: {
    query?: string; types?: string[]; states?: string[]; min_assets_usd?: number; max_assets_usd?: number;
    event_date_from?: string; event_date_to?: string; added_from?: string; added_to?: string; fi_id?: string;
    include_backfill?: boolean; sort?: "event_date_desc" | "added_desc"; limit?: number; cursor?: string;
  }) {
    for (const k of ["event_date_from", "event_date_to", "added_from", "added_to"] as const)
      if (q[k] && !DATE.test(q[k]!)) throw new ToolError(`${k} must be YYYY-MM-DD`);
    const types = this.expandTypes(q.types);
    const states = q.states?.length ? new Set(q.states.map((s) => s.toUpperCase())) : null;
    const words = (q.query ?? "").toLowerCase().split(/\s+/).filter(Boolean);
    const limit = clamp(q.limit ?? 25, 1, 100);
    const offset = q.cursor ? parseInt(unb64(q.cursor).replace(/^o:/, ""), 10) : 0;
    if (!Number.isFinite(offset) || offset < 0) throw new ToolError("invalid cursor");
    let rows = this.b.signals.filter((s) =>
      (!types || types.has(s.type)) &&
      (!states || states.has(s.state.toUpperCase())) &&
      (q.include_backfill !== false || !s.backfill) &&
      (!q.fi_id || s.fi_id === q.fi_id) &&
      (q.min_assets_usd == null || (s.assets_usd != null && s.assets_usd >= q.min_assets_usd)) &&
      (q.max_assets_usd == null || (s.assets_usd != null && s.assets_usd <= q.max_assets_usd)) &&
      (!q.event_date_from || s.event_date >= q.event_date_from) &&
      (!q.event_date_to || s.event_date <= q.event_date_to) &&
      (!q.added_from || s.added >= q.added_from) &&
      (!q.added_to || s.added <= q.added_to) &&
      (!words.length || words.every((w) => `${s.institution} ${s.fi_name ?? ""} ${s.summary} ${s.type_label}`.toLowerCase().includes(w))));
    const key = q.sort === "added_desc" ? "added" : "event_date";
    rows = rows.sort((a, z) => cmp(z[key], a[key]) || cmp(z.id, a.id));
    const page = rows.slice(offset, offset + limit);
    const next = offset + limit < rows.length ? b64(`o:${offset + limit}`) : null;
    return { total: rows.length, count: page.length, next_cursor: next, signals: page };
  }

  /** Signals by publish date (`added`), oldest first, for incremental sync. Cursor = last (added, id) seen. */
  listNewSince(q: { since: string; types?: string[]; include_backfill?: boolean; limit?: number; cursor?: string }) {
    if (!DATE.test(q.since)) throw new ToolError("since must be YYYY-MM-DD");
    const types = this.expandTypes(q.types);
    const limit = clamp(q.limit ?? 100, 1, 200);
    let after: [string, string] | null = null;
    if (q.cursor) {
      const m = /^a:(\d{4}-\d{2}-\d{2}):(.+)$/.exec(unb64(q.cursor));
      if (!m) throw new ToolError("invalid cursor");
      after = [m[1], m[2]];
    }
    const rows = this.sortedByAdded.filter((s) =>
      s.added >= q.since && (q.include_backfill === true || !s.backfill) && (!types || types.has(s.type)) &&
      (!after || cmp(s.added, after[0]) > 0 || (s.added === after[0] && cmp(s.id, after[1]) > 0)));
    const page = rows.slice(0, limit);
    const last = page.at(-1);
    const cursor = last ? b64(`a:${last.added}:${last.id}`) : q.cursor ?? null;
    return { since: q.since, count: page.length, has_more: rows.length > limit, next_cursor: cursor, data_updated: this.b.meta.data_updated, signals: page };
  }

  resolve(q: { fi_id?: string; slug?: string; name?: string; state?: string }): { fi?: Institution; candidates?: Institution[] } {
    if (q.fi_id) {
      const fi = this.inst.get(q.fi_id.trim().toLowerCase());
      if (!fi) throw new ToolError(`no institution with fi_id "${q.fi_id}" (format fdic-<CERT> or ncua-<charter>)`);
      return { fi };
    }
    if (q.slug) {
      const p = q.slug.trim().replace(/^https?:\/\/[^/]+/, "").replace(/^\/?(fi\/)?/, "").replace(/\/$/, "").toLowerCase();
      const id = this.byPath.get(p);
      if (id) return { fi: this.inst.get(id)! };
      const hits = [...this.byPath.entries()].filter(([k]) => k.endsWith("/" + p)).map(([, v]) => this.inst.get(v)!);
      if (hits.length === 1) return { fi: hits[0] };
      if (hits.length > 1) return { candidates: hits.slice(0, 10) };
      throw new ToolError(`no institution page "${q.slug}" (use the /fi/<state>/<slug>/ path from fisignalweekly.com)`);
    }
    if (q.name) {
      const n = norm(q.name);
      const st = q.state?.toUpperCase();
      const all = [...this.inst.values()].filter((x) => !st || x.state === st);
      const exact = all.filter((x) => norm(x.name) === n || (x.also_known_as && norm(x.also_known_as) === n));
      const pool = exact.length ? exact : all.filter((x) => norm(x.name).includes(n) || (x.also_known_as ?? "").toLowerCase().includes(q.name!.toLowerCase()));
      pool.sort((a, z) => (z.total_assets_usd ?? 0) - (a.total_assets_usd ?? 0));
      if (pool.length === 1) return { fi: pool[0] };
      if (!pool.length) throw new ToolError(`no institution matching "${q.name}"${st ? " in " + st : ""}`);
      return { candidates: pool.slice(0, 10) };
    }
    throw new ToolError("give one of fi_id, slug or name");
  }

  profile(fi: Institution) {
    const f = this.b.financials[fi.fi_id];
    const qs = this.b.meta.trend_quarters;
    let financials = null;
    if (f) {
      const a = f.assets_usd;
      const g = (n: number) => (a.length > n && a.at(-1) != null && a.at(-1 - n) ? round((a.at(-1)! / a.at(-1 - n)!) - 1) : null);
      financials = {
        as_of: this.b.meta.assets_as_of,
        total_assets_usd: a.at(-1) ?? null, deposits_usd: f.deposits_usd, loans_usd: f.loans_usd,
        asset_trend: qs.map((q, i) => ({ quarter: q, total_assets_usd: a[i] ?? null })),
        asset_growth_1y: g(4), asset_growth_2y: g(8),
        members: f.members, offices: f.offices, sites: f.sites, established: f.established,
        regulator_history: f.history,
      };
    }
    const bm = this.b.benchmarks[fi.charter_type];
    return {
      ...fi,
      charter: fi.charter_type === "cu" ? "credit union" : "bank",
      financials,
      peer_benchmarks: bm ? { group: fi.charter_type === "cu" ? "all federally insured credit unions" : "all FDIC-insured banks", ...bm } : null,
      tech_stack: this.techStack(fi.fi_id),
      signals: (this.byFi.get(fi.fi_id) ?? []).slice().sort((a, z) => cmp(z.event_date, a.event_date)),
      sources: this.b.meta.sources,
    };
  }

  /** Mirrors resolve_provider() in scripts/build_directory.py: a verified announced change wins unless a later current row shows it. */
  techStack(fiId: string) {
    const p = this.b.providers[fiId] ?? {};
    const w = this.b.renewal_windows[fiId] ?? {};
    const out: Record<string, unknown> = {};
    for (const field of PROVIDER_FIELDS) {
      const rows = p[field] ?? [];
      const cur = rows.filter((r) => r.status === "current")
        .sort((a, z) => cmp(z.last_updated ?? "", a.last_updated ?? "") || Number(z.source_type === "Login page scan") - Number(a.source_type === "Login page scan"));
      const ann = rows.filter((r) => r.status === "announced").sort((a, z) => cmp(z.last_updated ?? "", a.last_updated ?? ""));
      let shown: Evidence | null = cur[0] ?? null, replaces: Evidence | null = null;
      if (ann[0] && !cur.some((c) => c.value === ann[0].value && (c.last_updated ?? "") >= (ann[0].last_updated ?? ""))) {
        shown = ann[0];
        replaces = cur.find((c) => c.value !== ann[0].value) ?? null;
      }
      out[field] = {
        label: FIELD_LABEL[field],
        value: shown?.value ?? null,
        identified: !!shown,
        status: shown?.status ?? null,
        evidence_type: shown?.source_type ?? null,
        source_url: shown?.source_url ?? null,
        last_updated: shown?.last_updated ?? null,
        note: shown?.note ?? (shown ? null : "Not yet identified"),
        replaces: replaces ? { value: replaces.value, evidence_type: replaces.source_type, source_url: replaces.source_url, last_updated: replaces.last_updated } : undefined,
        renewal_window_estimate: w[field] ?? undefined,
        evidence: rows.map((r) => ({ value: r.value, status: r.status, evidence_type: r.source_type, source_url: r.source_url, last_updated: r.last_updated, note: r.note })),
      };
    }
    return out;
  }

  techStackBatch(ids: string[]) {
    return ids.map((raw) => {
      const id = raw.trim().toLowerCase();
      const fi = this.inst.get(id);
      if (!fi) return { fi_id: raw, error: "unknown fi_id" };
      return { fi_id: id, name: fi.name, state: fi.state, page_url: fi.page_url, fields: this.techStack(id) };
    });
  }
}

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, Math.floor(n)));
const round = (n: number) => Math.round(n * 1e4) / 1e4;
const norm = (s: string) => s.toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();
