import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ProductCard } from "@/components/ProductCard";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

async function load(lang: "am" | "en", slug: string) {
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) notFound();
  const api = await serverApi();
  const { data } = await api.GET("/api/v1/catalog/categories/{slug}", { params: { path: { slug }, query: { lang } } });
  if (!data) notFound();
  return data;
}

export async function generateMetadata({ params }: PageProps<"/[lang]/c/[slug]">): Promise<Metadata> {
  const { lang, slug } = await params;
  if (!isLocale(lang)) return {};
  return { title: (await load(lang, slug)).name };
}

// A category on its own page (blueprint I.5): where it sits, its
// subcategories, and its products as cards (the API's search, which already
// covers a category's children); filters and sorting live on search.
export default async function CategoryPage({ params }: PageProps<"/[lang]/c/[slug]">) {
  const { lang, slug } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const category = await load(lang, slug);
  const api = await serverApi();
  const { data } = await api.GET("/api/v1/search", { params: { query: { q: "", lang, category: slug, limit: 24 } } });
  const cards = data?.results ?? [];
  return (
    <div className="space-y-5">
      <nav aria-label={t.search.category} className="text-sm text-slate">
        {category.breadcrumbs.map((crumb) => (
          <span key={crumb.id}><Link href={`/${lang}/c/${crumb.slug}`} className="underline">{crumb.name}</Link> / </span>
        ))}
      </nav>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-extrabold">{category.name}</h1>
        <Link href={`/${lang}/search?category=${category.slug}`} className="inline-flex min-h-12 items-center font-semibold underline">{t.search.categoryAll}</Link>
      </div>
      {category.children.length ? (
        <ul className="flex flex-wrap gap-2">
          {category.children.map((child) => (
            <li key={child.id}>
              <Link href={`/${lang}/c/${child.slug}`} className="inline-flex min-h-12 items-center rounded-full border border-line bg-white px-4 font-semibold hover:border-ink">{child.name}</Link>
            </li>
          ))}
        </ul>
      ) : null}
      {cards.length === 0 ? <p className="text-slate">{t.search.categoryEmpty}</p> : null}
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => (
          <li key={card.product_id}><ProductCard card={card} lang={lang} t={t} /></li>
        ))}
      </ul>
    </div>
  );
}
