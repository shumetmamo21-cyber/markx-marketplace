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

// -- resilience (D-100) ----------------------------------------------------------
//
// Every call from the browser goes through here and never throws: when the
// connection drops, the request takes too long or something between the
// browser and the API answers instead of it (a proxy's 502 page, a crash's
// plain "Internal Server Error"), the caller gets an ordinary error with one
// of two codes, so its button or form is released and it can show words and
// a "try again" button (`ProblemNotice`). Nothing here changes what is sent.

/** The connection dropped, or the request took longer than the time limit. */
export const NETWORK_FAILED = "network_unavailable";
/** The server answered with a failure that is not the API's own (5xx). */
export const SERVER_FAILED = "server_unavailable";

/** A call that took longer is given up (PROVISIONAL, D-100). Checkout is safe
 * to send again: it carries its idempotency key. */
export const REQUEST_TIMEOUT_MS = 30_000;
/** A photo or document upload over a slow mobile network gets longer. */
export const UPLOAD_TIMEOUT_MS = 120_000;

/** True for a failure of the connection or the server, which trying again
 * may cure; false for the API's own refusals, which it will not. */
export function isConnectionProblem(code: string): boolean {
  return code === NETWORK_FAILED || code === SERVER_FAILED;
}

/** The error body for a failure, shaped like the API's own (`{error: {code}}`). */
function failureBody(code: typeof NETWORK_FAILED | typeof SERVER_FAILED) {
  return { error: { code, message: "" } };
}

function failureResponse(code: typeof NETWORK_FAILED | typeof SERVER_FAILED, status = 503): Response {
  return new Response(JSON.stringify(failureBody(code)), { status, headers: { "Content-Type": "application/json" } });
}

/** `fetch` with a time limit. The limit also covers reading the answer
 * (aborting stops the body too); the caller's own signal still works. */
function fetchWithin(input: Request | string, init: RequestInit | undefined, ms: number): Promise<Response> {
  const controller = new AbortController();
  const outer = init?.signal ?? (input instanceof Request ? input.signal : undefined);
  if (outer) {
    if (outer.aborted) controller.abort();
    else outer.addEventListener("abort", () => controller.abort(), { once: true });
  }
  // Not cleared when the headers arrive: the body may still hang. Aborting a
  // request that has finished does nothing.
  setTimeout(() => controller.abort(), ms);
  return globalThis.fetch(input, { ...init, signal: controller.signal });
}

/** An answer of 500 or more that does not carry the API's error code is
 * someone else's page (a proxy, a crash): replaced by `server_unavailable`. */
async function normalisedFailure(response: Response): Promise<Response | undefined> {
  if (response.status < 500) return undefined;
  const body: unknown = await response.clone().json().catch(() => null);
  if (errorCode(body) !== "unknown") return undefined;
  return failureResponse(SERVER_FAILED, response.status);
}

const serverFailures: Middleware = {
  async onResponse({ response }) {
    return normalisedFailure(response);
  },
};

/** Wraps one client method so that it never throws: a network failure, a
 * time-out or an unreadable answer becomes `network_unavailable`. */
function guard<M extends (...args: never[]) => Promise<unknown>>(method: M): M {
  return (async (...args: Parameters<M>) => {
    try {
      return await method(...args);
    } catch {
      return { data: undefined, error: failureBody(NETWORK_FAILED), response: failureResponse(NETWORK_FAILED) };
    }
  }) as M;
}

/** The browser's API client, on the page's own origin. Exported for the
 * tests, which give it a short time limit and (Node has no page) an origin. */
export function createBrowserApi(timeoutMs = REQUEST_TIMEOUT_MS, baseUrl = "") {
  const client = createClient<paths>({
    baseUrl,
    credentials: "same-origin",
    fetch: (request: Request) => fetchWithin(request, undefined, timeoutMs),
  });
  client.use(markxHeaders);
  client.use(serverFailures);
  return {
    ...client,
    GET: guard(client.GET),
    POST: guard(client.POST),
    PUT: guard(client.PUT),
    PATCH: guard(client.PATCH),
    DELETE: guard(client.DELETE),
  };
}

export const browserApi = createBrowserApi();

/** The API's error code, for showing the right message. */
export function errorCode(error: unknown): string {
  if (error && typeof error === "object" && "error" in error) {
    const inner = (error as { error?: { code?: unknown } }).error;
    if (inner && typeof inner.code === "string") return inner.code;
  }
  return "unknown";
}

/** A multipart upload (a photo) with the same headers as every other change.
 * The browser sets the multipart boundary itself. Never throws (D-100). */
export async function sendForm(path: string, form: FormData, timeoutMs = UPLOAD_TIMEOUT_MS): Promise<{ ok: boolean; body: unknown }> {
  const headers: Record<string, string> = { "X-MarkX-Client": "web" };
  const csrf = readCookie(CSRF_COOKIE);
  if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
  try {
    const response = await fetchWithin(path, { method: "POST", body: form, headers, credentials: "same-origin" }, timeoutMs);
    const answer = (await normalisedFailure(response)) ?? response;
    const body: unknown = await answer.json().catch(() => null);
    return { ok: answer.ok, body };
  } catch {
    return { ok: false, body: failureBody(NETWORK_FAILED) };
  }
}

/** A GET outside the typed client (a file download). Never throws: a failure
 * comes back as `{ ok: false, body }` with the API's error or one of the two
 * codes above. The caller reads the answer's body inside `readBody`, which is
 * guarded the same way. */
export async function getSafely<T>(path: string, readBody: (response: Response) => Promise<T>, timeoutMs = REQUEST_TIMEOUT_MS): Promise<{ ok: true; value: T } | { ok: false; body: unknown }> {
  try {
    const response = await fetchWithin(path, { credentials: "same-origin" }, timeoutMs);
    if (!response.ok) {
      const answer = (await normalisedFailure(response)) ?? response;
      return { ok: false, body: await answer.json().catch(() => null) };
    }
    return { ok: true, value: await readBody(response) };
  } catch {
    return { ok: false, body: failureBody(NETWORK_FAILED) };
  }
}
