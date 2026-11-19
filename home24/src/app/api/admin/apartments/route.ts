import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-request";
import { apartments } from "@/lib/catalog";
import { applyLiveApartment } from "@/lib/live-data";

export async function GET(req: NextRequest) {
  const { id, error } = requireAdmin(req);
  if (error) return error;
  const items = apartments.map((a) => {
    const live = applyLiveApartment(a);
    return {
      slug: live.slug,
      id: live.id,
      name: live.name,
      address: live.address,
      metro: live.metro,
      ready: live.ready,
      videos: live.videos.length,
      wifi: live.wifi.slice(0, 80),
    };
  });
  return NextResponse.json({ admin: id, apartments: items });
}
