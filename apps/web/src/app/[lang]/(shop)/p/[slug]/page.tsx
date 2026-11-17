import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AddToCart } from "@/components/AddToCart";
import { serverApi } from "@/lib/api/server";
import type { RankedOffer } from "@/lib/api/types";
import { formatPrice, timeAgo } from "@/lib/format";
import { fill, isLocale, type Locale, type Messages } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

async function load(lang: Locale, slug: string) {
  const api = await serverApi();
  const product = await api.GET("/api/v1/catalog/products/{slug}", { params: { path: { slug }, query: { lang } } });
  if (product.response.status === 404 || !product.data) notFound();
  return product.data;
}

export async function generateMetadata({ params }: PageProps<"/[lang]/p/[slug]">): Promise<Metadata> {
  const { lang, slug } = await params;
  if (!isLocale(lang)) return {};
  const product = await load(lang, slug);
  return { title: product.name, description: product.description || undefined };
}

function conditionLabel(t: Messages, condition: string): string {
  return condition in t.condition ? t.condition[condition as keyof Messages["condition"]] : condition;
}

function OfferRow({ offer, lang, t, zoneChosen }: { offer: RankedOffer; lang: Locale; t: Messages; zoneChosen: boolean }) {
  return (
    <li className={`rounded-card border bg-card p-4 ${offer.is_default ? "border-ink" : "border-line"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          {offer.is_default ? (
            <p className="inline-flex rounded-full bg-adey px-2 py-0.5 text-xs font-bold">
              {t.product.best}
              {offer.default_reason ? ` · ${offer.default_reason === "lowest_total_delivered" ? t.product.bestReasonTotal : t.product.bestReasonPrice}` : ""}
            </p>
          ) : null}
          <p className="font-bold">
            <Link href={`/${lang}/s/${offer.store_slug}`} className="hover:underline">{offer.store_name}</Link>
          </p>
          <p className="flex flex-wrap gap-x-3 text-sm text-slate">
            {offer.seller_verification_level >= 2 ? (
              <span className="font-semibold text-highland">{fill(t.card.level, { level: offer.seller_verification_level })}</span>
            ) : (
              <span>{fill(t.card.level, { level: offer.seller_verification_level })}</span>
            )}
            <span>{conditionLabel(t, offer.condition)}</span>
            <span>{offer.warranty_months > 0 ? fill(t.product.warrantyMonths, { months: offer.warranty_months }) : t.product.noWarranty}</span>
          </p>
          <p className="text-sm text-slate">{fill(t.product.confirmed, { ago: timeAgo(offer.price_confirmed_at, lang) })}</p>
        </div>
        <div className="space-y-1 text-right">
          <p className="price text-xl">{formatPrice(offer.price_santim, lang)}</p>
          {zoneChosen ? (
            offer.delivery_fee_santim !== null ? (
              <p className="text-sm">
                {t.product.delivery}: <span className="price font-semibold">{formatPrice(offer.delivery_fee_santim, lang)}</span>
                <br />
                {t.product.total}: <span className="price">{formatPrice(offer.total_santim, lang)}</span>
              </p>
            ) : (
              <p className="text-sm text-slate">{t.product.freeCollection}</p>
            )
          ) : null}
        </div>
      </div>
      <div className="mt-3 max-w-xs">
        {offer.in_stock ? (
          <AddToCart
            offerId={offer.id}
            cartHref={`/${lang}/cart`}
            labels={{ add: t.product.addToCart, adding: t.product.adding, added: t.product.added, failed: t.product.addFailed, cart: t.nav.cart }}
          />
        ) : (
          <p className="font-semibold text-clay">{t.product.outOfStock}</p>
        )}
      </div>
    </li>
  );
}

export default async function ProductPage({ params, searchParams }: PageProps<"/[lang]/p/[slug]">) {
  const { lang, slug } = await params;
  if (!isLocale(lang)) notFound();
  const raw = await searchParams;
  const t = await getMessages(lang);
  const product = await load(lang, slug);
  if (product.slug !== slug) redirect(`/${lang}/p/${product.slug}`); // a merged product's old link

  const variants = product.variants.filter((variant) => variant.is_active);
  const wanted = one(raw.variant);
  const variant = variants.find((v) => v.id === wanted) ?? variants[0];
  const zone = one(raw.zone);
  const api = await serverApi();
  const [offers, zones] = await Promise.all([
    api.GET("/api/v1/catalog/products/{slug}/offers", {
      params: { path: { slug: product.slug }, query: { variant_id: variant?.id, zone: zone || undefined } },
    }),
    api.GET("/api/v1/delivery/zones", {}),
  ]);
  const ranked = offers.data?.offers ?? [];
  const zoneChosen = Boolean(offers.data?.zone_code);

  return (
    <div className="space-y-8 pb-6">
      <section className="space-y-2">
        <p className="text-sm text-slate">
          <Link href={`/${lang}/search?category=${product.category.slug}`} className="underline">{product.category.name}</Link>
          {product.brand ? ` · ${product.brand.name}` : ""}
        </p>
        <h1 className="text-2xl font-extrabold md:text-3xl">{product.name}</h1>
        {product.description ? <p className="max-w-prose text-slate">{product.description}</p> : null}
      </section>

      {variants.length > 1 ? (
        <section aria-labelledby="variant" className="space-y-2">
          <h2 id="variant" className="font-bold">{t.product.variant}</h2>
          <ul className="flex flex-wrap gap-2">
            {variants.map((v) => (
              <li key={v.id}>
                <Link
                  href={`/${lang}/p/${product.slug}?variant=${v.id}${zone ? `&zone=${zone}` : ""}`}
                  aria-current={v.id === variant?.id ? "true" : undefined}
                  className={`inline-flex min-h-12 items-center rounded-full border px-4 font-semibold ${v.id === variant?.id ? "border-ink bg-ink text-paper" : "border-line bg-white"}`}
                >
                  {v.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="offers" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="offers" className="text-lg font-bold">
            {t.product.offersTitle} <span className="font-normal text-slate">({fill(t.product.offersCount, { count: ranked.length })})</span>
          </h2>
          <form method="get" className="flex w-full flex-wrap items-end gap-2 sm:w-auto">
            {variant ? <input type="hidden" name="variant" value={variant.id} /> : null}
            <label className="min-w-0 flex-1 space-y-1">
              <span className="block text-sm font-semibold">{t.product.zone}</span>
              <select name="zone" defaultValue={zone} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
                <option value="">{t.product.zoneAny}</option>
                {(zones.data ?? []).filter((z) => z.is_active).map((z) => (
                  <option key={z.code} value={z.code}>{lang === "am" ? z.name_am : z.name_en}</option>
                ))}
              </select>
            </label>
            <button type="submit" className="min-h-12 shrink-0 rounded-card border border-ink px-4 font-semibold">{t.product.zoneApply}</button>
          </form>
        </div>
        {ranked.length ? (
          <ul className="space-y-3">
            {ranked.map((offer) => (
              <OfferRow key={offer.id} offer={offer} lang={lang} t={t} zoneChosen={zoneChosen} />
            ))}
          </ul>
        ) : (
          <p className="text-slate">{t.product.noOffers}</p>
        )}
        <p className="flex gap-2 rounded-card border border-line bg-white p-4 text-sm">
          <svg aria-hidden="true" viewBox="0 0 16 16" className="mt-0.5 h-4 w-4 shrink-0 text-highland"><path d="M3 8l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
          {t.product.inspect}
        </p>
      </section>

      {product.specs.length ? (
        <section aria-labelledby="specs" className="space-y-2">
          <h2 id="specs" className="text-lg font-bold">{t.product.specs}</h2>
          <dl className="grid max-w-lg grid-cols-2 gap-x-4 gap-y-2 rounded-card border border-line bg-white p-4">
            {product.specs.map((spec) => (
              <div key={spec.code} className="contents">
                <dt className="text-slate">{spec.name}</dt>
                <dd className="font-semibold">{spec.display}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  );
}
