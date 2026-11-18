#!/usr/bin/env python3
"""Build /roadmap/ from data/roadmap.json."""
from __future__ import annotations
import html, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = "20261118whatsnew"
MONTHS = "January February March April May June July August September October November December".split()

def e(s): return html.escape(s or "", quote=True)
def fmt_date(d):
    y, m, dd = d.split("-")
    return f"{MONTHS[int(m)-1]} {int(dd)}, {y}"

def fmt_when(spec):
    if not spec: return None
    if spec.get("date"):
        text = fmt_date(spec["date"])
        if spec.get("note"): text += f", {spec['note']}"
    elif spec.get("label"):
        text = spec["label"]
    else:
        return None
    if spec.get("est"): text += " (est.)"
    return text

def when_html(label, spec):
    text = fmt_when(spec)
    if not text: return ""
    href = (spec or {}).get("href")
    name = (spec or {}).get("label")
    if href:
        link = f'<a href="{e(href)}">{e(name or text)}</a>'
        if name and name != text:
            return f'<div><dt>{e(label)}</dt><dd>{e(text)} · {link}</dd></div>'
        return f'<div><dt>{e(label)}</dt><dd><a href="{e(href)}">{e(text)}</a></dd></div>'
    return f'<div><dt>{e(label)}</dt><dd>{e(text)}</dd></div>'

def render_showcase(data):
    block = data.get("showcase_pages") or {}
    pages = block.get("pages") or []
    if not pages: return ""
    links = [f'<a href="{e(pg["href"])}">{e(pg["name"])}</a>' for pg in pages]
    if len(links) == 1: joined = links[0]
    elif len(links) == 2: joined = f"{links[0]} and {links[1]}"
    else: joined = ", ".join(links[:-1]) + ", and " + links[-1]
    note = block.get("note") or "New features land first on these showcase institution pages."
    return f'<aside class="rm-showcases"><p>{e(note)} {joined}.</p></aside>\n'

def render_item(item):
    st = item["status"]
    slug = st.lower().replace(" ", "-")
    parts = [f'<article class="rm-item st-{e(slug)}" id="{e(item["id"])}">']
    parts.append(f'<p class="rm-status"><span class="rm-badge">{e(st)}</span></p>')
    parts.append(f'<h2>{e(item["name"])}</h2>')
    parts.append(f'<p>{e(item["description"])}</p>')
    if item.get("blocked"):
        parts.append(f'<p class="rm-blocked">{e(item["blocked"])}</p>')
    rows = [when_html("Showcase", item.get("showcase")), when_html("Full", item.get("full"))]
    if item.get("cadence"):
        rows.append(f'<div><dt>Cadence</dt><dd>{e(item["cadence"])}</dd></div>')
    for ms in item.get("milestones") or []:
        rows.append(when_html(ms["label"], ms))
    rows = [r for r in rows if r]
    if rows: parts.append('<dl class="rm-dates">' + "".join(rows) + "</dl>")
    parts.append("</article>")
    return "\n".join(parts)

FOOTER = '''<footer><div class="wrap">FI Signal Weekly · <a href="/">Board</a> · <a href="/fi/">Directory</a> · <a href="/territory/">Territory</a> · <a href="/vendor-changes/">Vendor changes</a> · <a href="/whats-new/">What's new</a> · <a href="/roadmap/">Roadmap</a> · <a href="/about.html">About</a> · <a href="/#subscribe">Friday digest</a> · <a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener">Follow @FISignalWeekly</a></div></footer>'''

HEAD = '''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — FI Signal Weekly</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FI Signal Weekly">
<meta property="og:title" content="{title} — FI Signal Weekly">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="https://fisignalweekly.com{path}">
<meta property="og:image" content="https://fisignalweekly.com/img/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title} — FI Signal Weekly">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://fisignalweekly.com/img/og-image.png">
<meta name="twitter:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="theme-color" content="#000F26">
<link rel="canonical" href="https://fisignalweekly.com{path}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/img/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/img/favicon-16.png">
<link rel="icon" type="image/png" sizes="192x192" href="/img/mark-192.png">
<link rel="apple-touch-icon" sizes="180x180" href="/img/apple-touch-icon.png">
<meta name="twitter:site" content="@FISignalWeekly">
<meta name="twitter:creator" content="@FISignalWeekly">
<link rel="stylesheet" href="/css/style.css?v={cache}">
</head><body>
<header class="site"><div class="wrap">
  <a class="logo" href="/"><img class="mark" src="/img/mark-64.png" width="32" height="32" alt="">FI Signal <span>Weekly</span></a>
  <nav><a href="/#board">Board</a><a class="nav-dir" href="/fi/">Directory</a><a class="nav-opt" href="/about.html">About</a><a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener" aria-label="Follow @FISignalWeekly on X"><svg class="x-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span class="fx-text">Follow @FISignalWeekly</span></a></nav>
</div></header>
'''

def build():
    data = json.loads((ROOT / "data/roadmap.json").read_text(encoding="utf-8"))
    items = data["items"]
    updated = fmt_date(data["updated"])
    showcase_html = render_showcase(data)
    body = "\n".join(render_item(it) for it in items)
    counts = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    page = HEAD.format(title="Roadmap", desc="What is live on FI Signal Weekly, what is being built, and what is queued, with estimated showcase and full dates.", path="/roadmap/", cache=CACHE)
    page += f'''<main class="wrap rm">
  <header class="hero">
    <h1>Roadmap</h1>
    <p>{e(data["intro"])} See also <a href="/whats-new/">What's new</a>.</p>
    <p class="rm-updated">Last updated {e(updated)}</p>
  </header>
  {showcase_html}
  {body}
</main>
{FOOTER}
</body></html>
'''
    out = ROOT / "roadmap/index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(items)} items; " + ", ".join(f"{n} {k}" for k,n in counts.items()) + ")")

if __name__ == "__main__":
    build()
