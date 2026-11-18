import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ProductCard } from "@/components/ProductCard";
import { ProductRequestForm } from "@/components/ProductRequestForm";
import { serverApi } from "@/lib/api/server";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

const PAGE_SIZE = 20;
const SORTS = ["relevance", "price", "freshness"] as const;
type Sort = (typeof SORTS)[number];

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

export async function generateMetadata({ params, searchParams }: PageProps<"/[lang]/search">): Promise<Metadata> {
  const { lang } = await params;
  const q = one((await searchParams).q);
  if (!isLocale(lang)) return {};
  const t = await getMessages(lang);
  return { title: q || t.search.label, robots: { index: false } };
}

export default async function SearchPage({ params, searchParams }: PageProps<"/[lang]/search">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const raw = await searchParams;
  const t = await getMessages(lang);
  const q = one(raw.q).slice(0, 100);
  const category = one(raw.category);
  const condition = one(raw.condition);
  const maxBirr = Number.parseInt(one(raw.max), 10);
  const inStock = one(raw.stock) === "1";
  const rating = ["3", "4"].includes(one(raw.rating)) ? one(raw.rating) : "";
  const level = ["1", "2", "3"].includes(one(raw.level)) ? one(raw.level) : "";
  const sortValue = one(raw.sort);
  const sort: Sort = (SORTS as readonly string[]).includes(sortValue) ? (sortValue as Sort) : "relevance";
  const page = Math.max(1, Number.parseInt(one(raw.page), 10) || 1);

  const api = await serverApi();
  const [found, categories] = await Promise.all([
    api.GET("/api/v1/search", {
      params: {
        query: {
          q, lang, sort, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE,
          category: category || undefined,
          condition: condition || undefined,
          max_price: Number.isFinite(maxBirr) && maxBirr > 0 ? maxBirr * 100 : undefined,
          in_stock: inStock,
          min_rating: rating ? Number(rating) : undefined,
          min_level: level ? Number(level) : undefined,
        },
      },
    }),
    api.GET("/api/v1/catalog/categories", { params: { query: { lang } } }),
  ]);
  if (found.response.status === 404) notFound();
  const result = found.data;
  if (!result) throw new Error("search failed");
  const options = (categories.data ?? []).flatMap((node) => [node, ...node.children]);

  const pageLink = (target: number) => {
    const next = new URLSearchParams();
    for (const [key, value] of Object.entries({ q, category, condition, max: one(raw.max), stock: inStock ? "1" : "", rating, level, sort: sort === "relevance" ? "" : sort })) {
      if (value) next.set(key, value);
    }
    if (target > 1) next.set("page", String(target));
    return `/${lang}/search?${next.toString()}`;
  };
  const heading = q ? fill(t.search.results, { count: result.total, query: q }) : fill(t.search.resultsAll, { count: result.total });

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold" aria-live="polite">{heading}</h1>

      <details className="rounded-card border border-line bg-white" open={Boolean(category || condition || inStock || one(raw.max) || rating || level)}>
        <summary className="flex min-h-12 cursor-pointer items-center px-4 font-semibold">{t.search.filters}</summary>
        <form method="get" action={`/${lang}/search`} className="grid gap-4 border-t border-line p-4 sm:grid-cols-2 lg:grid-cols-4">
          <input type="hidden" name="q" value={q} />
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{t.search.category}</span>
            <select name="category" defaultValue={category} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
              <option value="">{t.search.anyCategory}</option>
              {options.map((option) => (
                <option key={option.id} value={option.slug}>{option.name}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{t.search.condition}</span>
            <select name="condition" defaultValue={condition} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
              <option value="">{t.search.anyCondition}</option>
              {(["new", "used", "refurbished"] as const).map((value) => (
                <option key={value} value={value}>{t.condition[value]}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{t.search.maxPrice}</span>
            <input name="max" type="number" min={1} inputMode="numeric" defaultValue={one(raw.max)} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
          </label>
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{t.search.rating}</span>
            <select name="rating" defaultValue={rating} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
              <option value="">{t.search.anyRating}</option>
              {["4", "3"].map((stars) => <option key={stars} value={stars}>{fill(t.search.ratingAtLeast, { stars })}</option>)}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{t.search.sellerLevel}</span>
            <select name="level" defaultValue={level} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
              <option value="">{t.search.anyLevel}</option>
              {["1", "2", "3"].map((value) => <option key={value} value={value}>{fill(t.search.levelAtLeast, { level: value })}</option>)}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{t.search.sort}</span>
            <select name="sort" defaultValue={sort} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
              <option value="relevance">{t.search.sortRelevance}</option>
              <option value="price">{t.search.sortPrice}</option>
              <option value="freshness">{t.search.sortFreshness}</option>
            </select>
          </label>
          <div className="flex flex-col justify-end gap-3">
            <label className="flex min-h-12 items-center gap-2">
              <input type="checkbox" name="stock" value="1" defaultChecked={inStock} className="h-5 w-5" />
              <span>{t.search.inStock}</span>
            </label>
          </div>
          <div className="flex gap-3 sm:col-span-2 lg:col-span-4">
            <button type="submit" className="min-h-12 rounded-card bg-adey px-5 font-bold">{t.search.apply}</button>
            <Link href={`/${lang}/search${q ? `?q=${encodeURIComponent(q)}` : ""}`} className="inline-flex min-h-12 items-center px-3 font-semibold underline">
              {t.search.clear}
            </Link>
          </div>
        </form>
      </details>

      {result.results.length ? (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {result.results.map((card) => (
            <li key={card.product_id}>
              <ProductCard card={card} lang={lang} t={t} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="space-y-6">
          <div className="space-y-2">
            <p className="font-semibold">{fill(t.search.noResults, { query: q })}</p>
            <p className="text-slate">{t.search.tryAgain}</p>
          </div>
          {result.did_you_mean.length ? (
            <section aria-labelledby="dym" className="space-y-3">
              <h2 id="dym" className="font-bold">{t.search.didYouMean}</h2>
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {result.did_you_mean.map((card) => (
                  <li key={card.product_id}><ProductCard card={card} lang={lang} t={t} /></li>
                ))}
              </ul>
            </section>
          ) : null}
          {q ? (
            <section aria-labelledby="request" className="max-w-lg space-y-3 rounded-card border border-line bg-white p-5">
              <h2 id="request" className="font-bold">{t.search.requestTitle}</h2>
              <p className="text-slate">{t.search.requestBody}</p>
              <ProductRequestForm query={q} t={t.search} />
            </section>
          ) : null}
        </div>
      )}

      {result.total > PAGE_SIZE ? (
        <nav className="flex justify-between" aria-label={t.search.label}>
          {page > 1 ? <Link href={pageLink(page - 1)} className="inline-flex min-h-12 items-center font-semibold underline">{t.search.previous}</Link> : <span />}
          {page * PAGE_SIZE < result.total ? <Link href={pageLink(page + 1)} className="inline-flex min-h-12 items-center font-semibold underline">{t.search.next}</Link> : null}
        </nav>
      ) : null}
    </div>
  );
}
