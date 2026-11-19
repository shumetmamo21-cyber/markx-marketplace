import { notFound } from "next/navigation";

import { RemovePictureForm, UploadPictureForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMe } from "@/lib/session";
import { getMessages } from "@/lib/messages";

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

// Product pictures (blueprint AD-03; D-062): every picture of a product in
// every state, for moderation (moderate_listings), and the catalogue upload
// (curate_catalogue). The worker cleans and renders an upload before buyers
// see it; the API decides who may do what.
export default async function PicturesPage({ params, searchParams }: PageProps<"/[lang]/admin/pictures">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const a = t.admin;
  const raw = (await searchParams).product;
  const slug = (typeof raw === "string" ? raw : "").trim().toLowerCase();
  const api = await serverApi();
  const me = await getMe();
  const product = SLUG.test(slug) ? (await api.GET("/api/v1/catalog/products/{slug}", { params: { path: { slug }, query: { lang } } })).data : undefined;
  const pictures = product ? await api.GET("/api/v1/admin/catalog/products/{product_id}/images", { params: { path: { product_id: product.id } } }) : null;
  if (pictures?.response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const rows = pictures?.data ?? [];
  const mayUpload = me?.staff?.capabilities.includes("curate_catalogue") ?? false;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">{a.picturesTitle}</h1>
      <p className="text-slate">{a.picturesLead}</p>
      <form method="get" className="flex max-w-md items-end gap-2">
        <label className="flex-1 space-y-1">
          <span className="block text-sm font-semibold">{a.productSlug}</span>
          <input name="product" defaultValue={slug} required className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
        </label>
        <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{a.find}</button>
      </form>
      {slug && !product ? <p role="alert" className="font-semibold text-clay">{a.productNotFound}</p> : null}
      {product ? (
        <>
          <h2 className="text-lg font-bold">{product.name}</h2>
          {mayUpload ? (
            <section className="space-y-2">
              <h3 className="font-bold">{a.uploadPicture}</h3>
              <UploadPictureForm productId={product.id} t={text} />
            </section>
          ) : null}
          {rows.length === 0 ? <p className="text-slate">{a.noPictures}</p> : null}
          <ul className="grid gap-3 sm:grid-cols-2">
            {rows.map((picture) => (
              <li key={picture.id} className="space-y-2 rounded-card border border-line bg-white p-4">
                {picture.thumb_url ? (
                  // eslint-disable-next-line @next/next/no-img-element -- served by the API, already sized by the worker
                  <img src={picture.thumb_url} alt="" width={picture.width ?? undefined} height={picture.height ?? undefined} className="h-32 w-auto rounded-card border border-line object-contain" />
                ) : null}
                <p className="font-semibold">{codeLabel(t, "imageStatus", picture.status)} · {codeLabel(t, "imageKind", picture.kind)}</p>
                <p className="text-sm text-slate">
                  {formatDateTime(picture.created_at, lang)}
                  {picture.width && picture.height ? ` · ${fill(a.pictureSize, { width: picture.width, height: picture.height })}` : ""}
                </p>
                {picture.failure_reason ? <p className="text-sm font-semibold text-clay">{fill(a.pictureFailed, { reason: picture.failure_reason })}</p> : null}
                {picture.removed_reason ? <p className="text-sm">{fill(a.pictureRemoved, { reason: picture.removed_reason })}</p> : null}
                {picture.status !== "removed" ? <RemovePictureForm imageId={picture.id} t={text} /> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
