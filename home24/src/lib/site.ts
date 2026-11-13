/** Canonical guest URL. Phones and messengers need HTTPS — not a raw IP. */
export const CANONICAL_ORIGIN = "https://89-111-184-212.sslip.io";

export function publicOrigin(): string {
  const fromEnv = (process.env.PUBLIC_URL || process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/$/, "");
  if (fromEnv) return fromEnv;
  return CANONICAL_ORIGIN;
}

export function guestUrl(slug: string, path = ""): string {
  const extra = path ? (path.startsWith("/") ? path : `/${path}`) : "";
  return `${publicOrigin()}/g/${slug}${extra}`;
}
