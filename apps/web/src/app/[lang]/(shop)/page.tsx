import Link from "next/link";
import { notFound } from "next/navigation";

import { ProductCard } from "@/components/ProductCard";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { isLite } from "@/lib/lite-server";
import { getMessages } from "@/lib/messages";

// Blueprint I.5: search first, category shortcuts, popular products, three
// lines on buyer protection. No banner carousel.
export default async function HomePage({ params }: PageProps<"/[lang]">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const [t, lite] = await Promise.all([getMessages(lang), isLite()]);
  const api = await serverApi();
  const [categories, popular] = await Promise.all([
    api.GET("/api/v1/catalog/categories", { params: { query: { lang } } }),
    api.GET("/api/v1/search", { params: { query: { lang, limit: 8, in_stock: true } } }),
  ]);
  const shortcuts = (categories.data ?? []).flatMap((node) => [node, ...node.children]);

  return (
    <div className="space-y-10">
      <section className="space-y-2 pt-2">
        <h1 className="text-2xl font-extrabold leading-tight md:text-3xl">{t.home.heading}</h1>
        <p className="max-w-prose text-slate">{t.home.lead}</p>
      </section>

      {shortcuts.length ? (
        <section aria-labelledby="categories" className="space-y-3">
          <h2 id="categories" className="text-lg font-bold">{t.home.categories}</h2>
          <ul className="flex flex-wrap gap-2">
            {shortcuts.map((category) => (
              <li key={category.id}>
                <Link
                  href={`/${lang}/c/${category.slug}`}
                  className="inline-flex min-h-12 items-center rounded-full border border-line bg-white px-4 font-semibold hover:border-ink"
                >
                  {category.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="popular" className="space-y-3">
        <h2 id="popular" className="text-lg font-bold">{t.home.popular}</h2>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(popular.data?.results ?? []).map((card) => (
            <li key={card.product_id}>
              <ProductCard card={card} lang={lang} t={t} lite={lite} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="protection" className="rounded-card border border-line bg-white p-5">
        <h2 id="protection" className="mb-3 text-lg font-bold">{t.home.protectionTitle}</h2>
        <ul className="space-y-2">
          {[t.home.protection1, t.home.protection2, t.home.protection3].map((line) => (
            <li key={line} className="flex gap-2">
              <svg aria-hidden="true" viewBox="0 0 16 16" className="mt-1 h-4 w-4 shrink-0 text-highland"><path d="M3 8l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
