# FI Signal Weekly MCP server (source)

Read-only remote MCP server (Cloudflare Worker, Streamable HTTP, Bearer API keys) over the data published on
fisignalweekly.com. Tools: `search_signals`, `get_fi_profile`, `list_new_signals_since`, `get_tech_stack`.
Partner documentation: https://fisignalweekly.com/mcp/

This branch is never merged into the site (GitHub Pages serves the repo as-is).

```sh
cd mcp && npm ci && npm test        # bundle build, published-only tests, unit tests, type-check
npm run dev                          # wrangler dev --local on http://127.0.0.1:8787
```

- `scripts/build_bundle.py` builds `src/generated/bundle.json` from allowlisted published files and fields only
  (`--ref origin/main` reads exactly what is live).
- `wrangler.jsonc` has a placeholder KV namespace id; the deploy step substitutes the real one.
- `test/e2e.mjs` checks a running server with the official MCP client (`MCP_URL`, `MCP_KEY_FILE`).
