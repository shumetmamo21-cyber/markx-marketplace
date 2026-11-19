// Liveness for the container check and the reverse proxy (D-091): the web
// server answers. It calls nothing else, so an API or database outage never
// gets a healthy web server restarted. Readiness of the whole site is the
// API's /api/v1/healthz/ready.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "alive" }, { headers: { "Cache-Control": "no-store" } });
}
