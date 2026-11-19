import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { resolveSlug } from "@/lib/catalog";
import { CANONICAL_ORIGIN } from "@/lib/site";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const m = pathname.match(/^\/g\/([^/]+)(\/.*)?$/);
  if (!m) return NextResponse.next();

  const raw = m[1];
  const rest = (m[2] || "").replace(/\/+$/, "");
  const resolved = resolveSlug(raw);
  if (!resolved) return NextResponse.next();

  const nextPath = `/g/${resolved}${rest}`;
  const current = pathname.replace(/\/+$/, "") || pathname;
  if (nextPath === current || resolved === raw.toLowerCase().replace(/\s+/g, "-")) {
    return NextResponse.next();
  }
  return NextResponse.redirect(`${CANONICAL_ORIGIN}${nextPath}`);
}

export const config = {
  matcher: "/g/:path*",
};
