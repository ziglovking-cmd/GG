import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { DISK_UA as UA, PUBLIC_DISKS as DISKS } from "@/lib/disks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

function sharedDirs() {
  return [process.env.SHARED_DIR, "/opt/home24/shared", path.join(process.cwd(), "public", "shared")].filter(
    (d): d is string => Boolean(d)
  );
}

function findLocalFile(filePath: string) {
  const name = path.basename(filePath);
  if (!name || name.includes("..") || name.includes("/") || name.includes("\\")) return null;
  for (const dir of sharedDirs()) {
    const full = path.join(dir, name);
    if (fs.existsSync(full) && fs.statSync(full).isFile()) return full;
  }
  return null;
}

function localVideoResponse(file: string, rangeHeader: string | null) {
  const stat = fs.statSync(file);
  const ext = file.toLowerCase();
  const type = ext.endsWith(".mov") ? "video/quicktime" : "video/mp4";
  const headers = new Headers();
  headers.set("Content-Type", type);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Content-Disposition", "inline");
  headers.set("Cache-Control", "public, max-age=3600");
  headers.set("Access-Control-Allow-Origin", "*");
  let start = 0;
  let end = stat.size - 1;
  let status = 200;
  if (rangeHeader) {
    const m = rangeHeader.match(/bytes=(\d*)-(\d*)/);
    if (m) {
      start = m[1] ? Number(m[1]) : 0;
      end = m[2] ? Number(m[2]) : stat.size - 1;
      if (start > end || start >= stat.size) {
        return NextResponse.json({ error: "range" }, { status: 416 });
      }
      status = 206;
      headers.set("Content-Range", `bytes ${start}-${end}/${stat.size}`);
    }
  }
  headers.set("Content-Length", String(end - start + 1));
  const len = end - start + 1;
  const chunk = Buffer.alloc(len);
  const fd = fs.openSync(file, "r");
  try {
    fs.readSync(fd, chunk, 0, len, start);
  } finally {
    fs.closeSync(fd);
  }
  return new NextResponse(chunk, { status, headers });
}

function resolveDisk(raw: string | null): string | null {
  if (!raw) return DISKS.main;
  const key = raw.trim();
  if (key === "local") return "local";
  const map = DISKS as Record<string, string>;
  if (map[key]) return map[key];
  for (const url of Object.values(DISKS)) {
    if (key === url || url.endsWith(key) || key.includes(url.replace("https://disk.yandex.ru/d/", ""))) {
      return url;
    }
  }
  return null;
}

async function downloadHref(publicKey: string, path: string): Promise<string | null> {
  const url =
    "https://cloud-api.yandex.net/v1/disk/public/resources/download?" +
    new URLSearchParams({ public_key: publicKey, path });
  const res = await fetch(url, { cache: "no-store", headers: { "User-Agent": UA } });
  if (!res.ok) return null;
  const data = (await res.json()) as { href?: string };
  return data.href ?? null;
}

function passthroughHeaders(upstream: Response) {
  const headers = new Headers();
  const type = upstream.headers.get("content-type") || "video/mp4";
  headers.set("Content-Type", type.includes("video") || type.includes("octet") ? type : "video/mp4");
  const length = upstream.headers.get("content-length");
  if (length) headers.set("Content-Length", length);
  const range = upstream.headers.get("content-range");
  if (range) headers.set("Content-Range", range);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Content-Disposition", "inline");
  headers.set("Cache-Control", "public, max-age=3600");
  headers.set("Access-Control-Allow-Origin", "*");
  return headers;
}

export async function HEAD(req: NextRequest) {
  const url = req.nextUrl.clone();
  const headers = new Headers(req.headers);
  if (!headers.get("range")) headers.set("range", "bytes=0-0");
  const probe = await GET(new NextRequest(url, { headers }));
  return new NextResponse(null, { status: probe.status === 206 ? 200 : probe.status, headers: probe.headers });
}

export async function GET(req: NextRequest) {
  try {
    const filePath = req.nextUrl.searchParams.get("path");
    if (!filePath || !filePath.startsWith("/")) {
      return NextResponse.json({ error: "bad path" }, { status: 400 });
    }
    const disk = req.nextUrl.searchParams.get("disk");
    if (disk === "local") {
      const file = findLocalFile(filePath);
      if (!file) return NextResponse.json({ error: "file not found" }, { status: 404 });
      return localVideoResponse(file, req.headers.get("range"));
    }
    if (disk === "home24") {
      const name = path.basename(filePath);
      if (!/^[A-Za-z0-9._-]+\.(mp4|mov|m4v|webm)$/i.test(name)) {
        return NextResponse.json({ error: "bad path" }, { status: 400 });
      }
      const range = req.headers.get("range");
      const upstream = await fetch(`https://home24.msk.ru/api/media/${name}`, {
        cache: "no-store",
        headers: {
          "User-Agent": UA,
          Referer: "https://home24.msk.ru/",
          ...(range ? { Range: range } : {}),
        },
      });
      if (!upstream.ok && upstream.status !== 206) {
        return NextResponse.json({ error: "upstream" }, { status: 502 });
      }
      const headers = passthroughHeaders(upstream);
      const ext = name.toLowerCase();
      if (ext.endsWith(".mp4")) headers.set("Content-Type", "video/mp4");
      if (ext.endsWith(".mov")) headers.set("Content-Type", "video/quicktime");
      return new NextResponse(upstream.body, { status: upstream.status, headers });
    }
    const publicKey = resolveDisk(disk);
    if (!publicKey || publicKey === "local") {
      return NextResponse.json({ error: "bad disk" }, { status: 400 });
    }

    const href = await downloadHref(publicKey, filePath);
    if (!href) {
      return NextResponse.json({ error: "file not found" }, { status: 404 });
    }

    const range = req.headers.get("range");
    const ext = filePath.toLowerCase();
    const upstream = await fetch(href, {
      cache: "no-store",
      headers: {
        "User-Agent": UA,
        ...(range ? { Range: range } : {}),
      },
    });

    if (!upstream.ok && upstream.status !== 206) {
      return NextResponse.json({ error: "upstream" }, { status: 502 });
    }

    const headers = passthroughHeaders(upstream);
    if (ext.endsWith(".mp4")) headers.set("Content-Type", "video/mp4");
    if (ext.endsWith(".mov")) headers.set("Content-Type", "video/quicktime");

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "media failed" }, { status: 502 });
  }
}
