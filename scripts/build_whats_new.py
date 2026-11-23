#!/usr/bin/env python3
"""Build /whats-new/ from data/whats-new.json."""
from __future__ import annotations
import html, json
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from unlisted import is_unlisted, ROBOTS_META

ROOT = Path(__file__).resolve().parents[1]
CACHE = "20261118whatsnew"
CF_BEACON = """<script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "ffe394f0466d4ff8866c7bbfd8d53eb2"}'></script>
"""
MONTHS = "January February March April May June July August September October November December".split()

def e(s): return html.escape(s or "", quote=True)
def fmt(d):
    y, m, dd = d.split("-")
    return f"{MONTHS[int(m)-1]} {int(dd)}, {y}"

def build():
    data = json.loads((ROOT / "data/whats-new.json").read_text(encoding="utf-8"))
    by_date = defaultdict(list)
    for item in data["entries"]:
        by_date[item["date"]].append(item)
    sections = []
    for d in sorted(by_date, reverse=True):
        sections.append(f'<section class="wn-day" id="d-{e(d)}">')
        sections.append(f'<h2><time datetime="{e(d)}">{e(fmt(d))}</time></h2>')
        for item in by_date[d]:
            sections.append(f'<article class="wn-entry" id="{e(item["id"])}">')
            sections.append(f'<h3>{e(item["title"])}</h3>')
            if not item.get("link_href") or is_unlisted(item.get("link_href")):  # never link unlisted pages
                sections.append(f'<p>{e(item["body"])}</p>')
            else:
                sections.append(f'<p>{e(item["body"])} <a href="{e(item["link_href"])}">Example: {e(item["link_label"])}</a>.</p>')
            sections.append("</article>")
        sections.append("</section>")
    cache = CACHE
    page = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>What's new — FI Signal Weekly</title>
<meta name="description" content="Release notes for FI Signal Weekly: dated, plain-language notes about what changed on the site, each with an example page.">
{ROBOTS_META}
<meta property="og:type" content="website">
<meta property="og:site_name" content="FI Signal Weekly">
<meta property="og:title" content="What's new — FI Signal Weekly">
<meta property="og:description" content="Release notes for FI Signal Weekly: dated, plain-language notes about what changed on the site, each with an example page.">
<meta property="og:url" content="https://fisignalweekly.com/whats-new/">
<meta property="og:image" content="https://fisignalweekly.com/img/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="What's new — FI Signal Weekly">
<meta name="twitter:description" content="Release notes for FI Signal Weekly: dated, plain-language notes about what changed on the site, each with an example page.">
<meta name="twitter:image" content="https://fisignalweekly.com/img/og-image.png">
<meta name="twitter:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="theme-color" content="#000F26">
<link rel="canonical" href="https://fisignalweekly.com/whats-new/">
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
<main class="wrap wn">
  <header class="hero">
    <h1>What's new</h1>
    <p>Dated notes about what changed on FI Signal Weekly, each with a link to an example page.</p>
  </header>
  {"".join(sections)}
</main>
<footer><div class="wrap">FI Signal Weekly · <a href="/">Board</a> · <a href="/fi/">Directory</a> · <a href="/about.html">About</a> · <a href="/#subscribe">Friday digest</a> · <a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener">Follow @FISignalWeekly</a></div></footer>
{CF_BEACON}</body></html>
'''
    out = ROOT / "whats-new/index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print("wrote", out)

if __name__ == "__main__":
    build()
