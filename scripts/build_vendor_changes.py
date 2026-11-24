#!/usr/bin/env python3
"""Build /vendor-changes/ from data/vendor-changes/*.json.

Feed-shaped: each JSON file is one entry. Does not touch build_directory.py
or /fi/ pages. Re-run after adding an entry file.

Spec 08 (mobile): spec 02 header + nav.js, a key-facts block (effective date, notice date),
the vendor's public notice and our login-page scan as two separately labelled blocks,
affected lists collapsed with <details> (no JS, no layout shift), and a search/state
filter (js/vendor.js) that reuses the directory's labels and count wording.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from unlisted import is_unlisted          # never link an unlisted page
from build_directory import STATES, CF_BEACON

CACHE = "20261121vendor"
SHOW_FIRST = 6      # rows shown per group before "Show N more"
SHOW_ALL_UPTO = 8   # a group this small is never collapsed ("Show 2 more" helps nobody)


def e(s: str) -> str:
    return html.escape(s, quote=True)


def fmt_long(d: str) -> str:
    y, m, dd = d.split("-")
    months = "January February March April May June July August September October November December".split()
    return f"{months[int(m) - 1]} {int(dd)}, {y}"


def load_entries():
    files = sorted((ROOT / "data/vendor-changes").glob("*.json"))
    entries = []
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        d["_file"] = p.name
        entries.append(d)
    # newest notice first
    entries.sort(key=lambda x: x.get("notice_date") or "", reverse=True)
    return entries


def split_summary(d: dict):
    """(notice_html, scan_html). The entry body is unchanged copy; it is only split so the vendor's
    notice and our scan can be labelled apart. Optional keys notice_html / scan_html win if present."""
    if d.get("notice_html") or d.get("scan_html"):
        return d.get("notice_html") or "", d.get("scan_html") or ""
    body = d.get("summary_html")
    if not body and d.get("summary"):
        body = "<p>" + e(d["summary"]) + f' <a href="{e(d["notice_url"])}" rel="noopener">Read the original notice</a>.</p>'
    paras = re.findall(r"<p\b.*?</p>", body or "", flags=re.S)
    if not paras:
        return body or "", ""
    notice = [p for p in paras if d["notice_url"] in p] or paras[:1]
    scan = [p for p in paras if p not in notice]
    return "".join(notice), "".join(scan)


def fi_page_exists(path: str) -> bool:
    return (not is_unlisted(path)) and (ROOT / path.strip("/") / "index.html").exists()


def render_row(fi: dict) -> str:
    charter = "Credit union" if fi.get("charter") == "cu" else "Bank"
    # same text as before; the scan label gets its own span so phones can put it on its own line
    sub = (f'{e(fi["city"])}, {e(fi["state"])} · {charter}<span class="sep"> · </span>'
           f'<span class="scan">{e(fi["scan_label"])}</span>')
    inner = f'<span class="nm">{e(fi["name"])}</span><span class="sub">{sub}</span>'
    key = " ".join([fi["name"], fi["city"], fi["state"], STATES.get(fi["state"], "")]).lower()
    attrs = f'data-st="{e(fi["state"])}" data-k="{e(key)}" data-id="{e(fi["id"])}"'
    if fi.get("path") and fi_page_exists(fi["path"]):
        return f'<li {attrs}><a href="{e(fi["path"])}">{inner}</a></li>'
    return f'<li {attrs}><span class="nolink">{inner}</span></li>'   # no page: plain row, never a dead link


def render_entry(d: dict) -> str:
    eid = e(d["id"])
    title = e(d["notice_title"])
    notice_date = d["notice_date"]
    effective = d.get("effective_date")
    publisher = e(d.get("publisher") or "")
    groups = d.get("groups") or []
    fis = [fi for g in groups for fi in (g.get("fis") or [])]
    uniq = len({fi["id"] for fi in fis})
    notice_html, scan_html = split_summary(d)

    p = [f'<article class="vc-entry" id="{eid}" aria-labelledby="{eid}-h">', '<header class="vc-head">']
    if publisher:
        p.append(f'<p class="vc-vendor">{publisher}</p>')
    p.append(f'<h2 id="{eid}-h">{title}</h2>')
    p.append('<dl class="vc-facts">')
    if effective:
        p.append(f'<div class="vc-eff"><dt>Effective</dt><dd><time datetime="{e(effective)}">{e(fmt_long(effective))}</time>'
                 f'<span class="vc-cd" data-eff="{e(effective)}"></span></dd></div>')
    p.append(f'<div><dt>Notice dated</dt><dd><time datetime="{e(notice_date)}">{e(fmt_long(notice_date))}</time></dd></div>')
    p.append("</dl></header>")

    # 1. the vendor's public notice (confirmed by the vendor)
    p.append(f'<section class="vc-src vc-notice" aria-labelledby="{eid}-ln">')
    p.append(f'<p class="vc-label" id="{eid}-ln"><span class="vc-ico" aria-hidden="true"></span>Vendor\'s public notice</p>')
    p.append(notice_html)
    p.append("</section>")

    # 2. our login-page scan (inferred: may be affected)
    if groups:
        scan = d.get("scan") or {}
        p.append(f'<section class="vc-src vc-scan" aria-labelledby="{eid}-ls">')
        p.append(f'<p class="vc-label" id="{eid}-ls"><span class="vc-ico" aria-hidden="true"></span>Login-page scan: may be affected'
                 + (f'<span class="vc-scan-date">{e(scan["label"])}</span>' if scan.get("label") else "") + "</p>")
        p.append(scan_html)
        states = sorted({fi["state"] for fi in fis}, key=lambda s: STATES.get(s, s))
        opts = "".join(f'<option value="{e(s)}">{e(STATES.get(s, s))}</option>' for s in states)
        p.append(f'<div class="vc-filter" data-total="{uniq}">'
                 f'<div class="vc-q"><label for="{eid}-q">Search</label><input id="{eid}-q" type="search" placeholder="Name, city or state" autocomplete="off" enterkeyhint="search"></div>'
                 f'<div class="vc-st"><label for="{eid}-st">State</label><select id="{eid}-st"><option value="">All states</option>{opts}</select></div>'
                 f'<p class="vc-count" aria-live="polite"></p></div>')
        for g in groups:
            gf = g.get("fis") or []
            gid = f'{eid}-{e(g["id"])}'
            p.append(f'<section class="vc-group" id="{gid}" aria-labelledby="{gid}-h">')
            p.append(f'<h3 id="{gid}-h">{e(g["title"])} ({len(gf)})</h3>')
            if g.get("intro"):
                p.append(f'<p class="vc-intro">{e(g["intro"])}</p>')
            first, rest = (gf, []) if len(gf) <= SHOW_ALL_UPTO else (gf[:SHOW_FIRST], gf[SHOW_FIRST:])
            p.append('<ul class="fi-list vc-list">' + "".join(render_row(fi) for fi in first) + "</ul>")
            if rest:
                p.append(f'<details class="vc-more"><summary>Show {len(rest)} more</summary>'
                         '<ul class="fi-list vc-list">' + "".join(render_row(fi) for fi in rest) + "</ul></details>")
            p.append("</section>")
        p.append("</section>")
    p.append("</article>")
    return "\n".join(p)


def render_toc(entries) -> str:
    """Only with 2+ entries: a jump list, newest notice first (same order as the page)."""
    if len(entries) < 2:
        return ""
    rows = []
    for d in entries:
        eff = d.get("effective_date")
        sub = " · ".join(x for x in [e(d.get("publisher") or ""), f"Effective {e(fmt_long(eff))}" if eff else ""] if x)
        rows.append(f'<li><a href="#{e(d["id"])}"><span class="nm">{e(d["notice_title"])}</span><span class="sub">{sub}</span></a></li>')
    return '<nav class="vc-toc" aria-label="Entries"><ul class="fi-list">' + "".join(rows) + "</ul></nav>"


def write_html(entries):
    articles = "\n".join(render_entry(d) for d in entries) or '<p class="vc-empty">No entries yet.</p>'
    n = len(entries)
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Vendor platform changes — FI Signal Weekly</title>
<meta name="description" content="Public notices about digital banking platform changes, with institutions that may be affected based on login-page scans. Not a list of core systems.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FI Signal Weekly">
<meta property="og:title" content="Vendor platform changes — FI Signal Weekly">
<meta property="og:description" content="Public notices about digital banking platform changes, with institutions that may be affected based on login-page scans. Not a list of core systems.">
<meta property="og:url" content="https://fisignalweekly.com/vendor-changes/">
<meta property="og:image" content="https://fisignalweekly.com/img/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Vendor platform changes — FI Signal Weekly">
<meta name="twitter:description" content="Public notices about digital banking platform changes, with institutions that may be affected based on login-page scans. Not a list of core systems.">
<meta name="twitter:image" content="https://fisignalweekly.com/img/og-image.png">
<meta name="twitter:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="theme-color" content="#000F26">
<link rel="canonical" href="https://fisignalweekly.com/vendor-changes/">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/img/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/img/favicon-16.png">
<link rel="icon" type="image/png" sizes="192x192" href="/img/mark-192.png">
<link rel="apple-touch-icon" sizes="180x180" href="/img/apple-touch-icon.png">
<meta name="twitter:site" content="@FISignalWeekly">
<meta name="twitter:creator" content="@FISignalWeekly">
<link rel="stylesheet" href="/css/style.css?v={CACHE}">
</head><body>
<header class="site"><div class="wrap">
  <a class="logo" href="/"><img class="mark" src="/img/mark-64.png" width="32" height="32" alt="">FI Signal <span>Weekly</span></a>
  <nav><a href="/#board">Board</a><a class="nav-opt" href="/#sponsor">Sponsor</a><a class="nav-dir" href="/fi/">Directory</a><a class="nav-opt" href="/about.html">About</a><a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener" aria-label="Follow @FISignalWeekly on X"><svg class="x-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span class="fx-text">Follow @FISignalWeekly</span></a><button class="nav-toggle" id="nav-toggle" type="button" aria-expanded="false" aria-controls="site-menu" aria-label="Menu" hidden><svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></nav>
</div></header>
<main class="wrap vc">
  <header class="vc-hero">
    <h1>Vendor platform changes</h1>
    <p>Public notices about digital banking platforms, with institutions that may be affected based on a login-page scan. This is not a list of core systems. New entries will be added as public notices appear.</p>
  </header>
  {render_toc(entries)}
  {articles}
</main>
<footer><div class="wrap">FI Signal Weekly · Login-page scan evidence and public vendor notices only. Verify before acting. Not affiliated with any regulator or vendor. · <a href="/">Board</a> · <a href="/fi/">Directory</a> · <a href="/vendor-changes/" aria-current="page">Vendor changes</a> · <a href="/about.html">About</a> · <a href="/#subscribe">Friday digest</a> · <a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener">Follow @FISignalWeekly</a></div></footer>
<script src="/js/nav.js?v=20261119nav" defer></script>
<script src="/js/vendor.js?v={CACHE}" defer></script>
{CF_BEACON}</body></html>
"""
    out = ROOT / "vendor-changes/index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({n} entr{'y' if n==1 else 'ies'})")


if __name__ == "__main__":
    write_html(load_entries())
