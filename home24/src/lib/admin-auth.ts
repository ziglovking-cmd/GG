import { createHmac, timingSafeEqual } from "crypto";

export const ADMIN_COOKIE = "home24_admin";

export function adminIds(): Set<number> {
  const raw = process.env.ADMIN_TELEGRAM_IDS || "2032620613,8228063846";
  return new Set(
    raw
      .split(/[,\s]+/)
      .map((x) => Number(x.trim()))
      .filter((n) => Number.isFinite(n) && n > 0)
  );
}

export function adminSecret() {
  return process.env.ADMIN_SECRET || process.env.TELEGRAM_BOT_TOKEN || "home24-admin-dev";
}

export function adminLogin() {
  return process.env.ADMIN_LOGIN || "home24";
}

export function adminPassword() {
  return process.env.ADMIN_PASSWORD || "Home24_admin";
}

function hmacHex(value: string) {
  return createHmac("sha256", adminSecret()).update(value).digest();
}

export function checkAdminPassword(login: string, password: string) {
  const lOk = timingSafeEqual(hmacHex(`login:${login}`), hmacHex(`login:${adminLogin()}`));
  const pOk = timingSafeEqual(hmacHex(`pass:${password}`), hmacHex(`pass:${adminPassword()}`));
  return lOk && pOk;
}

export function signAdminToken(telegramId: number, days = 14) {
  const exp = Math.floor(Date.now() / 1000) + days * 86400;
  const payload = `${telegramId}.${exp}`;
  const sig = createHmac("sha256", adminSecret()).update(payload).digest("hex");
  return `${payload}.${sig}`;
}

export function verifyAdminToken(token: string | null | undefined): number | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [idRaw, expRaw, sig] = parts;
  const payload = `${idRaw}.${expRaw}`;
  const expect = createHmac("sha256", adminSecret()).update(payload).digest("hex");
  const a = Buffer.from(sig);
  const b = Buffer.from(expect);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  const id = Number(idRaw);
  const exp = Number(expRaw);
  if (!Number.isFinite(id) || !Number.isFinite(exp)) return null;
  if (Date.now() / 1000 > exp) return null;
  if (id === 0) return 0;
  if (!adminIds().has(id)) return null;
  return id;
}
