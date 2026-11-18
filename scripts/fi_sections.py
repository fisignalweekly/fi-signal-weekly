"""Institution-page sections for the /fi/ directory (used by scripts/build_directory.py).

Inputs are already-loaded public data: data/callreports.json (FDIC/NCUA call report history, offices, members,
FDIC history events), data/providers.csv rows and board rows from data/triggers.json. Nothing here fetches or
estimates anything; missing data renders as a plain "not reported" / "Not yet identified".
"""
import html, json, math, re

e = lambda s: html.escape(str(s), quote=True)

# Feature flags: a name listed here renders only on showcase pages (data/showcase.txt). Move a feature to all
# pages by removing it from this set. Empty = every shipped feature is on every page.
SHOWCASE_ONLY = set()


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


def trend_section(cr, quarters, as_of, charter):
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
    y, q = as_of[:4], int(as_of[5])
    start = f' Figures on this page start {qname(quarters[fi0])}.' if fi0 else ""
    return (f'<section class="fin" aria-labelledby="fin-h"><h2 id="fin-h">Assets, deposits &amp; loans</h2>'
            f'<div class="tabs" role="group" aria-label="Choose a measure">{"".join(tabs)}</div>'
            f'<figure class="fin-chart"><div class="chart-wrap">{chart_svg(cr["a"][fi0:], quarters[fi0:])}<div class="tip" hidden></div></div>'
            f'<figcaption class="note">Quarterly, {qname(quarters[fi0])} to {qname(as_of)}. Tap or hover the chart for a quarter.</figcaption></figure>'
            f'<div class="fin-tables">{"".join(tables)}</div>'
            f'<p class="note">Source: {e(src)}, as of {qname(as_of)} ({QEND[q]}, {y}). QoQ = change from the prior quarter, YoY = change from the same quarter a year earlier.{start}</p>'
            f'<script type="application/json" class="fin-data">{json.dumps(data, separators=(",", ":"))}</script></section>')


def peer_section(peer):
    if not peer:
        return ""
    items = "".join(f"<li>{x}</li>" for x in peer)
    return f'<section class="peer" aria-labelledby="peer-h"><h2 id="peer-h">Peer rank</h2><ul class="peer-list">{items}</ul></section>'


def exec_section(rows, type_label):
    ex = [r for r in rows if r["type"] in ("executive", "cu_executive")][:5]
    if not ex:
        return ""
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
    basis = (f"Same state ({e(st_name)}), asset tier ({e(tier_label)}) and digital banking platform ({e(vendor)}, from our login page scan)"
             if vendor else f"Same state ({e(st_name)}) and asset tier ({e(tier_label)}); none of them share a digital banking platform we identified with this one, or it has none on file")
    return (f'<section class="similar" aria-labelledby="sim-h"><h2 id="sim-h">Similar institutions</h2>'
            f'<p class="note">{basis}. Closest in total assets first.</p><ul class="fi-list">{"".join(fi_li(y) for y in similar)}</ul></section>')
