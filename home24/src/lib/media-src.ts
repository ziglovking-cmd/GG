import type { Video } from "@/lib/catalog";
import { isCoffeeVideo } from "@/lib/video-kind";

export function isTourVideo(v: Video) {
  if (isCoffeeVideo(v)) return false;
  if (v.disk === "home24") return true;
  const blob = `${v.title} ${v.name}`.normalize("NFC").toLowerCase();
  return /видео о квартир|как выглядит квартир|обзор квартир|осмотр/.test(blob);
}

export function pickTourVideo(videos: Video[]): Video | undefined {
  const tours = videos.filter(isTourVideo);
  if (tours.length) return tours[0];
  return videos.find((v) => !isCoffeeVideo(v));
}

export function playableSrc(
  v: { path?: string; disk?: string; url?: string; name?: string },
  tick = 0
) {
  const file = (v.path || v.url || v.name || "").split("?")[0].split("/").pop() || "";
  if (v.disk === "local" && file) return `/shared/${file}`;
  if (v.disk === "home24") {
    const name = file || (v.path || "").replace(/^\//, "");
    if (!name) return "";
    return `/api/media?path=${encodeURIComponent(`/${name.replace(/^\//, "")}`)}&disk=home24&t=${tick}`;
  }
  const fromSite = (v.url || "").match(/\/api\/media\/([^/?]+\.(?:mp4|mov|m4v|webm))/i);
  if (fromSite) {
    return `/api/media?path=${encodeURIComponent(`/${fromSite[1]}`)}&disk=home24&t=${tick}`;
  }
  if (v.path?.startsWith("/")) {
    const disk = v.disk ? `&disk=${encodeURIComponent(v.disk)}` : "";
    return `/api/media?path=${encodeURIComponent(v.path)}${disk}&t=${tick}`;
  }
  return "";
}
