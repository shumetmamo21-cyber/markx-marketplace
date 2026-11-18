// Where to send someone after they sign in (SEC-1, D-084).
//
// The address comes from the `next` query parameter, which anyone can put in
// a link, so it must never lead off the site. A plain "starts with one slash"
// check is not enough: browsers read "/\evil.example" as "//evil.example"
// (another site), drop tabs and line breaks inside addresses, and a link can
// hide a backslash as "%5C". So: refuse anything that is not an ordinary path
// on this site, and fall back to a safe page.

const PLACEHOLDER_ORIGIN = "https://markx.invalid";

/** Returns `value` when it is a path on this site, otherwise `fallback`. */
export function safeNext(value: string | string[] | undefined | null, fallback: string): string {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || raw.length > 2048) return fallback;
  // Look through up to three layers of percent-encoding, so "%5C" and
  // "%255C" are judged by what they become.
  let decoded = raw;
  for (let i = 0; i < 3; i++) {
    let next: string;
    try {
      next = decodeURIComponent(decoded);
    } catch {
      return fallback; // malformed encoding: nothing a real link of ours makes
    }
    if (next === decoded) break;
    decoded = next;
  }
  for (const form of [raw, decoded]) {
    if (!form.startsWith("/") || form.startsWith("//")) return fallback;
    if (form.includes("\\")) return fallback;
    // Control characters, including tab and line breaks, which browsers drop.
    if (/[\u0000-\u001f\u007f]/.test(form)) return fallback;
  }
  // Finally, let the URL parser decide: the result must stay on this origin.
  let url: URL;
  try {
    url = new URL(raw, PLACEHOLDER_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== PLACEHOLDER_ORIGIN) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}
