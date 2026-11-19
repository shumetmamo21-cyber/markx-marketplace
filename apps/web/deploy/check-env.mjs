// The web server's start-up check for staging and production (D-091).
//
// `node deploy/start.mjs` (the production image's command) runs this before
// it starts the server; a refused setting stops the container with a message
// that names the setting and never its value. On a laptop and in CI
// (MARKX_ENV unset, "local" or "test") nothing is required.
//
// The API has its own, stricter check (apps/api/markx/core/config.py); this
// one covers what only the web server reads.

const REAL = new Set(["staging", "production"]);
const KNOWN = new Set(["", "local", "test", "staging", "production"]);

function origin(value) {
  try {
    const url = new URL(value);
    if (url.pathname !== "/" || url.search || url.hash || url.username || url.password) return null;
    if (!value.startsWith(`${url.protocol}//`) || value.endsWith("/")) return null;
    return url;
  } catch {
    return null;
  }
}

// Cloudflare's published Turnstile test keys look like "1x0000…AA"; a real
// site key starts "0x" (the API refuses the test keys the same way, D-085).
function isTurnstileTestKey(key) {
  return /^[123]x000000/.test(key);
}

/** Every problem with the web server's environment, in words. */
export function webEnvironmentProblems(env) {
  const stage = (env.MARKX_ENV ?? "").trim();
  if (!KNOWN.has(stage)) return [`MARKX_ENV must be local, test, staging or production, not "${stage}"`];
  if (!REAL.has(stage)) return [];

  const problems = [];
  if (env.NODE_ENV !== "production") problems.push("NODE_ENV must be production");

  const api = origin(env.MARKX_API_ORIGIN ?? "");
  if (!api || !["http:", "https:"].includes(api.protocol)) {
    problems.push("MARKX_API_ORIGIN must be the API's internal origin, such as http://api:8000");
  }

  const site = origin(env.MARKX_PUBLIC_ORIGIN ?? "");
  if (!site || site.protocol !== "https:") {
    problems.push("MARKX_PUBLIC_ORIGIN must be the site's https:// origin, the same value the API has");
  }

  const media = origin(env.MARKX_MEDIA_ORIGIN ?? "");
  if (!media || media.protocol !== "https:") {
    problems.push("MARKX_MEDIA_ORIGIN must be the picture CDN's https:// origin (the same at build and run time)");
  } else if (site && media.hostname === site.hostname) {
    problems.push("MARKX_MEDIA_ORIGIN must be on its own domain, not the site's");
  }

  const siteKey = (env.MARKX_TURNSTILE_SITE_KEY ?? "").trim();
  if (!siteKey) problems.push("MARKX_TURNSTILE_SITE_KEY must be set (the public site key of the site's own widget)");
  else if (isTurnstileTestKey(siteKey)) problems.push("MARKX_TURNSTILE_SITE_KEY must be a real site key, not a Cloudflare test key");

  if (env.MARKX_HSTS_MAX_AGE) problems.push("MARKX_HSTS_MAX_AGE is not used at run time; the reverse proxy sends HSTS (D-091)");
  return problems;
}
