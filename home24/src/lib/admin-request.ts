import { NextRequest, NextResponse } from "next/server";
import { ADMIN_COOKIE, verifyAdminToken } from "@/lib/admin-auth";

export function adminIdFromRequest(req: NextRequest) {
  return verifyAdminToken(req.cookies.get(ADMIN_COOKIE)?.value);
}

export function requireAdmin(req: NextRequest) {
  const id = adminIdFromRequest(req);
  if (id === null) {
    return { id: null, error: NextResponse.json({ error: "forbidden" }, { status: 403 }) };
  }
  return { id, error: null };
}
