"use client";

import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

const CSRF_COOKIE = "markx_csrf";

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

// The API refuses a change without the app's header, and a signed-in change
// without the session's CSRF token (docs/ARCHITECTURE.md). Both go on every
// request that changes something.
const markxHeaders: Middleware = {
  onRequest({ request }) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      request.headers.set("X-MarkX-Client", "web");
      const csrf = readCookie(CSRF_COOKIE);
      if (csrf) request.headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    }
    return request;
  },
};

export const browserApi = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
browserApi.use(markxHeaders);

/** The API's error code, for showing the right message. */
export function errorCode(error: unknown): string {
  if (error && typeof error === "object" && "error" in error) {
    const inner = (error as { error?: { code?: unknown } }).error;
    if (inner && typeof inner.code === "string") return inner.code;
  }
  return "unknown";
}

/** A multipart upload (a photo) with the same headers as every other change.
 * The browser sets the multipart boundary itself. */
export async function sendForm(path: string, form: FormData): Promise<{ ok: boolean; body: unknown }> {
  const headers: Record<string, string> = { "X-MarkX-Client": "web" };
  const csrf = readCookie(CSRF_COOKIE);
  if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
  const response = await fetch(path, { method: "POST", body: form, headers, credentials: "same-origin" });
  const body: unknown = await response.json().catch(() => null);
  return { ok: response.ok, body };
}
