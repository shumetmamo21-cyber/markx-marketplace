import { NextResponse, type NextRequest } from "next/server";

import { DEFAULT_LOCALE, LOCALE_COOKIE, isLocale } from "@/lib/i18n";

// Every page lives under /am or /en (blueprint F.1). An address without one
// goes to the language the visitor chose last, or Amharic.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const first = pathname.split("/")[1] ?? "";
  if (isLocale(first)) return NextResponse.next();
  const remembered = request.cookies.get(LOCALE_COOKIE)?.value ?? "";
  const locale = isLocale(remembered) ? remembered : DEFAULT_LOCALE;
  const url = request.nextUrl.clone();
  url.pathname = `/${locale}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Not the API, Next's own files, the liveness check (D-091), or anything
  // with a file extension.
  matcher: ["/((?!api/|_next/|healthz$|.*\\.[a-zA-Z0-9]+$).*)"],
};
