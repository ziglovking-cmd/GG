import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-request";

export async function GET(req: NextRequest) {
  const { id, error } = requireAdmin(req);
  if (error) return error;
  return NextResponse.json({ id });
}
