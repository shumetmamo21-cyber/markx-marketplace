"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { browserApi } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { formatPrice } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";

type Cart = components["schemas"]["CartOut"];
type Item = components["schemas"]["CartItemOut"];

function problemText(t: Messages["cart"], problem: string): string {
  if (problem === "out_of_stock" || problem === "not_enough_stock") return t.problem_out_of_stock;
  if (problem.endsWith("_not_available")) return t.problem_unavailable;
  return t.problemGeneric;
}

// The cart is read and changed in the browser, because the API keeps a
// visitor's cart by a cookie it sets on these very responses (D-036).
export function CartView({ lang, t, conditions }: { lang: Locale; t: Messages["cart"]; conditions: Messages["condition"] }) {
  const [cart, setCart] = useState<Cart | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data, error } = await browserApi.GET("/api/v1/cart", { params: { query: { lang } } });
    if (error || !data) setFailed(true);
    else setCart(data);
  }, [lang]);

  useEffect(() => {
    let live = true;
    browserApi.GET("/api/v1/cart", { params: { query: { lang } } }).then(({ data, error }) => {
      if (!live) return;
      if (error || !data) setFailed(true);
      else setCart(data);
    });
    return () => {
      live = false;
    };
  }, [lang]);

  const change = async (run: () => Promise<{ data?: Cart; error?: unknown }>) => {
    setBusy(true);
    const { data } = await run();
    if (data) setCart(data);
    else await load();
    setBusy(false);
  };

  if (failed) return <p role="alert" className="text-clay">{t.failed}</p>;
  if (!cart) return <p role="status" className="text-slate">{t.loading}</p>;
  if (cart.line_count === 0) {
    return (
      <div className="space-y-4">
        <p>{t.empty}</p>
        <Link href={`/${lang}/search`} className="inline-flex min-h-12 items-center rounded-card bg-adey px-5 font-bold">{t.browse}</Link>
      </div>
    );
  }

  const row = (item: Item) => (
    <li key={item.offer_id} className="flex flex-wrap items-start justify-between gap-3 border-t border-line py-4 first:border-t-0">
      <div className="min-w-0 flex-1 space-y-1">
        <Link href={`/${lang}/p/${item.product_slug}`} className="font-semibold hover:underline">{item.product_name}</Link>
        <p className="text-sm text-slate">
          {[item.variant_label, item.condition in conditions ? conditions[item.condition as keyof typeof conditions] : item.condition].filter(Boolean).join(" · ")}
        </p>
        {item.price_changed ? (
          <p className="text-sm font-semibold text-clay">{fill(t.priceChanged, { before: formatPrice(item.price_seen_santim, lang), after: formatPrice(item.price_santim, lang) })}</p>
        ) : null}
        {item.problem ? <p className="text-sm font-semibold text-clay">{problemText(t, item.problem)}</p> : null}
      </div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">{t.quantity}</span>
          <select
            value={item.quantity}
            disabled={busy}
            onChange={(event) =>
              change(() => browserApi.PUT("/api/v1/cart/items/{offer_id}", {
                params: { path: { offer_id: item.offer_id }, query: { lang } },
                body: { quantity: Number(event.target.value) },
              }))
            }
            className="min-h-12 rounded-card border border-line bg-white px-3"
          >
            {Array.from({ length: Math.max(item.quantity, Math.min(item.available, 20)) }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <span className="price w-28 text-right">{formatPrice(item.line_total_santim, lang)}</span>
        <button
          type="button"
          disabled={busy}
          onClick={() => change(() => browserApi.DELETE("/api/v1/cart/items/{offer_id}", { params: { path: { offer_id: item.offer_id }, query: { lang } } }))}
          className="min-h-12 px-2 text-sm font-semibold underline"
        >
          {t.remove}
        </button>
      </div>
    </li>
  );

  return (
    <div className="space-y-5">
      {cart.has_price_changes ? (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-clay bg-white p-4">
          <p className="font-semibold">{t.changesNotice}</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => change(() => browserApi.POST("/api/v1/cart/accept-changes", { params: { query: { lang } } }))}
            className="min-h-12 rounded-card bg-ink px-4 font-bold text-paper"
          >
            {t.acceptChanges}
          </button>
        </div>
      ) : null}
      <p className="text-sm text-slate">{t.perSeller}</p>
      {cart.groups.map((group) => (
        <section key={group.store_slug} className="rounded-card border border-line bg-white px-4" aria-label={group.store_name}>
          <h2 className="border-b border-line py-3 font-bold">
            <Link href={`/${lang}/s/${group.store_slug}`} className="hover:underline">{fill(t.from, { store: group.store_name })}</Link>
          </h2>
          <ul>{group.items.map(row)}</ul>
        </section>
      ))}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-card border border-ink bg-white p-4">
        <p className="text-lg">
          {t.itemsTotal}: <span className="price">{formatPrice(cart.items_total_santim, lang)}</span>
        </p>
        {cart.can_check_out ? (
          <Link href={`/${lang}/checkout`} className="inline-flex min-h-12 items-center rounded-card bg-adey px-6 font-bold">{t.checkout}</Link>
        ) : null}
      </div>
    </div>
  );
}
