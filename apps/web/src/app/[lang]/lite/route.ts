import type { NextRequest } from "next/server";

import { isLocale } from "@/lib/i18n";
import { LITE_COOKIE, LITE_MAX_AGE_SECONDS, liteChoice, liteReturnPath } from "@/lib/lite";
import { safeNext } from "@/lib/safe-next";

// The lite-mode switch (C-12; D-107): a plain link, so it works before any
// script loads. It remembers the choice and goes back to the page it came
// from (the path of the Referer, or `next`), which must be a page on this
// site (SEC-1: never off the site). The way back is a relative address, so it
// never depends on the Host header.
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, { params }: RouteContext<"/[lang]/lite">) {
  const { lang } = await params;
  const home = isLocale(lang) ? `/${lang}` : "/";
  const wanted = request.nextUrl.searchParams.get("next") ?? liteReturnPath(request.headers.get("referer"));
  const back = safeNext(wanted, home);
  const headers = new Headers({ Location: back, "Cache-Control": "no-store" });
  const choice = liteChoice(request.nextUrl.searchParams.get("on"));
  if (choice) {
    headers.append("Set-Cookie", `${LITE_COOKIE}=${choice}; Path=/; Max-Age=${LITE_MAX_AGE_SECONDS}; SameSite=Lax`);
  }
  return new Response(null, { status: 303, headers });
}
