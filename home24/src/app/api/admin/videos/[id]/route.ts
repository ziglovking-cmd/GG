import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/admin-request";
import { apartments } from "@/lib/catalog";
import { readStore, sharedVideoDir, writeStore } from "@/lib/live-data";

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { error } = requireAdmin(req);
  if (error) return error;
  const { id } = await ctx.params;
  const store = readStore();
  const item = store.videos.find((v) => v.id === id);
  if (!item) return NextResponse.json({ error: "not found" }, { status: 404 });
  const body = (await req.json()) as { title?: string; scope?: string; slugs?: string[]; skipIfHas?: boolean };
  if (typeof body.title === "string" && body.title.trim()) item.title = body.title.trim();
  if (typeof body.skipIfHas === "boolean") item.skipIfHas = body.skipIfHas;
  if (body.scope === "all") item.slugs = "all";
  if (body.scope === "selected" && Array.isArray(body.slugs)) {
    const known = new Set(apartments.map((a) => a.slug));
    const slugs = body.slugs.filter((s) => known.has(s));
    if (!slugs.length) return NextResponse.json({ error: "выберите квартиры" }, { status: 400 });
    item.slugs = slugs;
  }
  writeStore(store);
  revalidatePath("/g", "layout");
  return NextResponse.json({ video: item });
}

export async function DELETE(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { error } = requireAdmin(req);
  if (error) return error;
  const { id } = await ctx.params;
  const store = readStore();
  const item = store.videos.find((v) => v.id === id);
  if (!item) return NextResponse.json({ error: "not found" }, { status: 404 });
  store.videos = store.videos.filter((v) => v.id !== id);
  writeStore(store);
  try {
    fs.unlinkSync(path.join(sharedVideoDir(), item.filename));
  } catch {
    /* already gone */
  }
  revalidatePath("/g", "layout");
  return NextResponse.json({ ok: true });
}
