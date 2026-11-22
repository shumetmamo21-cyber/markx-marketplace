import { qrSvg } from "./qr";

/** A QR code as an SVG picture (S-10; D-107); with `download`, as a file to
 * save and print at the till. */
export function qrFile(link: string, title: string, filename: string, download: boolean): Response {
  return new Response(qrSvg(link, { title }), {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Content-Disposition": `${download ? "attachment" : "inline"}; filename="${filename}"`,
      "Cache-Control": "public, max-age=300",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    },
  });
}
