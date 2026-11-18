// Per-partner API keys. A key looks like fisw_<key_id>_<secret>. Only SHA-256(key) is stored, in KV under
// "key:<key_id>". Keys are issued and revoked with scripts/keys.mjs, never through a public endpoint.

export type KeyRecord = { hash: string; label: string; created_at: string; revoked_at?: string | null; rate_per_min?: number };
export type Principal = { keyId: string; label: string; ratePerMin?: number };

const KEY_RE = /^fisw_([0-9a-f]{8})_([A-Za-z0-9_-]{40,64})$/;

export async function sha256Hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function sameHex(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let x = 0;
  for (let i = 0; i < a.length; i++) x |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return x === 0;
}

export function bearer(req: Request): string | null {
  const h = req.headers.get("Authorization") ?? "";
  const m = /^Bearer\s+(\S+)\s*$/i.exec(h);
  return m ? m[1] : null;
}

/** The key's principal, or null if the key is malformed, unknown, revoked or does not match its stored hash. */
export async function verifyKey(key: string | null, kv: KVNamespace): Promise<Principal | null> {
  if (!key) return null;
  const m = KEY_RE.exec(key);
  if (!m) return null;
  const rec = await kv.get<KeyRecord>(`key:${m[1]}`, { type: "json", cacheTtl: 60 });
  if (!rec || rec.revoked_at) return null;
  if (!sameHex(await sha256Hex(key), rec.hash)) return null;
  return { keyId: m[1], label: rec.label, ratePerMin: rec.rate_per_min };
}
