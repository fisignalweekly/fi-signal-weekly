import { createMcpHandler } from "agents/mcp/server";
import bundle from "./generated/bundle.json";
import { Store, type Bundle } from "./data";
import { createServer } from "./server";
import { bearer, verifyKey } from "./auth";

export interface Env {
  KEYS: KVNamespace;
  RATE_LIMITER?: RateLimit;
  ALLOWED_HOSTNAMES?: string;
}

const store = new Store(bundle as unknown as Bundle);
let handler: ReturnType<typeof createMcpHandler> | null = null;
function mcp(env: Env) {
  if (!handler) {
    const extra = (env.ALLOWED_HOSTNAMES ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    handler = createMcpHandler(() => createServer(store), {
      route: "/mcp", corsOptions: false, legacy: "stateless", responseMode: "json",
      ...(extra.length ? { allowedHostnames: extra } : {}),
    });
  }
  return handler;
}

// Fallback limiter (per isolate) when no RATE_LIMITER binding is configured.
const windows = new Map<string, { start: number; n: number }>();
function localLimit(key: string, limit: number): boolean {
  const now = Date.now();
  const w = windows.get(key);
  if (!w || now - w.start >= 60_000) { windows.set(key, { start: now, n: 1 }); return true; }
  return ++w.n <= limit;
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

function describe(body: unknown): { method: string; tool?: string } {
  const one = Array.isArray(body) ? body[0] : body;
  if (!one || typeof one !== "object") return { method: "unknown" };
  const m = String((one as { method?: unknown }).method ?? "response");
  const p = (one as { params?: { name?: unknown } }).params;
  return m === "tools/call" ? { method: m, tool: String(p?.name ?? "") } : { method: m };
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") {
      return json(200, { name: "FI Signal Weekly MCP", endpoint: "/mcp", transport: "streamable-http", auth: "Authorization: Bearer <api key>",
        data_updated: store.b.meta.data_updated, signals: store.b.signals.length });
    }
    if (url.pathname !== "/mcp") return json(404, { error: "not found" });

    const principal = await verifyKey(bearer(request), env.KEYS);
    if (!principal) {
      console.log(JSON.stringify({ event: "mcp_auth_rejected", ts: new Date().toISOString() }));
      return json(401, { error: "missing or invalid API key" }, { "WWW-Authenticate": 'Bearer realm="fi-signal-weekly"' });
    }
    const limit = principal.ratePerMin ?? 60;
    const allowed = env.RATE_LIMITER
      ? (await env.RATE_LIMITER.limit({ key: principal.keyId })).success
      : localLimit(principal.keyId, limit);
    let parsedBody: unknown;
    if (request.method === "POST") {
      try { parsedBody = await request.clone().json(); } catch { return json(400, { error: "invalid JSON body" }); }
    }
    const what = describe(parsedBody);
    const log = (status: number) => console.log(JSON.stringify({ event: "mcp_request", key_id: principal.keyId, label: principal.label,
      method: what.method, tool: what.tool, status, ts: new Date().toISOString() }));
    if (!allowed) { log(429); return json(429, { error: "rate limit exceeded" }, { "Retry-After": "60" }); }

    const res = await mcp(env).fetch(request, {
      authInfo: { token: "redacted", clientId: principal.keyId, scopes: ["read"] },
      parsedBody,
    });
    log(res.status);
    return res;
  },
} satisfies ExportedHandler<Env>;
