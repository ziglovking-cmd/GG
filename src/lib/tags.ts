export function normalizeTag(raw: string): string | null {
  const cleaned = raw.trim().toUpperCase().replace(/\s+/g, "");
  if (!cleaned) return null;
  const withHash = cleaned.startsWith("#") ? cleaned : `#${cleaned}`;
  if (!/^#[0-9A-Z]{3,15}$/.test(withHash)) return null;
  return withHash;
}
