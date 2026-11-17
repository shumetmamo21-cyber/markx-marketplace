import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ReportForm } from "@/components/ReportForm";
import { RatingSummary, ReviewItem } from "@/components/Reviews";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale, type Messages } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export async function generateMetadata({ params }: PageProps<"/[lang]/s/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const api = await serverApi();
  const { data } = await api.GET("/api/v1/catalog/stores/{slug}", { params: { path: { slug } } });
  return data ? { title: data.name } : {};
}

// Judge a seller (blueprint I.5): the level and exactly what was checked,
// member since, completed orders, policies and offers. Numbers, not adjectives.
const REVIEWS_PER_PAGE = 10;

export default async function StorePage({ params, searchParams }: PageProps<"/[lang]/s/[slug]">) {
  const { lang, slug } = await params;
  if (!isLocale(lang)) notFound();
  const raw = (await searchParams).reviews;
  const before = (Array.isArray(raw) ? raw[0] : raw) ?? "";
  const t = await getMessages(lang);
  const api = await serverApi();
  const [store, offers, reviews] = await Promise.all([
    api.GET("/api/v1/catalog/stores/{slug}", { params: { path: { slug } } }),
    api.GET("/api/v1/catalog/stores/{slug}/offers", { params: { path: { slug }, query: { lang } } }),
    api.GET("/api/v1/catalog/stores/{slug}/reviews", {
      params: { path: { slug }, query: { lang, limit: REVIEWS_PER_PAGE, before: /^[0-9a-f-]{36}$/.test(before) ? before : undefined } },
    }),
  ]);
  if (!store.data) notFound();
  const s = store.data;
  const reportText = { report: t.report, apiErrors: t.apiErrors, reasons: t.labels.reportReason };
  const shown = reviews.data?.reviews ?? [];
  const checks = Object.entries(s.checks).filter(([, done]) => done).map(([key]) => key);
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-extrabold">{s.name}</h1>
        <p className="font-semibold text-highland">{fill(t.store.level, { level: s.verification_level })}</p>
        <p className="text-slate">{s.shop_address}</p>
        {s.shop_latitude !== null && s.shop_longitude !== null && s.shop_latitude !== undefined && s.shop_longitude !== undefined ? (
          <p>
            <a
              href={`https://www.openstreetmap.org/?mlat=${s.shop_latitude}&mlon=${s.shop_longitude}#map=18/${s.shop_latitude}/${s.shop_longitude}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-12 items-center font-semibold underline"
            >
              {t.store.directions}
            </a>
          </p>
        ) : null}
        <p className="text-sm text-slate">
          {fill(t.store.memberSince, { date: formatDateTime(s.member_since, lang) })} · {fill(t.store.completed, { count: s.completed_orders })}
        </p>
        {s.description ? <p className="max-w-prose">{s.description}</p> : null}
        <ReportForm target={{ type: "store", slug: s.slug }} t={reportText} />
      </header>

      {checks.length ? (
        <section aria-labelledby="checked" className="rounded-card border border-line bg-white p-4">
          <h2 id="checked" className="mb-2 font-bold">{t.store.checked}</h2>
          <ul className="grid gap-1 sm:grid-cols-2">
            {checks.map((key) => (
              <li key={key} className="flex items-center gap-2">
                <svg aria-hidden="true" viewBox="0 0 16 16" className="h-4 w-4 text-highland"><path d="M3 8l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
                {t.store[`check_${key}` as keyof Messages["store"]] ?? key}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <dl className="grid gap-3 sm:grid-cols-3">
        {[
          [t.store.hours, s.working_hours],
          [t.store.areas, s.areas_served.join(", ")],
          [t.store.returns, s.return_policy],
        ].filter(([, value]) => value).map(([label, value]) => (
          <div key={label} className="rounded-card border border-line bg-white p-3">
            <dt className="text-sm text-slate">{label}</dt>
            <dd className="font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="offers" className="space-y-3">
        <h2 id="offers" className="text-lg font-bold">{t.store.offers}</h2>
        {(offers.data ?? []).length === 0 ? <p className="text-slate">{t.store.noOffers}</p> : null}
        <ul className="grid gap-3 sm:grid-cols-2">
          {(offers.data ?? []).map((offer) => (
            <li key={offer.id}>
              <Link href={`/${lang}/p/${offer.product_slug}`} className="flex h-full flex-col gap-1 rounded-card border border-line bg-white p-4 hover:border-ink">
                <span className="font-semibold">{offer.product_name}</span>
                <span className="text-sm text-slate">{offer.variant_label} · {t.condition[offer.condition as keyof Messages["condition"]] ?? offer.condition}</span>
                {offer.in_stock ? <span className="price">{formatPrice(offer.price_santim, lang)}</span> : <span className="font-semibold text-clay">{t.card.outOfStock}</span>}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="reviews" className="space-y-3">
        <h2 id="reviews" className="text-lg font-bold">{t.reviews.storeTitle}</h2>
        {reviews.data ? <RatingSummary summary={reviews.data.summary} t={t} /> : null}
        {shown.length ? (
          <ul className="space-y-3">
            {shown.map((review) => (
              <ReviewItem
                key={review.id}
                review={review}
                lang={lang}
                t={t}
                shopName={s.name}
                linkShop={false}
                report={<ReportForm target={{ type: "review", id: review.id }} t={reportText} />}
              />
            ))}
          </ul>
        ) : null}
        <p className="flex flex-wrap gap-4">
          {before ? <Link href={`/${lang}/s/${s.slug}#reviews`} className="inline-flex min-h-12 items-center font-semibold underline">{t.reviews.newest}</Link> : null}
          {shown.length === REVIEWS_PER_PAGE ? (
            <Link href={`/${lang}/s/${s.slug}?reviews=${shown[shown.length - 1]?.id}#reviews`} className="inline-flex min-h-12 items-center font-semibold underline">{t.reviews.older}</Link>
          ) : null}
        </p>
      </section>
    </div>
  );
}
