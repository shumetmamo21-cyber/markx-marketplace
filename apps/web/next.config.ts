import type { NextConfig } from "next";

// The browser sees one origin (blueprint F.5): /api goes to the API, the rest
// to this app. In production the reverse proxy does this; in development the
// rewrite below does it, so cookies and the CSRF check behave the same.
const apiOrigin = process.env.MARKX_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
