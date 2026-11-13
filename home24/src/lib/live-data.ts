import fs from "fs";
import path from "path";
import type { Apartment, Video } from "@/lib/catalog";

export type AptOverlay = Partial<
  Pick<
    Apartment,
    | "name"
    | "address"
    | "metro"
    | "coords"
    | "wifi"
    | "how"
    | "parking"
    | "checkin"
    | "checkout"
    | "rules"
    | "district"
    | "contacts"
    | "ready"
  >
>;

export type LibraryVideo = {
  id: string;
  title: string;
  filename: string;
  createdAt: string;
  slugs: string[] | "all";
  skipIfHas: boolean;
};

type Store = {
  overlays: Record<string, AptOverlay>;
  videos: LibraryVideo[];
};

function roots() {
  const list = [process.env.ADMIN_DATA_DIR, "/opt/home24/admin", path.join(process.cwd(), "data", "admin")].filter(
    (d): d is string => Boolean(d)
  );
  return list;
}

export function adminDataDir() {
  for (const dir of roots()) {
    try {
      fs.mkdirSync(dir, { recursive: true });
      return dir;
    } catch {
      /* try next */
    }
  }
  const fallback = path.join(process.cwd(), "data", "admin");
  fs.mkdirSync(fallback, { recursive: true });
  return fallback;
}

export function sharedVideoDir() {
  const list = [process.env.SHARED_DIR, "/opt/home24/shared", path.join(process.cwd(), "public", "shared")].filter(
    (d): d is string => Boolean(d)
  );
  for (const dir of list) {
    try {
      fs.mkdirSync(dir, { recursive: true });
      return dir;
    } catch {
      /* next */
    }
  }
  const fallback = path.join(process.cwd(), "public", "shared");
  fs.mkdirSync(fallback, { recursive: true });
  return fallback;
}

function storePath() {
  return path.join(adminDataDir(), "store.json");
}

export function readStore(): Store {
  try {
    const raw = fs.readFileSync(storePath(), "utf8");
    const data = JSON.parse(raw) as Store;
    return {
      overlays: data.overlays && typeof data.overlays === "object" ? data.overlays : {},
      videos: Array.isArray(data.videos) ? data.videos : [],
    };
  } catch {
    return { overlays: {}, videos: [] };
  }
}

export function writeStore(next: Store) {
  const dir = adminDataDir();
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(storePath(), JSON.stringify(next, null, 2) + "\n", "utf8");
}

export function addLibraryVideo(item: LibraryVideo) {
  const store = readStore();
  store.videos = [item, ...store.videos.filter((v) => v.id !== item.id)];
  writeStore(store);
}

function titleKey(s: string) {
  return s.normalize("NFC").toLowerCase().replace(/\s+/g, " ").trim();
}

export function applyLiveApartment(apt: Apartment): Apartment {
  const store = readStore();
  const overlay = store.overlays[apt.slug] || {};
  const haveTitles = new Set(apt.videos.map((v) => titleKey(v.title)));
  const haveFiles = new Set(apt.videos.map((v) => v.name));
  const extra: Video[] = [];
  for (const v of store.videos) {
    if (v.slugs !== "all" && !v.slugs.includes(apt.slug)) continue;
    if (haveFiles.has(v.filename)) continue;
    if (v.skipIfHas && haveTitles.has(titleKey(v.title))) continue;
    haveTitles.add(titleKey(v.title));
    haveFiles.add(v.filename);
    extra.push({
      title: v.title,
      name: v.filename,
      url: `/shared/${v.filename}`,
      path: `/${v.filename}`,
      disk: "local",
      folderUrl: "",
    });
  }
  return { ...apt, ...overlay, videos: [...apt.videos, ...extra], faq: [...apt.faq] };
}
