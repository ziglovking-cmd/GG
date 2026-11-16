export function getAdminToken(): string {
  return process.env.ADMIN_TOKEN?.trim() ?? "";
}

export function requireAdmin(request: Request): boolean {
  const expected = getAdminToken();
  if (!expected) return false;
  const header = request.headers.get("authorization") ?? "";
  const bearer = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  const queryToken = new URL(request.url).searchParams.get("token") ?? "";
  const cookie = parseCookie(request.headers.get("cookie") ?? "").admin_token;
  return bearer === expected || queryToken === expected || cookie === expected;
}

export function isTelegramAdmin(telegramId: number): boolean {
  const raw = process.env.ADMIN_TELEGRAM_IDS?.trim() ?? "";
  if (!raw) return false;
  return raw
    .split(",")
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n))
    .includes(telegramId);
}

export function parseCookie(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of raw.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (!k) continue;
    out[k] = decodeURIComponent(rest.join("=") || "");
  }
  return out;
}

export function sessionSecret(): string {
  return (
    process.env.SESSION_SECRET?.trim() ||
    process.env.ADMIN_TOKEN?.trim() ||
    "dev-only-session-secret"
  );
}
