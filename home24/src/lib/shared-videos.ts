import { unstable_cache } from "next/cache";
import { connection } from "next/server";
import fs from "fs";
import path from "path";
import { getApartment, type Apartment, type Faq, type Video } from "@/lib/catalog";
import { DISK_UA, PUBLIC_DISKS, type DiskId } from "@/lib/disks";
import { isCoffeeVideo } from "@/lib/video-kind";
import fallback from "../../data/shared-videos.json";

export { isCoffeeVideo };

const COFFEE_FAQ: Faq = {
  q: "Как пользоваться кофемашиной?",
  a: "Короткое видео — во вкладке «Видео пользования техникой и не только». Капсулы или зерно обычно стоят рядом с машиной. После себя промойте рожок. Если машины нет или она не включается — напишите персональному менеджеру с 09:00 до 00:00.",
};

type DiskItem = { name: string; path: string; type: string };

function nfcLow(s: string) {
  return s.normalize("NFC").toLowerCase();
}

function publicPath(raw: string) {
  let p = raw.replace(/^disk:/, "");
  if (!p.startsWith("/")) p = `/${p}`;
  return p;
}

async function listFolder(disk: DiskId, path: string): Promise<DiskItem[]> {
  const url =
    "https://cloud-api.yandex.net/v1/disk/public/resources?" +
    new URLSearchParams({ public_key: PUBLIC_DISKS[disk], path, limit: "100" });
  const res = await fetch(url, { cache: "no-store", headers: { "User-Agent": DISK_UA } });
  if (!res.ok) return [];
  const data = (await res.json()) as { _embedded?: { items?: { name: string; path: string; type: string }[] } };
  return (data._embedded?.items || []).map((it) => ({
    name: it.name,
    path: publicPath(it.path || `/${it.name}`),
    type: it.type,
  }));
}

function toCoffeeVideo(item: DiskItem, disk: DiskId): Video {
  return {
    title: "Как пользоваться кофемашиной",
    name: item.name,
    url: `${PUBLIC_DISKS[disk]}?path=${encodeURIComponent(item.path)}`,
    path: item.path,
    disk,
    folderUrl: PUBLIC_DISKS[disk],
  };
}

function localCoffee(): Video[] {
  const dirs = [process.env.SHARED_DIR, "/opt/home24/shared", path.join(process.cwd(), "public", "shared")].filter(
    (d): d is string => Boolean(d)
  );
  for (const dir of dirs) {
    if (!fs.existsSync(dir)) continue;
    for (const name of fs.readdirSync(dir)) {
      if (!/\.(mov|mp4|m4v)$/i.test(name)) continue;
      if (!isCoffeeVideo({ name }) && !/^coffee-machine\./i.test(name)) continue;
      return [
        {
          title: "Как пользоваться кофемашиной",
          name,
          url: `/shared/${name}`,
          path: `/shared/${name}`,
          disk: "local",
          folderUrl: "",
        },
      ];
    }
  }
  return [];
}

async function discoverCoffeeFromDisk(): Promise<Video[]> {
  const scans: { disk: DiskId; path: string }[] = [
    { disk: "lunar", path: "/" },
    { disk: "main", path: "/" },
    { disk: "main", path: "/Видео материал " },
    { disk: "main", path: "/Видео материал /Общее" },
    { disk: "main", path: "/Видео материал /Общее/" },
  ];
  for (const scan of scans) {
    const items = await listFolder(scan.disk, scan.path);
    const file = items.find((it) => it.type === "file" && isCoffeeVideo(it));
    if (file) return [toCoffeeVideo(file, scan.disk)];
    const sub = items.find((it) => it.type === "dir" && nfcLow(it.name).includes("общее"));
    if (sub) {
      const nested = await listFolder(scan.disk, sub.path);
      const nestedFile = nested.find((it) => it.type === "file" && isCoffeeVideo(it));
      if (nestedFile) return [toCoffeeVideo(nestedFile, scan.disk)];
    }
  }
  return [];
}

const loadDiskSharedVideos = unstable_cache(
  async () => {
    const live = await discoverCoffeeFromDisk();
    if (live.length) return live;
    const baked = (fallback as { videos?: Video[] }).videos || [];
    return baked.filter(isCoffeeVideo);
  },
  ["shared-coffee-videos-disk"],
  { revalidate: 120 }
);

export async function loadSharedVideos() {
  const local = localCoffee();
  if (local.length) return local;
  return loadDiskSharedVideos();
}

export function mergeSharedVideos(apt: Apartment, shared: Video[]): Apartment {
  if (!apt.ready) return apt;
  const coffee = shared.find((v) => isCoffeeVideo(v) && v.disk !== "local" && v.disk !== "home24");
  if (!coffee) return apt;
  if (apt.videos.some(isCoffeeVideo)) return apt;
  const faq = apt.faq.some(isCoffeeVideo)
    ? apt.faq
    : [...apt.faq, { ...COFFEE_FAQ }];
  return { ...apt, videos: [...apt.videos, coffee], faq };
}

function titleFromFilename(name: string) {
  const base = name.replace(/\.[^.]+$/i, "").replace(/[_-]+/g, " ").trim();
  const low = nfcLow(base);
  if (/балкон/.test(low) && /штор/.test(low)) return "Как работают шторы на балконе";
  if (/ванн|душ/.test(low)) return "Как пользоваться ванной";
  if (/штор/.test(low)) return "Как работают шторы";
  if (/телевиз|\btv\b/.test(low)) return "Как пользоваться телевизором";
  if (/кондиц|сплит/.test(low)) return "Как пользоваться кондиционером";
  return base || name;
}

async function mergeDiskFolderVideos(apt: Apartment): Promise<Apartment> {
  if (!apt.diskFolder) return apt;
  const items = await listFolder("main", apt.diskFolder);
  const have = new Set(apt.videos.map((v) => nfcLow(v.name)));
  const added: Video[] = [];
  for (const it of items) {
    if (it.type !== "file") continue;
    if (!/\.(mp4|mov|m4v|webm)$/i.test(it.name)) continue;
    if (have.has(nfcLow(it.name))) continue;
    have.add(nfcLow(it.name));
    added.push({
      title: titleFromFilename(it.name),
      name: it.name,
      url: `${PUBLIC_DISKS.main}?path=${encodeURIComponent(it.path)}`,
      path: it.path,
      disk: "main",
      folderUrl: apt.diskUrl || PUBLIC_DISKS.main,
    });
  }
  if (!added.length) return apt;
  return { ...apt, videos: [...apt.videos, ...added] };
}

function allowedGuestVideos(apt: Apartment): Apartment {
  return apt;
}

export async function getGuestApartment(slug: string) {
  await connection();
  const apt = getApartment(slug);
  if (!apt) return undefined;
  const { applyLiveApartment } = await import("@/lib/live-data");
  const live = applyLiveApartment(apt);
  const withFolder = await mergeDiskFolderVideos(live);
  const withDiskCoffee = mergeSharedVideos(withFolder, await loadDiskSharedVideos());
  return allowedGuestVideos(withDiskCoffee);
}
