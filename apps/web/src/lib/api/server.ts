import "server-only";

import { cookies, headers } from "next/headers";
import createClient from "openapi-fetch";

import { forwardedHeaders } from "./forwarded";
import type { paths } from "./schema";

// Server components read the API directly, not through the public origin,
// and pass the visitor's own cookies so the API sees who is asking. Never
// cached: prices and stock are read fresh on every request (D-055).
const API_ORIGIN = process.env.MARKX_API_ORIGIN ?? "http://127.0.0.1:8000";

export async function serverApi() {
  const jar = await cookies();
  const incoming = await headers();
  return createClient<paths>({
    baseUrl: API_ORIGIN,
    cache: "no-store",
    // The visitor's address and the request id, as the proxy gave them (D-091).
    headers: { ...forwardedHeaders(incoming), cookie: jar.toString() },
  });
}
