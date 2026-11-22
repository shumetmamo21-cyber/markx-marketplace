// C-12 lite mode (blueprint D.1, I.1 "works on bad days"; D-107): smaller
// pictures and no picture strips, for a slow connection or a cheap phone.
//
// Remembered in a cookie the person sets with a plain link (no script
// needed). Without a choice, the phone's own "save data" setting decides:
// browsers in data-saver mode send `Save-Data: on` with every request.
// PROVISIONAL (P-107-6, D-107): lite mode turns on by itself for Save-Data
// and is otherwise off; the person's own choice always wins.

export const LITE_COOKIE = "markx_lite";
export const LITE_MAX_AGE_SECONDS = 31_536_000; // a year, like the language

/** Whether a page is drawn in lite mode, from the person's remembered choice
 * ("1" on, "0" off) and the browser's Save-Data header. */
export function liteFrom(cookie: string | undefined | null, saveData: string | undefined | null): boolean {
  if (cookie === "1") return true;
  if (cookie === "0") return false;
  return (saveData ?? "").trim().toLowerCase() === "on";
}

/** The cookie value for the switch's `on` parameter, or null for anything else. */
export function liteChoice(on: string | null): "1" | "0" | null {
  if (on === "1") return "1";
  if (on === "0") return "0";
  return null;
}

/** The page to go back to after the switch: only the path and query of the
 * Referer (the origin is dropped, so it can only be a page of this site),
 * never the switch itself; null when there is none. `safeNext` judges it. */
export function liteReturnPath(referer: string | null): string | null {
  if (!referer) return null;
  try {
    const url = new URL(referer);
    if (/^\/(am|en)\/lite(\/|$)/.test(url.pathname)) return null;
    return `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}
