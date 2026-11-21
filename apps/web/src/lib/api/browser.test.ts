// The shared way the browser calls the API (D-100): it never throws, a
// dropped connection, a time-out or a page that is not the API's own becomes
// one of two codes, and what is sent (the app's header, the CSRF token) is
// exactly what it was before.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createBrowserApi,
  errorCode,
  getSafely,
  isConnectionProblem,
  NETWORK_FAILED,
  sendForm,
  SERVER_FAILED,
} from "./browser";

const ORIGIN = "http://markx.test";
type Seen = { request: Request; signal: AbortSignal | undefined };
let seen: Seen[] = [];

function answer(reply: (request: Request) => Promise<Response> | Response) {
  vi.stubGlobal("fetch", async (input: Request | string, init?: RequestInit) => {
    const request = input instanceof Request ? new Request(input, init) : new Request(`${ORIGIN}${input}`, init);
    seen.push({ request, signal: init?.signal ?? undefined });
    return reply(request);
  });
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const apiError = (code: string) => ({ error: { code, message: "words", request_id: "r" } });
const addToCart = (api: ReturnType<typeof createBrowserApi>) =>
  api.PUT("/api/v1/cart/items/{offer_id}", { params: { path: { offer_id: "o1" } }, body: { quantity: 1 } });

beforeEach(() => {
  seen = [];
  vi.stubGlobal("document", { cookie: "other=1; markx_csrf=token%2Fvalue" });
});
afterEach(() => vi.unstubAllGlobals());

describe("the browser's API client", () => {
  it("turns a dropped connection into network_unavailable instead of throwing", async () => {
    answer(() => Promise.reject(new TypeError("Failed to fetch")));
    const { data, error } = await addToCart(createBrowserApi(undefined, ORIGIN));
    expect(data).toBeUndefined();
    expect(errorCode(error)).toBe(NETWORK_FAILED);
    expect(isConnectionProblem(errorCode(error))).toBe(true);
  });

  it("gives up a request that hangs, at the time limit, and aborts it", async () => {
    answer(
      (request) =>
        new Promise((_, reject) => {
          request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const started = Date.now();
    const { error } = await addToCart(createBrowserApi(50, ORIGIN));
    expect(errorCode(error)).toBe(NETWORK_FAILED);
    expect(Date.now() - started).toBeLessThan(2000);
    expect(seen[0]?.signal?.aborted).toBe(true);
  });

  it("gives up an answer whose body stops halfway, at the time limit", async () => {
    answer((request) => {
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('{"items": ['));
          request.signal.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
        },
      });
      return new Response(body, { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const { error } = await createBrowserApi(50, ORIGIN).GET("/api/v1/cart", { params: { query: { lang: "en" } } });
    expect(errorCode(error)).toBe(NETWORK_FAILED);
  });

  it("turns a proxy's error page or a crash's plain text into server_unavailable", async () => {
    for (const reply of [
      new Response("<html><body>502 Bad Gateway</body></html>", { status: 502, headers: { "Content-Type": "text/html" } }),
      new Response("Internal Server Error", { status: 500, headers: { "Content-Type": "text/plain" } }),
      new Response("", { status: 504 }),
    ]) {
      answer(() => reply);
      const { error } = await addToCart(createBrowserApi(undefined, ORIGIN));
      expect(errorCode(error)).toBe(SERVER_FAILED);
    }
  });

  it("keeps the API's own refusals, 5xx included, exactly as they were", async () => {
    for (const [status, code] of [[409, "too_many_open_orders"], [503, "storage_unavailable"], [429, "rate_limited"], [422, "validation_failed"]] as const) {
      answer(() => json(status, apiError(code)));
      const { error } = await addToCart(createBrowserApi(undefined, ORIGIN));
      expect(errorCode(error)).toBe(code);
      expect(isConnectionProblem(code)).toBe(false);
    }
  });

  it("returns the API's answer unchanged when it succeeds", async () => {
    answer(() => json(200, { line_count: 1 }));
    const { data, error } = await addToCart(createBrowserApi(undefined, ORIGIN));
    expect(error).toBeUndefined();
    expect(data).toEqual({ line_count: 1 });
  });

  it("treats a success whose body cannot be read as a dropped connection", async () => {
    answer(() => new Response("{not json", { status: 200, headers: { "Content-Type": "application/json" } }));
    const { error } = await addToCart(createBrowserApi(undefined, ORIGIN));
    expect(errorCode(error)).toBe(NETWORK_FAILED);
  });

  it("still sends the app's header and the CSRF token on a change, and neither on a read", async () => {
    answer(() => json(200, {}));
    const api = createBrowserApi(undefined, ORIGIN);
    await addToCart(api);
    await api.GET("/api/v1/cart", { params: { query: { lang: "en" } } });
    const [change, read] = seen;
    expect(change?.request.method).toBe("PUT");
    expect(change?.request.headers.get("X-MarkX-Client")).toBe("web");
    expect(change?.request.headers.get("X-CSRF-Token")).toBe("token/value");
    expect(change?.request.credentials).toBe("same-origin");
    expect(read?.request.method).toBe("GET");
    expect(read?.request.headers.get("X-MarkX-Client")).toBeNull();
    expect(read?.request.headers.get("X-CSRF-Token")).toBeNull();
  });
});

describe("a photo or document upload", () => {
  const form = () => {
    const data = new FormData();
    data.set("file", new Blob(["x"], { type: "image/png" }), "x.png");
    return data;
  };

  it("never throws on a dropped connection", async () => {
    answer(() => Promise.reject(new TypeError("Failed to fetch")));
    const sent = await sendForm("/api/v1/seller/s/documents", form());
    expect(sent.ok).toBe(false);
    expect(errorCode(sent.body)).toBe(NETWORK_FAILED);
  });

  it("gives up at its own time limit", async () => {
    answer((request) => new Promise((_, reject) => request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))));
    const sent = await sendForm("/api/v1/seller/s/documents", form(), 50);
    expect(errorCode(sent.body)).toBe(NETWORK_FAILED);
  });

  it("turns a proxy's page into server_unavailable and keeps the API's refusal", async () => {
    answer(() => new Response("<html>413 or 502</html>", { status: 502 }));
    expect(errorCode((await sendForm("/x", form())).body)).toBe(SERVER_FAILED);
    answer(() => json(413, apiError("payload_too_large")));
    expect(errorCode((await sendForm("/x", form())).body)).toBe("payload_too_large");
  });

  it("sends the same headers as before and reports success", async () => {
    answer(() => json(201, { id: "d1" }));
    const sent = await sendForm("/api/v1/seller/s/documents", form());
    expect(sent).toEqual({ ok: true, body: { id: "d1" } });
    expect(seen[0]?.request.headers.get("X-MarkX-Client")).toBe("web");
    expect(seen[0]?.request.headers.get("X-CSRF-Token")).toBe("token/value");
  });
});

describe("a file download", () => {
  it("reports a connection that drops while the file is read", async () => {
    answer(() => new Response("a,b\n", { status: 200 }));
    const got = await getSafely("/api/v1/admin/exports/orders", async () => {
      throw new TypeError("network error");
    });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(errorCode(got.body)).toBe(NETWORK_FAILED);
  });

  it("keeps the API's refusal and returns the file otherwise", async () => {
    answer(() => json(422, apiError("export_period_invalid")));
    const refused = await getSafely("/x", (r) => r.text());
    expect(refused.ok ? "" : errorCode(refused.body)).toBe("export_period_invalid");
    answer(() => new Response("a,b\n", { status: 200 }));
    expect(await getSafely("/x", (r) => r.text())).toEqual({ ok: true, value: "a,b\n" });
  });
});
