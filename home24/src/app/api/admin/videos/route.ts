import { NextRequest, NextResponse } from "next/server";
import { randomBytes } from "crypto";
import fs from "fs";
import path from "path";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/admin-request";
import { apartments } from "@/lib/catalog";
import { readStore, sharedVideoDir, writeStore, type LibraryVideo } from "@/lib/live-data";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

function copyToPublic(abs: string, filename: string) {
  try {
    const destDir = path.join(process.cwd(), "public", "shared");
    fs.mkdirSync(destDir, { recursive: true });
    fs.copyFileSync(abs, path.join(destDir, filename));
  } catch {
    /* optional */
  }
}

export async function GET(req: NextRequest) {
  const { error } = requireAdmin(req);
  if (error) return error;
  return NextResponse.json({ videos: readStore().videos });
}

export async function POST(req: NextRequest) {
  const { error } = requireAdmin(req);
  if (error) return error;
  const form = await req.formData();
  const file = form.get("file");
  const title = String(form.get("title") || "").trim();
  const scope = String(form.get("scope") || "all");
  const slugsRaw = String(form.get("slugs") || "");
  const skipIfHas = String(form.get("skipIfHas") || "1") !== "0";
  if (!(file instanceof File) || !file.size) {
    return NextResponse.json({ error: "нужен файл" }, { status: 400 });
  }
  if (!title) {
    return NextResponse.json({ error: "нужен заголовок" }, { status: 400 });
  }
  const original = file.name || "video.mp4";
  const ext = path.extname(original).toLowerCase() || ".mp4";
  if (![".mp4", ".mov", ".m4v", ".webm"].includes(ext)) {
    return NextResponse.json({ error: "только видео mp4/mov/m4v" }, { status: 400 });
  }
  const id = randomBytes(6).toString("hex");
  const filename = `${id}${ext}`;
  const dir = sharedVideoDir();
  const abs = path.join(dir, filename);
  const { Readable } = await import("node:stream");
  const { pipeline } = await import("node:stream/promises");
  await pipeline(Readable.fromWeb(file.stream() as never), fs.createWriteStream(abs));
  const maxFaststart = 80 * 1024 * 1024;
  if ([".mp4", ".m4v", ".mov"].includes(ext) && fs.statSync(abs).size <= maxFaststart) {
    const { faststartFile } = await import("@/lib/mp4-faststart");
    faststartFile(abs);
  }
  copyToPublic(abs, filename);

  let slugs: LibraryVideo["slugs"] = "all";
  if (scope !== "all") {
    const wanted = slugsRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const known = new Set(apartments.map((a) => a.slug));
    slugs = wanted.filter((s) => known.has(s));
    if (!slugs.length) {
      return NextResponse.json({ error: "выберите квартиры" }, { status: 400 });
    }
  }
  const item: LibraryVideo = {
    id,
    title,
    filename,
    createdAt: new Date().toISOString(),
    slugs,
    skipIfHas,
  };
  const store = readStore();
  store.videos.unshift(item);
  writeStore(store);
  revalidatePath("/g", "layout");
  return NextResponse.json({ ok: true, video: item });
}
