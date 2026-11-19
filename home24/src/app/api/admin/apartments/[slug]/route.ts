import { NextRequest, NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/admin-request";
import { apartments, getApartment } from "@/lib/catalog";
import { applyLiveApartment, readStore, writeStore, type AptOverlay } from "@/lib/live-data";

const FIELDS = [
  "name",
  "address",
  "metro",
  "coords",
  "wifi",
  "how",
  "parking",
  "checkin",
  "checkout",
  "rules",
  "district",
  "contacts",
  "ready",
] as const;

export async function GET(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { error } = requireAdmin(req);
  if (error) return error;
  const { slug } = await ctx.params;
  const apt = getApartment(slug);
  if (!apt) return NextResponse.json({ error: "not found" }, { status: 404 });
  return NextResponse.json(applyLiveApartment(apt));
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { error } = requireAdmin(req);
  if (error) return error;
  const { slug } = await ctx.params;
  if (!apartments.some((a) => a.slug === slug)) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const body = (await req.json()) as Record<string, unknown>;
  const patch: AptOverlay = {};
  for (const key of FIELDS) {
    if (!(key in body)) continue;
    if (key === "ready") patch.ready = Boolean(body.ready);
    else if (typeof body[key] === "string") patch[key] = body[key] as string;
  }
  const store = readStore();
  store.overlays[slug] = { ...(store.overlays[slug] || {}), ...patch };
  writeStore(store);
  revalidatePath("/g", "layout");
  const apt = getApartment(slug);
  return NextResponse.json(apt ? applyLiveApartment(apt) : { ok: true });
}
