"""Institution-page sections for the /fi/ directory (used by scripts/build_directory.py).

Inputs are already-loaded public data: data/callreports.json (FDIC/NCUA call report history, offices, members,
FDIC history events), data/providers.csv rows and board rows from data/triggers.json. Nothing here fetches or
estimates anything; missing data renders as a plain "not reported" / "Not yet identified".
"""
import html, json, math, re

e = lambda s: html.escape(str(s), quote=True)

# Feature flags: a name listed here renders only on showcase pages (data/showcase.txt). Move a feature to all
# pages by removing it from this set. Empty = every shipped feature is on every page.
SHOWCASE_ONLY = set()  # strategic_priorities moved to every matching institution page Nov 24, 2026

# Parent ticker -> operating-bank fi_ids that have /fi/ pages (from data/institutions.json).
# load_strategy uses this when a row's fi_ids are empty or none of them match a directory institution.
# BBT is the retired ticker for the same operating bank as TFC.
STRATEGY_TICKERS = {
    "BAC": ("fdic-3510", "fdic-25178"),
    "BKU": ("fdic-58979",),
    "C": ("fdic-7213",),
    "COF": ("fdic-4297",),
    "GBCI": ("fdic-30788",),
    "JPM": ("fdic-628", "fdic-21761"),
    "KISB": ("fdic-14969",),
    "MS": ("fdic-32992", "fdic-34221"),
    "PNC": ("fdic-6384",),
    "TFC": ("fdic-9846",),
    "BBT": ("fdic-9846",),  # retired ticker; same bank as TFC
    "UFS": ("fdic-90290",),
    "USB": ("fdic-6548",),
    "WFC": ("fdic-3511", "fdic-27389", "fdic-5146"),
    "FFBC": ("fdic-6600",),
    "FMBH": ("fdic-3705",),
    "MPB": ("fdic-9889",),
    "JMSB": ("fdic-58243",),
    "HBAN": ("fdic-6560",),
    "KEY": ("fdic-17534",),
    "RNST": ("fdic-12437",),
    "DCOM": ("fdic-6976",),
    "PEBO": ("fdic-6544",),
    "EQBK": ("fdic-25858",),
    "FMNB": ("fdic-6540",),
    "TCBX": ("fdic-58716",),
    "HBT": ("fdic-20369",),
}


def strategy_page_ids(row, known=None):
    """Institution ids a strategic_priorities row should appear on.

    Uses the row's fi_ids when they match known directory institutions. If none do (or fi_ids
    is empty), falls back to STRATEGY_TICKERS for the row's ticker.
    """
    fids = [x.strip() for x in (row.get("fi_ids") or "").split("|") if x.strip()]
    if known is not None:
        valid = [x for x in fids if x in known]
    else:
        valid = fids
    if valid:
        return valid
    ticker = (row.get("ticker") or "").strip().upper()
    mapped = list(STRATEGY_TICKERS.get(ticker, ()))
    if known is not None:
        mapped = [x for x in mapped if x in known]
    return mapped


def feature_on(name, is_showcase):
    return is_showcase or name not in SHOWCASE_ONLY


def load_showcase(root):
    import os
    p = os.path.join(root, "data", "showcase.txt")
    if not os.path.exists(p):
        return set()
    return {ln.split("#")[0].strip() for ln in open(p, encoding="utf-8") if ln.split("#")[0].strip()}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
METRICS = [("a", "Assets", "Total assets"), ("d", "Deposits", "Deposits"), ("l", "Loans", "Loans and leases")]
QEND = {1: "March 31", 2: "June 30", 3: "September 30", 4: "December 31"}


def ws(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def fmt_date(d):
    y, m, dd = d.split("-")
    return f"{MONTHS[int(m) - 1]} {int(dd)}, {y}"


def qname(q):  # "2026Q2" -> "Q2 2026"
    return f"{q[4:]} {q[:4]}"


def money_k(k):
    """$ thousands -> $1.2B / $45.6M / $820K."""
    if k is None:
        return "—"
    usd = k * 1000
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(usd) >= div:
            v = usd / div
            t = f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}"
            return "$" + re.sub(r"\.0$", "", t) + suf
    return f"${usd / 1e3:,.0f}K"


def pct(new, old):
    if new is None or old in (None, 0):
        return None
    return (new / old - 1) * 100


def pct_html(p):
    if p is None:
        return '<span class="pc">—</span>'
    cls = "up" if p > 0.05 else "dn" if p < -0.05 else ""
    sign = "+" if p > 0 else ("−" if p < 0 else "")
    return f'<span class="pc {cls}">{sign}{abs(p):.1f}%</span>'


def first_idx(series):
    return next((i for i, v in enumerate(series) if v is not None), None)


# ---------------------------------------------------------------- charts (inline SVG)
def spark_svg(series, w=120, h=32):
    pts = [(i, v) for i, v in enumerate(series) if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1
    n = len(series) - 1 or 1
    xy = " ".join(f"{(i / n) * (w - 4) + 2:.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}" for i, v in pts)
    lx, ly = xy.split(" ")[-1].split(",")
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true" focusable="false">'
            f'<polyline points="{xy}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx}" cy="{ly}" r="2.6" fill="currentColor"/></svg>')


def chart_svg(series, quarters):
    """Static first render of the interactive chart (js/fi-chart.js redraws it the same way)."""
    W, H, L, R, T, B = 640, 260, 84, 12, 14, 34
    pts = [(i, v) for i, v in enumerate(series) if v is not None]
    if len(pts) < 2:
        return '<p class="empty-note">Not enough quarters reported to draw a trend.</p>'
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    pad = (hi - lo) * 0.08 or hi * 0.05 or 1
    lo, hi = max(0, lo - pad), hi + pad
    n = len(series) - 1
    X = lambda i: L + i / n * (W - L - R)
    Y = lambda v: T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
    path = " ".join(f"{'M' if k == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for k, (i, v) in enumerate(pts))
    grid = ""
    for g in range(3):
        v = lo + (hi - lo) * g / 2
        grid += (f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="gl"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{e(money_k(v))}</text>')
    years = ""
    for i, q in enumerate(quarters):
        if q.endswith("Q1") and int(q[:4]) % 2 == 0:
            years += f'<text x="{X(i):.1f}" y="{H - 8}" text-anchor="middle">{q[:4]}</text>'
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Quarterly trend chart">'
            f'{grid}{years}<path d="{path}" class="ln"/></svg>')


# ---------------------------------------------------------------- sections
def header_trend(cr, q_as_of):
    a = cr["a"]
    if a[-1] is None:
        return ""
    yoy = pct(a[-1], a[-5]) if len(a) >= 5 else None
    yo = f'{pct_html(yoy)} <span class="muted-inline">assets, 1 yr</span>' if yoy is not None else '<span class="muted-inline">assets trend</span>'
    return f'<p class="hdr-trend" title="Total assets, last 5 years of call reports">{spark_svg(a[-21:])}<span>{yo}</span></p>'


def trend_section(cr, quarters, as_of, charter, bench=None):
    src = ("FDIC BankFind call reports" if charter == "bank" else "NCUA 5300 call reports")
    if all(v is None for v in cr["a"]):
        return (f'<section class="fin" aria-labelledby="fin-h"><h2 id="fin-h">Assets, deposits &amp; loans</h2>'
                f'<p class="empty-note">No call report figures on file for this institution yet ({e(src)}).</p></section>')
    fi0 = first_idx(cr["a"])
    tabs, tables = [], []
    for k_, short, long_ in METRICS:
        s = cr.get(k_) or []
        on = k_ == "a"
        tabs.append(f'<button type="button" class="tab" data-m="{k_}" aria-pressed="{"true" if on else "false"}">{short}</button>')
        if not on:  # deposits / loans tables are built by js/fi-chart.js from the embedded data (keeps pages light)
            continue
        rows = []
        for j in range(len(s) - 1, max(len(s) - 9, fi0 - 1), -1):
            v = s[j]
            qoq = pct(v, s[j - 1]) if j >= 1 else None
            yoy = pct(v, s[j - 4]) if j >= 4 else None
            rows.append(f"<tr><th scope=\"row\">{qname(quarters[j])}</th><td>{money_k(v)}</td><td>{pct_html(qoq)}</td><td>{pct_html(yoy)}</td></tr>")
        tables.append(f'<table class="fin-t" data-m="{k_}"{"" if on else " hidden"}><caption class="sr">{long_}, last 8 quarters</caption>'
                      f'<thead><tr><th scope="col">Quarter</th><th scope="col">{short}</th><th scope="col">QoQ</th><th scope="col">YoY</th></tr></thead>'
                      f'<tbody>{"".join(rows)}</tbody></table>')
    # chart + embedded data start at the first quarter this institution reported (new charters get a short, readable chart)
    data = {"q0": quarters[fi0], **{k_: (cr.get(k_) or [])[fi0:] for k_, _, _ in METRICS}}
    bhtml, bnote = "", ""
    if bench:
        data.update(bench["data"])
        bhtml, bnote = bench["html"], bench["note"]
    y, q = as_of[:4], int(as_of[5])
    start = f' Figures on this page start {qname(quarters[fi0])}.' if fi0 else ""
    return (f'<section class="fin" aria-labelledby="fin-h"><h2 id="fin-h">Assets, deposits &amp; loans</h2>'
            f'<div class="tabs" role="group" aria-label="Choose a measure">{"".join(tabs)}</div>{bhtml}'
            f'<figure class="fin-chart"><div class="chart-wrap">{chart_svg(cr["a"][fi0:], quarters[fi0:])}<div class="tip" hidden></div></div>'
            f'<figcaption class="note">Quarterly, {qname(quarters[fi0])} to {qname(as_of)}. Tap or hover the chart for a quarter.</figcaption></figure>'
            f'{bnote}<div class="fin-tables">{"".join(tables)}</div>'
            f'<p class="note">Source: {e(src)}, as of {qname(as_of)} ({QEND[q]}, {y}). QoQ = change from the prior quarter, YoY = change from the same quarter a year earlier.{start}</p>'
            f'<script type="application/json" class="fin-data">{json.dumps(data, separators=(",", ":"))}</script></section>')


THEME_LABEL = {"digital": "Digital", "payments": "Payments", "lending": "Lending", "deposits": "Deposits",
               "efficiency": "Efficiency", "M&A": "M&amp;A"}


def load_strategy(root):
    """data/strategic_priorities.csv -> {fi_id: [row, ...]} in file order. Rows belong to the parent company and show on
    every subsidiary page in fi_ids (pipe list) as 'Stated by <parent_name>'."""
    import csv, os
    p = os.path.join(root, "data", "strategic_priorities.csv")
    out = {}
    if not os.path.exists(p):
        return out
    known = None
    inst = os.path.join(root, "data", "institutions.json")
    if os.path.exists(inst):
        db = json.load(open(inst, encoding="utf-8"))
        known = {dict(zip(db["columns"], row))["id"] for row in db["rows"]}
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            fids = strategy_page_ids(r, known)
            if not fids:
                t = (r.get("ticker") or r.get("row_id") or "?").strip() or "?"
                print("strategic_priorities: no directory page for", r.get("row_id") or t)
            for fid in fids:
                out.setdefault(fid, []).append(r)
    return out


def strategy_section(rows):
    """Stated strategic priorities, quoted verbatim from the parent's public filings. No rows = no section."""
    if not rows:
        return ""
    parents = sorted({(r["parent_name"], r["ticker"]) for r in rows})
    by = ", ".join(f'{e(n)} ({e(t)})' if t else e(n) for n, t in parents)
    li = "".join(
        f'<li><span class="ex-date">{THEME_LABEL.get(r["theme"], e(r["theme"]))}</span>'
        f'<p class="sp-label">{e(r["priority"])}</p>'
        f'<blockquote class="sp-quote"><p>“{e(r["quote"])}”</p></blockquote>'
        f'<p class="sp-src">Stated by {e(r["parent_name"])}' + (f' ({e(r["ticker"])})' if r["ticker"] else "") +
        f' · {e(r["source_label"])}' + (f', {e(r["locator"])}' if r.get("locator") else "") +
        f' · filed {fmt_date(r["source_date"])}</p>'
        f'<p class="sig-links"><a href="{e(r["source_url"])}" target="_blank" rel="noopener noreferrer">Source ↗</a></p></li>'
        for r in rows)
    return (f'<section class="strat" aria-labelledby="sp-h"><h2 id="sp-h">Strategic priorities <span class="count-pill">{len(rows)}</span></h2>'
            f'<p class="note">What {by} says it is focusing on, quoted word for word from its public filings. '
            f'The short label above each quote is ours.</p><ul class="ex-list sp-list">{li}</ul></section>')


def peer_section(peer):
    if not peer:
        return ""
    items = "".join(f"<li>{x}</li>" for x in peer)
    return f'<section class="peer" aria-labelledby="peer-h"><h2 id="peer-h">Peer rank</h2><ul class="peer-list">{items}</ul></section>'


def exec_section(rows, type_label):
    ex = [r for r in rows if r["type"] in ("executive", "cu_executive")][:5]
    if not ex:
        return ('<section class="execs" aria-labelledby="ex-h"><h2 id="ex-h">Key executives</h2>'
                '<p class="empty-note">No leadership moves in our verified signals yet. Executive changes appear here when we verify them from public sources.</p></section>')
    li = "".join(f'<li><span class="ex-date">{fmt_date(r["date"])}</span><p>{e(r["summary"])}</p>'
                 f'<p class="sig-links">' + (f'<a href="/#{e(r["id"])}">See the signal</a>' if r.get("fi_only") is not True and r.get("type") != "branch_opening" else "") + f'<a href="{e(r["source_url"])}" target="_blank" rel="noopener noreferrer">Source ↗</a></p></li>'
                 for r in ex)
    return (f'<section class="execs" aria-labelledby="ex-h"><h2 id="ex-h">Key executives <span class="count-pill">{len(ex)}</span></h2>'
            f'<p class="note">Leadership moves from our verified signals, newest first.</p><ul class="ex-list">{li}</ul></section>')


def history_section(hist, rows, class_label, charter, type_label):
    items = []
    for h in hist or []:
        c, other = h["code"], ws(h.get("other", ""))
        if c == 110:
            t = "Opened as a new institution"
        elif c in (810, 811) and other:
            t = f"Merged in {e(other)}" + (" (FDIC-assisted)" if c == 811 else "")
        elif c == 712 and other:
            t = f"Bought branches from {e(other)}"
        elif c == 510 and h.get("from_name") and h.get("name") and ws(h["from_name"]) != ws(h["name"]):
            t = f"Name changed from {e(ws(h['from_name']))} to {e(ws(h['name']))}"
        elif c == 430 and h.get("from_class") and h.get("class") and h["from_class"] != h["class"]:
            t = f"Charter class changed: {e(class_label.get(h['from_class'], h['from_class']))} → {e(class_label.get(h['class'], h['class']))}"
        elif c == 420:
            t = "Changed chartering agency"
        elif c == 440:
            t = "Changed organization type"
        else:
            continue
        items.append((h["date"], f'<li><span class="ex-date">{fmt_date(h["date"])}</span><p>{t}</p><p class="src-tag">FDIC history</p></li>'))
    for r in rows:
        if r["type"] in ("merger", "cu_merger", "cu_acquires_bank", "cu_charter"):
            items.append((r["date"], f'<li><span class="ex-date">{fmt_date(r["date"])}</span><p><span class="badge {e(r["type"])}">{e(type_label.get(r["type"], r["type"]))}</span> {e(r["summary"])}</p>'
                                     f'<p class="sig-links">' + (f'<a href="/#{e(r["id"])}">See the signal</a>' if r.get("fi_only") is not True and r.get("type") != "branch_opening" else "") + f'<a href="{e(r["source_url"])}" target="_blank" rel="noopener noreferrer">Source ↗</a></p></li>'))
    items.sort(key=lambda x: x[0], reverse=True)
    note = ("FDIC institution history since 2016 plus merger and charter signals from the board."
            if charter == "bank" else "Credit union mergers and charter changes from our verified board signals.")
    if not items:
        return (f'<section class="hist" aria-labelledby="hi-h"><h2 id="hi-h">Mergers &amp; charter history</h2>'
                f'<p class="empty-note">None on file since 2016. {note}</p></section>')
    more = len(items) - 10
    return (f'<section class="hist" aria-labelledby="hi-h"><h2 id="hi-h">Mergers &amp; charter history <span class="count-pill">{len(items)}</span></h2>'
            f'<p class="note">{note}</p><ul class="ex-list">{"".join(h for _, h in items[:10])}</ul>'
            + (f'<p class="note">{more} earlier event{"s" if more != 1 else ""} not shown.</p>' if more > 0 else "") + "</section>")


def similar_section(x, similar, vendor, st_name, tier_label, fi_li):
    if not similar:
        return ""
    basis = (f"Same state ({e(st_name)}), asset tier ({e(tier_label)}) and online banking platform ({e(vendor)}, from our login page scan)"
             if vendor else f"Same state ({e(st_name)}) and asset tier ({e(tier_label)}); none of them share an online banking platform we identified with this one, or it has none on file")
    return (f'<section class="similar" aria-labelledby="sim-h"><h2 id="sim-h">Similar institutions</h2>'
            f'<p class="note">{basis}. Closest in total assets first.</p><ul class="fi-list">{"".join(fi_li(y) for y in similar)}</ul></section>')


# ---------------------------------------------------------------- asset-chart benchmarks (data from scripts/build_benchmarks.py)
MIN_PEERS = 5  # same as scripts/build_benchmarks.py
def _distinct(vals, fmt, lo=1, hi=3):
    """Smallest decimals (lo..hi) at which values that differ also print differently."""
    for d in range(lo, hi + 1):
        out = [fmt(v, d) for v in vals]
        if all(out[i] != out[j] for i in range(len(vals)) for j in range(i) if vals[i] != vals[j]):
            return out
    return [fmt(v, hi) for v in vals]


def verdict_text(ratios, start_label, peer_label, ind_label, real=False, mult=None):
    """ratios = [this FI, peer median or None, industry median]; each = assets now / assets at the chart start.

    Multiples ("3.5x") when any ratio is 2 or more, else % change; decimals grow until different numbers print differently.
    """
    vals = [r for r in ratios if r is not None]
    if (max(vals) >= 2) if mult is None else mult:
        out = _distinct(vals, lambda v, d: f"{v:.{d}f}x")
        lead = f"are {out[0]} their {start_label} level"
    else:
        def pc(v, d):
            p = (v - 1) * 100
            return f"{'+' if p > 0 else '−' if p < 0 else ''}{abs(p):.{d}f}%"
        out = _distinct(vals, pc)
        p0 = (vals[0] - 1) * 100
        lead = (f"are up {out[0].lstrip('+')}" if p0 > 0 else f"are down {out[0].lstrip('−')}" if p0 < 0 else "are flat") + f" since {start_label}"
    it = iter(out[1:])
    cmp_ = []
    if ratios[1] is not None:
        cmp_.append(f"{next(it)} for the {peer_label} median")
    cmp_.append(f"{next(it)} for the median {ind_label}")
    s = f"Assets {lead}, vs {' and '.join(cmp_)}"
    return ("Adjusted for inflation, a" + s[1:] if real else s) + "."


def chart_events(hist, rows, quarters, fi0):
    """Merger markers: FDIC history mergers / branch purchases and the board's merger signals, by chart quarter."""
    qi = {q: i - fi0 for i, q in enumerate(quarters) if i >= fi0}
    ev = {}
    def add(d, t):
        y, m = int(d[:4]), int(d[5:7])
        j = qi.get(f"{y}Q{(m - 1) // 3 + 1}")
        if j is not None:
            ev.setdefault(j, []).append(f"{fmt_date(d)}: {t}")
    for h in hist or []:
        other = ws(h.get("other", ""))
        if h["code"] in (810, 811) and other:
            add(h["date"], f"merged in {other}" + (" (FDIC-assisted)" if h["code"] == 811 else ""))
        elif h["code"] == 712 and other:
            add(h["date"], f"bought branches from {other}")
    for r in rows:
        if r["type"] in ("merger", "cu_merger", "cu_acquires_bank"):
            sm = ws(r["summary"])
            add(r["date"], "merger signal: " + (sm if len(sm) <= 90 else sm[:88].rsplit(" ", 1)[0] + "…"))
    return [[j, " · ".join(reversed(v))] for j, v in sorted(ev.items())]


def bench_block(cr, quarters, charter, bm, peer, peer_n, tier_label, events):
    """HTML (controls, verdict, legend, note) + chart data for the asset benchmarks. None if assets can't be indexed."""
    a = cr["a"]
    fi0 = first_idx(a)
    word = "bank" if charter == "bank" else "credit union"
    words = word + "s"
    if fi0 is None:
        return None
    ind = bm[charter]
    med = ind["med"].get(quarters[fi0])
    why = None
    if a[-1] is None:
        why = f"there is no {qname(quarters[-1])} call report on file for this {word}, so there is no current figure to compare"
    elif not a[fi0]:
        why = (f"this {word}&#39;s first call report on file ({qname(quarters[fi0])}) shows $0 in assets, "
               "so its growth can&#39;t be indexed against peers")
    elif not med or med[-1] is None:
        why = f"there is no industry median for {qname(quarters[fi0])} to compare with"
    if why:
        return {"data": {}, "html": f'<p class="note bm-none">No peer comparison on this chart: {why}.</p>', "note": ""}
    sl = qname(quarters[fi0])
    tot = ind["total"]
    cpi = bm["cpi"]
    ratios = [a[-1] / a[fi0], peer[-1] if peer else None, med[-1]]
    v_nom = verdict_text(ratios, sl, "peer", word)
    defl = cpi[fi0] / cpi[-1]
    v_real = verdict_text([r * defl if r is not None else None for r in ratios], sl, "peer", word, real=True,
                          mult=max(r for r in ratios if r is not None) >= 2)  # same unit as the plain line
    ix = lambda xs: [None if v is None else round(v * 100, 1) for v in xs[fi0:]]
    data = {"bm": {"im": ix(med), "it": [round(t / tot[fi0] * 100, 1) for t in tot[fi0:]],
                   "cpi": [round(c, 3) for c in cpi[fi0:]],
                   "n": {"fi": f"This {word}", "p": "Peer median", "im": f"Median {word}", "it": f"All {words}, total"}}, "ev": events}
    if peer:
        data["bm"]["p"] = ix(peer)
    reg = "FDIC-insured" if charter == "bank" else "federally insured"
    tl = tier_label[0].lower() + tier_label[1:] if tier_label.startswith("Under") else tier_label
    legend = (f'<li><i class="k k-fi"></i>This {word}</li>'
              + (f'<li><i class="k k-p"></i>Peer median ({peer_n:,} {e(tl)} {words})</li>' if peer else "")
              + f'<li><i class="k k-im"></i>Median {word}</li><li><i class="k k-it"></i>All {words}, total</li>'
              + ('<li><i class="k k-ev"></i>Merger</li>' if events else ""))
    html_ = (f'<p class="verdict" data-nom="{e(v_nom)}" data-real="{e(v_real)}">{e(v_nom)}</p>'
             f'<div class="bm-ctl" hidden><div class="seg" role="group" aria-label="Chart view">'
             f'<button type="button" class="vw" data-v="usd" aria-pressed="true">Dollars</button>'
             f'<button type="button" class="vw" data-v="idx" aria-pressed="false">vs peers</button></div>'
             f'<label class="cpi-t"><input type="checkbox" class="cpi-in"> Adjust for inflation</label></div>'
             f'<ul class="bm-legend" hidden>{legend}</ul>'
             + ("" if peer else f'<p class="note bm-none">No peer median: fewer than {MIN_PEERS} other {e(tl)} {words} reported in {sl} '
                                f'and today, so this compares with the median {word} and the industry total only.</p>'))
    peer_txt = (f"Peer median: the middle of today&#39;s {e(tl)} {words} (the same tier as the peer rank below) "
                f"that reported in {sl}, this one left out, each indexed to 100 there."
                if peer else f"Too few {e(tl)} {words} reported in {sl} for a peer median, so there is no peer line.")
    if events:
        ev_txt = ('<p class="note bm-ev"><span class="k k-ev" aria-hidden="true"></span> marks a merger or branch purchase'
                  + (" from FDIC history or" if charter == "bank" else "") + " from our merger signals (tap the chart for details). "
                  "Acquisitions add the acquired institution&#39;s assets in the quarter the deal closes, so they can cause jumps "
                  "that aren&#39;t organic growth.</p>")
    else:
        ev_txt = ('<p class="note bm-ev">Acquisitions add the acquired institution&#39;s assets in the quarter the deal closes, '
                  "so they can cause jumps. " + (f"None on file in FDIC history or our signals for this bank since {sl}."
                  if charter == "bank" else "We have no merger on file for this credit union in our signals.") + "</p>")
    note = (ev_txt + f'<details class="bm-how"><summary>How the comparison works</summary><p class="note">“vs peers” indexes each line to 100 at {sl}. '
            f'{peer_txt} Median {word}: the middle of all {reg} {words} that reported in both {sl} and that quarter. '
            f'All {words}, total: the sum of every filer&#39;s assets each quarter, so it includes {words} that opened, merged or closed. '
            f'Peer and median lines count only institutions that still file today, so they leave out ones that merged away or closed. Inflation uses the BLS CPI-U '
            f'(all items, U.S. city average), averaged by quarter; the dollar view is in {qname(quarters[-1])} dollars. '
            f'The line above compares assets in {qname(quarters[-1])} with {sl}. '
            f'Source: {"FDIC BankFind" if charter == "bank" else "NCUA 5300"} call reports and BLS.</p></details>')
    return {"data": data, "html": html_, "note": note}
