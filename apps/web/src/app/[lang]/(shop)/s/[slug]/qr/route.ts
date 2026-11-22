import { fill, isLocale } from "@/lib/i18n";
import { publicOrigin, shareLinks } from "@/lib/share";
import { qrFile } from "@/lib/qr-file";
import { messagesFor, publicStore } from "@/lib/share-data";

// A shop's QR code as an SVG file, to print at the till (S-10; D-107).
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: RouteContext<"/[lang]/s/[slug]/qr">) {
  const { lang, slug } = await params;
  const origin = publicOrigin(process.env);
  if (!isLocale(lang) || !origin || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) return new Response(null, { status: 404 });
  const store = await publicStore(request, slug);
  if (!store) return new Response(null, { status: 404 });
  const t = messagesFor(lang);
  const link = shareLinks(origin, lang, "store", store.slug, store.name).page;
  return qrFile(link, fill(t.share.qrAlt, { name: store.name }), `markx-${store.slug}-qr.svg`, new URL(request.url).searchParams.get("download") === "1");
}
