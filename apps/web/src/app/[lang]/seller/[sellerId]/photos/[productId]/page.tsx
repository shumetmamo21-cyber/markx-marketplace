import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PhotoUpload } from "@/components/PhotoUpload";
import { WithdrawPhotoButton } from "@/components/WithdrawPhotoButton";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// The shop's own photos of one product it sells (blueprint D.5, S-06): every
// photo in every state, an upload, and a way to take one down. The API
// decides who may add, how many, and of what (D-062).
export default async function SellerPhotosPage({ params }: PageProps<"/[lang]/seller/[sellerId]/photos/[productId]">) {
  const { lang, sellerId, productId } = await params;
  if (!isLocale(lang) || !/^[0-9a-f-]{36}$/.test(productId)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [photos, offers] = await Promise.all([
    api.GET("/api/v1/seller/{seller_id}/products/{product_id}/photos", { params: { path: { seller_id: sellerId, product_id: productId } } }),
    api.GET("/api/v1/seller/{seller_id}/offers", { params: { path: { seller_id: sellerId }, query: { lang } } }),
  ]);
  const s = t.seller;
  if (photos.response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const product = (offers.data ?? []).find((offer) => offer.product_id === productId);
  const name = product?.product_name ?? "";
  const list = photos.data ?? [];
  const text = { seller: t.seller, apiErrors: t.apiErrors };
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <p><Link href={`/${lang}/seller/${sellerId}/offers`} className="inline-flex min-h-12 items-center font-semibold underline">{s.photoBack}</Link></p>
      <h1 className="text-2xl font-extrabold">{fill(s.photosTitle, { product: name })}</h1>
      <p className="text-slate">{s.photosLead}</p>
      {list.length === 0 ? <p>{s.photosNone}</p> : null}
      <ul className="grid gap-3 sm:grid-cols-2">
        {list.map((photo) => (
          <li key={photo.id} className="space-y-2 rounded-card border border-line bg-white p-3">
            {photo.thumb_url ? (
              <a href={photo.main_url ?? photo.thumb_url} className="flex h-40 items-center justify-center overflow-hidden rounded-card bg-paper">
                {/* eslint-disable-next-line @next/next/no-img-element -- a thumbnail within 320 px and 30 KB (D-062) */}
                <img src={photo.thumb_url} alt={fill(s.photoAlt, { product: name })} className="h-full w-full object-contain" />
              </a>
            ) : null}
            <p className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="rounded-full border border-line px-3 py-1 font-semibold">{codeLabel(t, "imageStatus", photo.status)}</span>
              <span className="text-slate">{formatDateTime(photo.created_at, lang)}</span>
            </p>
            {photo.status === "removed" && photo.removed_reason ? <p className="text-sm text-clay">{fill(s.photoRemoved, { reason: photo.removed_reason })}</p> : null}
            {photo.status === "failed" && photo.failure_reason ? <p className="text-sm text-clay">{fill(s.photoFailed, { reason: photo.failure_reason })}</p> : null}
            {photo.status !== "removed" ? <WithdrawPhotoButton sellerId={sellerId} imageId={photo.id} t={text} /> : null}
          </li>
        ))}
      </ul>
      <section aria-labelledby="add-photo" className="space-y-2 rounded-card border border-line bg-white p-4">
        <h2 id="add-photo" className="font-bold">{s.photoAdd}</h2>
        <PhotoUpload path={`/api/v1/seller/${sellerId}/products/${productId}/photos`} label={s.photoChoose} send={s.photoUpload} sent={s.photoReceived} t={text} />
      </section>
    </div>
  );
}
