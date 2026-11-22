import { fill, isLocale } from "@/lib/i18n";
import { publicOrigin, shareLinks } from "@/lib/share";
import { qrFile } from "@/lib/qr-file";
import { messagesFor, publicProduct } from "@/lib/share-data";

// A product's QR code as an SVG file (S-10; D-107).
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: RouteContext<"/[lang]/p/[slug]/qr">) {
  const { lang, slug } = await params;
  const origin = publicOrigin(process.env);
  if (!isLocale(lang) || !origin || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) return new Response(null, { status: 404 });
  const product = await publicProduct(request, slug, lang);
  if (!product) return new Response(null, { status: 404 });
  const t = messagesFor(lang);
  const link = shareLinks(origin, lang, "product", product.slug, product.name).page;
  return qrFile(link, fill(t.share.qrAlt, { name: product.name }), `markx-${product.slug}-qr.svg`, new URL(request.url).searchParams.get("download") === "1");
}
