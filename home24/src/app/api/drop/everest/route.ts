import { NextRequest, NextResponse } from "next/server";
import { randomBytes } from "crypto";
import fs from "fs";
import path from "path";
import { revalidatePath } from "next/cache";
import { addLibraryVideo, sharedVideoDir } from "@/lib/live-data";
import { everestTitleFromFilename } from "@/lib/everest-drop";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 600;

function extOf(name: string) {
  return path.extname(name).toLowerCase() || "";
}

async function writeWebStream(body: ReadableStream<Uint8Array>, abs: string) {
  const reader = body.getReader();
  const ws = fs.createWriteStream(abs);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value?.length) continue;
      const chunk = Buffer.from(value);
      if (!ws.write(chunk)) {
        await new Promise<void>((resolve, reject) => {
          ws.once("drain", resolve);
          ws.once("error", reject);
        });
      }
    }
    await new Promise<void>((resolve, reject) => {
      ws.end(() => resolve());
      ws.once("error", reject);
    });
  } catch (err) {
    ws.destroy();
    try {
      fs.unlinkSync(abs);
    } catch {
      /* ignore */
    }
    throw err;
  }
}

export async function POST(req: NextRequest) {
  try {
    const original =
      decodeURIComponent(req.nextUrl.searchParams.get("name") || req.headers.get("x-filename") || "") ||
      "video.mov";
    const ext = extOf(original) || ".mp4";
    const isVideo = [".mp4", ".mov", ".m4v", ".webm"].includes(ext);
    const isPhoto = [".jpg", ".jpeg", ".png", ".webp", ".heic"].includes(ext);
    if (!isVideo && !isPhoto) {
      return NextResponse.json({ error: "нужно видео или фото" }, { status: 400 });
    }
    const body = req.body;
    if (!body) {
      return NextResponse.json({ error: "пустой файл" }, { status: 400 });
    }
    const id = randomBytes(6).toString("hex");
    const filename = `${id}${ext}`;
    const dir = sharedVideoDir();
    fs.mkdirSync(dir, { recursive: true });
    const abs = path.join(dir, filename);
    await writeWebStream(body, abs);
    const size = fs.statSync(abs).size;
    if (!size) {
      fs.unlinkSync(abs);
      return NextResponse.json({ error: "файл не записался — место на диске или обрыв сети" }, { status: 500 });
    }
    const title = everestTitleFromFilename(original);
    addLibraryVideo({
      id,
      title,
      filename,
      createdAt: new Date().toISOString(),
      slugs: ["everest"],
      skipIfHas: false,
    });
    revalidatePath("/g", "layout");
    return NextResponse.json({ ok: true, title, original, filename, size });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "не ушло";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
