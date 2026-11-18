#!/usr/bin/env python3
"""Build /vendor-changes/ from data/vendor-changes/*.json.

Feed-shaped: each JSON file is one entry. Does not touch build_directory.py
or /fi/ pages. Re-run after adding an entry file.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = "20261118vendor"
NOTICE = "https://banno.com/statements/2025-07-31-retiring-netteller-2027/"


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


def render_entry(d: dict) -> str:
    eid = e(d["id"])
    title = e(d["notice_title"])
    url = e(d["notice_url"])
    notice_date = d["notice_date"]
    effective = d.get("effective_date")
    publisher = e(d.get("publisher") or "")
    parts = [f'<article class="vc-entry" id="{eid}">', "<header>"]
    parts.append(
        f'<p class="vc-meta"><time datetime="{e(notice_date)}">Notice dated {e(fmt_long(notice_date))}</time>'
        + (f' · <span>{publisher}</span>' if publisher else "")
        + "</p>"
    )
    parts.append(f"<h2>{title}</h2>")
    parts.append("</header>")
    # Body is written to stay close to the public notice without implying a core.
    parts.append(
        "<p>On July 31, 2025, Banno published a statement that Jack Henry will retire "
        "NetTeller Online Banking, NetTeller Small Business Cash Management, and "
        "NetTeller Commercial Cash Management on "
        f'<time datetime="{e(effective)}">{e(fmt_long(effective))}</time>. '
        "On that date, the notice says, access to NetTeller front-end services will be "
        "turned off and existing NetTeller and NetTeller Cash Management contracts will "
        f'not be renewed. <a href="{url}" rel="noopener">Read the original notice</a>.</p>'
    )
    parts.append(
        "<p>The institutions below showed a NetTeller login host on a "
        "<strong>login-page scan dated November 17, 2026</strong>. They may be affected. "
        "A NetTeller login is not evidence of which core system an institution uses, "
        "and this list does not identify anyone’s core.</p>"
    )
    for g in d.get("groups") or []:
        fis = g.get("fis") or []
        parts.append(f'<section id="{e(d["id"])}-{e(g["id"])}">')
        parts.append(f'<h3>{e(g["title"])} ({len(fis)})</h3>')
        if g.get("intro"):
            parts.append(f'<p>{e(g["intro"])}</p>')
        parts.append('<ul class="fi-list">')
        for fi in fis:
            href = e(fi["path"])
            charter = "Credit union" if fi.get("charter") == "cu" else "Bank"
            sub = f'{e(fi["city"])}, {e(fi["state"])} · {charter} · {e(fi["scan_label"])}'
            parts.append(
                f'<li><a href="{href}"><span class="nm">{e(fi["name"])}</span>'
                f'<span class="sub">{sub}</span></a></li>'
            )
        parts.append("</ul></section>")
    parts.append("</article>")
    return "\n".join(parts)


def write_html(entries):
    articles = "\n".join(render_entry(d) for d in entries) or "<p>No entries yet.</p>"
    n = len(entries)
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
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
  <nav><a href="/#board">Board</a><a class="nav-dir" href="/fi/">Directory</a><a class="nav-opt" href="/about.html">About</a><a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener" aria-label="Follow @FISignalWeekly on X"><svg class="x-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span class="fx-text">Follow @FISignalWeekly</span></a></nav>
</div></header>
<main class="wrap vc">
  <header class="hero">
    <h1>Vendor platform changes</h1>
    <p>Public notices about digital banking platforms, with institutions that may be affected based on a login-page scan. This is not a list of core systems. New entries will be added as public notices appear.</p>
  </header>
  {articles}
</main>
<footer><div class="wrap">FI Signal Weekly · Login-page scan evidence and public vendor notices only. Verify before acting. Not affiliated with any regulator or vendor. · <a href="/">Board</a> · <a href="/fi/">Directory</a> · <a href="/territory/">Territory</a> · <a href="/vendor-changes/">Vendor changes</a> · <a href="/about.html">About</a> · <a href="/#subscribe">Friday digest</a> · <a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener">Follow @FISignalWeekly</a></div></footer>
</body></html>
"""
    out = ROOT / "vendor-changes/index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({n} entr{'y' if n==1 else 'ies'})")


if __name__ == "__main__":
    write_html(load_entries())
