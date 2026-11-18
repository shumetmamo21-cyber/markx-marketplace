import type { NextConfig } from "next";

// The browser sees one origin (blueprint F.5): /api goes to the API, the rest
// to this app. In production the reverse proxy does this; in development the
// rewrite below does it, so cookies and the CSRF check behave the same.
const apiOrigin = process.env.MARKX_API_ORIGIN ?? "http://127.0.0.1:8000";
const isDev = process.env.NODE_ENV !== "production";

// Security headers on every page (SEC-5, D-084).
//
// The Content Security Policy limits where a page may load from and send to:
// this site only, plus the picture CDN when MARKX_MEDIA_ORIGIN names one
// (F.6). Scripts still allow 'unsafe-inline' because Next.js writes its own
// small inline start-up scripts; a nonce per request would remove that but
// make every page dynamic, so it is a separate, measured change. Development
// adds 'unsafe-eval', which Next's fast refresh needs.
//
// HSTS ("always use HTTPS here") is sent only when MARKX_HSTS_MAX_AGE is set
// at build time, because once a browser has seen it, the site cannot go back
// to plain HTTP for that long. Set it when HTTPS is confirmed end to end; the
// API sends it by itself on staging and production, which refuse to start
// without an https:// origin.
const mediaOrigin = process.env.MARKX_MEDIA_ORIGIN ?? "";
const hstsMaxAge = process.env.MARKX_HSTS_MAX_AGE ?? "";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob:${mediaOrigin ? ` ${mediaOrigin}` : ""}`,
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ...(/^\d+$/.test(hstsMaxAge) ? [{ key: "Strict-Transport-Security", value: `max-age=${hstsMaxAge}` }] : []),
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
  async headers() {
    // Not /api: the API sets its own headers on its own responses.
    return [{ source: "/((?!api/).*)", headers: securityHeaders }];
  },
};

export default nextConfig;
