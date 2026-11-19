import catalog from "../../data/apartments.json";
import { OLD_SLUG_ALIASES } from "@/lib/aliases";
import { foldSearch } from "@/lib/search";

export type Video = {
  title: string;
  name: string;
  url: string;
  path?: string;
  disk?: string;
  folderUrl: string;
};

export type Photo = {
  title: string;
  src: string;
  alt?: string;
};

export type Faq = {
  q: string;
  a: string;
  video?: string;
};

export type Apartment = {
  id: number;
  slug: string;
  name: string;
  area: string;
  address: string;
  metro: string;
  coords: string;
  ready: boolean;
  wifi: string;
  how: string;
  parking: string;
  parkingHint?: string;
  checkin: string;
  rules: string;
  checkout: string;
  district: string;
  review: string;
  contacts: string;
  diskUrl: string;
  diskFolder: string;
  videos: Video[];
  photos?: Photo[];
  faq: Faq[];
  guestMessage: string;
  mapsOrgUrl?: string;
};

export const company = catalog.company;
export const phone = catalog.phone;
export const site = catalog.site;
export const yandexPublic = catalog.yandexPublic;
export { foldSearch, matchesSearch } from "@/lib/search";

export const apartments = catalog.apartments as Apartment[];

export function findApartments(query: string): Apartment[] {
  const q = foldSearch(query);
  if (!q) return apartments;
  const tokens = query
    .trim()
    .split(/\s+/)
    .map(foldSearch)
    .filter(Boolean);

  const hit = (a: Apartment) => {
    const blob = foldSearch([a.name, a.slug, a.area, a.address, a.metro, String(a.id)].join(" "));
    const aliases = Object.entries(OLD_SLUG_ALIASES)
      .filter(([, to]) => to === a.slug)
      .map(([from]) => foldSearch(from))
      .join("");
    const hay = blob + aliases;
    if (hay.includes(q)) return true;
    if (tokens.length > 1 && tokens.every((t) => hay.includes(t))) return true;
    return false;
  };

  const exact = apartments.filter(hit);
  if (exact.length) return exact;
  if (tokens.length > 1) {
    const any = apartments.filter((a) => {
      const blob = foldSearch([a.name, a.slug, a.area, a.address, a.metro, String(a.id)].join(" "));
      return tokens.some((t) => blob.includes(t));
    });
    if (any.length) return any;
  }
  return [];
}

export function resolveSlug(raw: string): string | null {
  const decoded = decodeURIComponent(raw || "").trim();
  const key = decoded.toLowerCase().replace(/\s+/g, "-");
  if (!key) return null;
  if (OLD_SLUG_ALIASES[key]) return OLD_SLUG_ALIASES[key];
  const bySlug = apartments.find((a) => a.slug === key);
  if (bySlug) return bySlug.slug;
  const byName = apartments.find((a) => foldSearch(a.name) === foldSearch(decoded));
  if (byName) return byName.slug;
  return null;
}

export function getApartment(slug: string) {
  const real = resolveSlug(slug);
  if (!real) return undefined;
  return apartments.find((a) => a.slug === real);
}
