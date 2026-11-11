import { NextRequest, NextResponse } from "next/server";
import { ADMIN_COOKIE, checkAdminPassword, signAdminToken, verifyAdminToken } from "@/lib/admin-auth";

function cookieOpts(req: NextRequest) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 14 * 24 * 3600,
  };
}

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("k") || "";
  const id = verifyAdminToken(token);
  if (id === null) {
    return NextResponse.redirect(new URL("/admin?err=1", req.url));
  }
  const res = NextResponse.redirect(new URL("/admin", req.url));
  res.cookies.set(ADMIN_COOKIE, token, cookieOpts(req));
  return res;
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { login?: string; password?: string };
  if (!checkAdminPassword(String(body.login || ""), String(body.password || ""))) {
    return NextResponse.json({ error: "Неверный логин или пароль" }, { status: 401 });
  }
  const token = signAdminToken(0);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(ADMIN_COOKIE, token, cookieOpts(req));
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(ADMIN_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return res;
}
