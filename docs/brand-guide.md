# FI Signal Weekly — Brand & Voice Guide

One page. Every agent and contributor that writes for the site, the Friday digest or @FISignalWeekly follows it.

## Colors

Navy and pulse green are sampled from the X avatar and header (`img/mark-512.png`, `img/og-image.png`). The site defines all of these as CSS variables in `css/style.css`.

| Role | Hex | Use |
|---|---|---|
| Navy 900 | `#000F26` | Header, footer, share image background (X header background) |
| Navy 800 | `#031940` | Mark tile background (X avatar background), button hover |
| Navy 700 | `#0A2A5C` | Buttons, card accent bar, feedback panel rule |
| Pulse green | `#40E737` | The pulse line, "Weekly" in the wordmark, links on navy, row highlight. **Only on navy backgrounds.** |
| Green (on light) | `#15803D` | "New" tag (same ET calendar day a row is published; drops off at midnight ET) and any green text on white or light backgrounds |
| On-dark text | `#FFFFFF` | Text on navy |
| On-dark muted | `#A8BACC` | Secondary text and nav links on navy |
| Ink | `#0B1B33` | Body text on light backgrounds |
| Muted | `#4A5B73` | Secondary text on light backgrounds |
| Link | `#1450B8` | Links on light backgrounds |
| Page background | `#F4F7FB` | Page background |
| Card | `#FFFFFF` | Board cards and panels |
| Line | `#DCE3EE` | Borders |
| Merger / Core / Executive | `#7C3AED` / `#0E7490` / `#B45309` | Signal-type badges (white text) |

Contrast (WCAG AA, 4.5:1 for normal text): white on Navy 900 19.2:1; pulse green on Navy 900 11.6:1; on-dark muted on Navy 900 9.6:1; ink on page background 16.0:1; muted on white 6.9:1; link on white 7.3:1; white on the three badge colors 5.7 / 5.4 / 5.0:1; white on `#15803D` 5.0:1. Pulse green on white is only 1.6:1, so never use it for text on light backgrounds.

## Logo and mark

- **Files:** the FI pulse mark is `img/mark-512.png` (also `mark-192.png`, `mark-96.png`, `mark-64.png`). Favicons: `favicon.ico` (16/32/48), `img/favicon-16.png`, `img/favicon-32.png`, `img/apple-touch-icon.png` (180). Share image: `img/og-image.png` (1200×630). X avatar and header originals: `fisignal-avatar.jpg`, `fisignal-header.jpg`.
- **Wordmark:** "FI Signal **Weekly**": "FI Signal" in white and "Weekly" in pulse green on navy; on light backgrounds, "FI Signal" in ink.
- **Minimum size:** the mark is 16 px for favicons only; 24 px is the smallest in layouts (the site header uses 32 px).
- **Clear space:** keep at least one quarter of the mark's width clear on every side (8 px at 32 px).
- **Don'ts:** don't recolor, stretch, rotate or outline the mark; don't put the pulse green on white; don't add effects or other logos inside its clear space; don't place it on busy photos; don't redraw the "FI" letters or the pulse.

## Voice

- **Plain and factual.** Say what happened, who, and when. No hype, no superlatives, no "huge", "massive" or "game-changer".
- **Never say "exclusive".**
- **Source-first.** Every claim links its public source (regulator notices and data, filings, press releases). If a fact can't be verified from a public source, leave it out. Never guess numbers, dates or names.
- **Results first.** Lead with the event and its date; context and "why it matters for sellers" come after.
- **Short sentences.** One idea per sentence. Cut filler.
- **Every row is fact-checked** before it goes on the board or X. Flagged rows wait for review.

## X post rules

- Under 280 characters, counting every URL as 23.
- Tag only official handles that are verified (the institution's site links the handle, or the profile links the institution's official domain with a matching name). Tag each handle only once per post. Never start a post with `@`. Never invent a handle.
- One or two hashtags.
- Every post gets an image card (`make_card.py`, 1200×675).
- Every post includes a row anchor (`https://fisignalweekly.com/#tNNN`) or the direct public source link.
- The Friday top-5 thread ends with the digest signup link.

## Brand-only

Everything public is FI Signal Weekly: site, digest, X, commits, branches and PR text. Never use the owner's name, likeness or personal accounts. Contact address: fisignal@mail.grokbot.com.
