// What the web server passes on to the API about the visitor (D-091).
//
// Server pages call the API from inside the web container, so without this
// the API sees the web server's own address for every visitor, and its
// per-address limits (search, D-059) would count the whole site as one
// visitor. The reverse proxy sets X-Forwarded-For to the visitor's address
// (it overwrites whatever the visitor sent); this passes that one address on.
// The API believes it only because the web container is on the network listed
// in MARKX_TRUSTED_PROXIES (SEC-3, D-084). The request id lets one visit be
// followed through the proxy, web and API logs.

const ADDRESS = /^[0-9A-Fa-f:.]{2,45}$/;
const REQUEST_ID = /^[A-Za-z0-9-]{1,64}$/;

type HeaderSource = { get(name: string): string | null };

export function forwardedHeaders(incoming: HeaderSource): Record<string, string> {
  const headers: Record<string, string> = {};
  // The nearest address is the one the proxy added; anything before it came
  // from the visitor and is not passed on.
  const chain = (incoming.get("x-forwarded-for") ?? "").split(",");
  const visitor = chain[chain.length - 1]?.trim() ?? "";
  if (ADDRESS.test(visitor)) headers["x-forwarded-for"] = visitor;
  const requestId = incoming.get("x-request-id")?.trim() ?? "";
  if (REQUEST_ID.test(requestId)) headers["x-request-id"] = requestId;
  return headers;
}
