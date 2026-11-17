import { notFound } from "next/navigation";

import { LiftHoldForm, TakeDownForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

// Listing moderation (AD-03): take a live offer down with a reason, and lift a
// takedown deliberately (D-032). A takedown holds: the seller cannot relist
// the item until staff lift it, and lifting publishes nothing by itself.
export default async function ListingsPage({ params, searchParams }: PageProps<"/[lang]/admin/listings">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const raw = (await searchParams).product;
  const slug = (typeof raw === "string" ? raw : "").trim().toLowerCase();
  const api = await serverApi();
  const [held, offers] = await Promise.all([
    api.GET("/api/v1/admin/offers/held", { params: { query: { limit: 200, lang } } }),
    SLUG.test(slug) ? api.GET("/api/v1/catalog/products/{slug}/offers", { params: { path: { slug } } }) : null,
  ]);
  const a = t.admin;
  if (held.response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const condition = (code: string) => (t.condition as Record<string, string>)[code] ?? code;
  const heldRows = held.data ?? [];
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-extrabold">{a.listingsTitle}</h1>
      <section className="space-y-3">
        <h2 className="text-lg font-bold">{a.findListingTitle}</h2>
        <form method="get" className="flex max-w-md items-end gap-2">
          <label className="flex-1 space-y-1">
            <span className="block text-sm font-semibold">{a.productSlug}</span>
            <input name="product" defaultValue={slug} required className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
          </label>
          <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{a.showOffers}</button>
        </form>
        {slug && !offers?.data ? <p role="alert" className="font-semibold text-clay">{a.productNotFound}</p> : null}
        {offers?.data && offers.data.offers.length === 0 ? <p className="text-slate">{a.noOffers}</p> : null}
        <ul className="space-y-3">
          {(offers?.data?.offers ?? []).map((offer) => (
            <li key={offer.id} className="space-y-2 rounded-card border border-line bg-white p-4">
              <p className="font-semibold">{offer.store_name} · {condition(offer.condition)}</p>
              <p className="text-sm text-slate">{fill(a.price, { price: formatPrice(offer.price_santim, lang) })}</p>
              <TakeDownForm offerId={offer.id} t={text} />
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-bold">{a.heldTitle}</h2>
        {heldRows.length === 0 ? <p className="text-slate">{a.noHeld}</p> : null}
        <ul className="space-y-3">
          {heldRows.map((offer) => (
            <li key={offer.id} className="space-y-2 rounded-card border border-line bg-white p-4">
              <p className="font-bold">{offer.product_name} <span className="font-normal text-slate">· {offer.variant_label}</span></p>
              <p className="text-sm text-slate">
                {offer.store_name} · {condition(offer.condition)} · {fill(a.price, { price: formatPrice(offer.price_santim, lang) })}
              </p>
              <p className="text-sm">{fill(a.takenDown, { time: formatDateTime(offer.removed_by_staff_at, lang) })}{offer.reason ? ` · ${fill(a.heldReason, { reason: offer.reason })}` : ""}</p>
              <LiftHoldForm offerId={offer.id} t={text} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
