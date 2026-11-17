import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

const STATUSES = ["approved", "draft", "pending_review", "archived", "merged"] as const;

// Every product by its state (AD-02), each opening its own page.
export default async function ProductsPage({ params, searchParams }: PageProps<"/[lang]/admin/products">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const raw = (await searchParams).status;
  const status = STATUSES.find((s) => s === (Array.isArray(raw) ? raw[0] : raw)) ?? "approved";
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/catalog/products", { params: { query: { status, limit: 200, lang } } });
  const a = t.admin;
  if (response.status === 403) return <p role="alert">{a.notAllowed}</p>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">{a.productsTitle}</h1>
        <Link href={`/${lang}/admin/products/new`} className="inline-flex min-h-12 items-center rounded-card bg-adey px-5 font-bold">{a.productNew}</Link>
      </div>
      <ul className="flex flex-wrap gap-2">
        {STATUSES.map((s) => (
          <li key={s}>
            <Link href={`/${lang}/admin/products?status=${s}`} aria-current={s === status ? "page" : undefined} className={`inline-flex min-h-12 items-center rounded-full border px-4 font-semibold ${s === status ? "border-ink bg-ink text-paper" : "border-line bg-white"}`}>
              {codeLabel(t, "productStatus", s)}
            </Link>
          </li>
        ))}
      </ul>
      {(data ?? []).length === 0 ? <p>{a.productsNone}</p> : null}
      <ul className="space-y-2">
        {(data ?? []).map((product) => (
          <li key={product.id}>
            <Link href={`/${lang}/admin/products/${product.id}`} className="flex flex-wrap items-baseline justify-between gap-2 rounded-card border border-line bg-white p-3 hover:border-ink">
              <span className="font-semibold">{product.name} <span className="text-sm font-normal text-slate">({product.slug})</span></span>
              <span className="text-sm text-slate">{product.proposed_by_seller_id ? `${a.proposedByShop} · ` : ""}{formatDateTime(product.created_at, lang)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
