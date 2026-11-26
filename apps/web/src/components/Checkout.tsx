"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { formatPrice } from "@/lib/format";
import { apiErrorText, fill, type Locale, type Messages } from "@/lib/i18n";
import { noticeReady } from "@/lib/order-notice";

import { OrderNotice } from "./OrderNotice";
import { ProblemNotice } from "./Resilience";

type Schemas = components["schemas"];
type Address = Schemas["AddressOut"];
type Zone = Schemas["ZoneOut"];
type Cart = Schemas["CartOut"];
type Quote = Schemas["QuoteOut"];
type Method = Schemas["DeliveryChoiceIn"]["method"];
type Payment = Schemas["CheckoutIn"]["payment_method"];

const PAYMENTS: Payment[] = ["cash", "telebirr", "bank_transfer", "ethqr"];

function newKey(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

// Four short steps in one column (blueprint I.5). The browser never sends a
// price: it sends what and where, the server prices it, and the order is
// placed with the total the buyer saw, which the server compares (G.5).
export function Checkout({ lang, t, addresses: initial, zones }: { lang: Locale; t: Pick<Messages, "checkout" | "cart" | "apiErrors">; addresses: Address[]; zones: Zone[] }) {
  const c = t.checkout;
  const router = useRouter();
  const [addresses, setAddresses] = useState(initial);
  const [addressId, setAddressId] = useState(initial[0]?.id ?? "");
  const [adding, setAdding] = useState(initial.length === 0);
  const [cart, setCart] = useState<Cart | null>(null);
  const [methods, setMethods] = useState<Record<string, Method>>({});
  const [payment, setPayment] = useState<Payment>("cash");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [key, setKey] = useState(newKey);
  const [busy, setBusy] = useState(false);
  // What went wrong, in words, and (for a dropped connection) how to try again.
  const [problem, setProblem] = useState<{ code: string; text: string; retry?: () => void } | null>(null);
  // The cart (and so the delivery choices) could not be read.
  const [cartFailed, setCartFailed] = useState("");

  const zoneCode = useMemo(() => {
    const address = addresses.find((a) => a.id === addressId);
    return zones.find((z) => z.id === address?.zone_id)?.code;
  }, [addresses, addressId, zones]);

  const showCart = useCallback((data: Cart) => {
    setCart(data);
    setMethods(Object.fromEntries(data.groups.map((g) => [g.store_slug, (g.delivery_options?.[0]?.method ?? "shop_collection") as Method])));
  }, []);

  const loadCart = useCallback(async () => {
    if (!zoneCode) return;
    const { data, error } = await browserApi.GET("/api/v1/cart", { params: { query: { lang, zone: zoneCode } } });
    if (data) {
      setCartFailed("");
      showCart(data);
    } else setCartFailed(errorCode(error));
  }, [lang, zoneCode, showCart]);

  // The delivery choices depend on the address's zone: read them again when it changes.
  useEffect(() => {
    if (!zoneCode) return;
    let live = true;
    browserApi.GET("/api/v1/cart", { params: { query: { lang, zone: zoneCode } } }).then(({ data, error }) => {
      if (!live) return;
      if (data) {
        setCartFailed("");
        showCart(data);
      } else setCartFailed(errorCode(error));
    });
    return () => {
      live = false;
    };
  }, [lang, zoneCode, showCart]);

  const chooseAddress = (id: string) => {
    setAddressId(id);
    setQuote(null);
  };

  const review = async () => {
    setBusy(true);
    setProblem(null);
    const deliveries = Object.entries(methods).map(([store_slug, method]) => ({ store_slug, method }));
    const { data, error } = await browserApi.POST("/api/v1/checkout/quote", { params: { query: { lang } }, body: { address_id: addressId, deliveries } });
    setBusy(false);
    if (error || !data) {
      const code = errorCode(error);
      return setProblem({ code, text: apiErrorText(t, code), retry: () => void review() });
    }
    setQuote(data);
    setKey(newKey());
  };

  const place = async () => {
    if (!quote) return;
    setBusy(true);
    setProblem(null);
    const deliveries = Object.entries(methods).map(([store_slug, method]) => ({ store_slug, method }));
    const { data, error } = await browserApi.POST("/api/v1/checkout", {
      params: { query: { lang } },
      body: { address_id: addressId, deliveries, payment_method: payment, expected_total_santim: quote.grand_total_santim, idempotency_key: key },
    });
    if (data) {
      router.push(`/${lang}/orders/${data.id}`);
      return;
    }
    setBusy(false);
    const code = errorCode(error);
    if (code === "total_changed" || code === "price_changed") {
      setQuote(null);
      setProblem({ code, text: c.totalChanged });
      await loadCart();
    } else {
      // The same idempotency key is kept, so trying again after a dropped
      // connection can never place the order twice (G.5, D-100).
      setProblem({ code, text: apiErrorText(t, code), retry: () => void place() });
    }
  };

  const area = (a: Address) => (lang === "am" ? a.area_name_am : a.area_name_en);

  return (
    <div className="space-y-6">
      <section className="space-y-3 rounded-card border border-line bg-white p-4" aria-labelledby="step1">
        <h2 id="step1" className="font-bold">{c.step1}</h2>
        {addresses.length ? (
          <fieldset className="space-y-2">
            <legend className="sr-only">{c.step1}</legend>
            {addresses.map((a) => (
              <label key={a.id} className="flex min-h-12 items-start gap-3 rounded-card border border-line p-3">
                <input type="radio" name="address" className="mt-1 h-5 w-5" checked={a.id === addressId} onChange={() => chooseAddress(a.id)} />
                <span>
                  <span className="block font-semibold">{a.recipient_name} · {area(a)}</span>
                  <span className="block text-sm text-slate">{a.landmark}</span>
                </span>
              </label>
            ))}
          </fieldset>
        ) : null}
        {adding ? (
          <NewAddress
            lang={lang}
            t={t}
            zones={zones}
            onSaved={(address) => {
              setAddresses((list) => [...list, address]);
              chooseAddress(address.id);
              setAdding(false);
            }}
          />
        ) : (
          <button type="button" onClick={() => setAdding(true)} className="min-h-12 font-semibold underline">{c.newAddress}</button>
        )}
      </section>

      {!cart && addressId && cartFailed ? (
        <div className="space-y-2">
          <ProblemNotice code={cartFailed} text={t.cart.failed} retry={() => void loadCart()} />
        </div>
      ) : null}

      {cart && addressId ? (
        <section className="space-y-3 rounded-card border border-line bg-white p-4" aria-labelledby="step2">
          <h2 id="step2" className="font-bold">{c.step2}</h2>
          {cart.groups.map((group) => (
            <fieldset key={group.store_slug} className="space-y-2">
              <legend className="font-semibold">{group.store_name}</legend>
              {(group.delivery_options ?? []).map((option) => (
                <label key={option.method} className="flex min-h-12 items-center gap-3 rounded-card border border-line px-3">
                  <input
                    type="radio"
                    name={`delivery-${group.store_slug}`}
                    className="h-5 w-5"
                    checked={methods[group.store_slug] === option.method}
                    onChange={() => {
                      setMethods((m) => ({ ...m, [group.store_slug]: option.method as Method }));
                      setQuote(null);
                    }}
                  />
                  <span className="flex-1">
                    {c[`method_${option.method}` as "method_seller_rider"] ?? option.method}
                    {option.promised_hours ? <span className="text-sm text-slate"> · {fill(c.hours, { hours: option.promised_hours })}</span> : null}
                  </span>
                  <span className="price">{formatPrice(option.fee_santim, lang)}</span>
                </label>
              ))}
            </fieldset>
          ))}
        </section>
      ) : null}

      {cart && addressId ? (
        <section className="space-y-3 rounded-card border border-line bg-white p-4" aria-labelledby="step3">
          <h2 id="step3" className="font-bold">{c.step3}</h2>
          <div className="grid grid-cols-2 gap-2">
            {PAYMENTS.map((value) => (
              <label key={value} className="flex min-h-12 items-center gap-3 rounded-card border border-line px-3">
                <input type="radio" name="payment" className="h-5 w-5" checked={payment === value} onChange={() => setPayment(value)} />
                {c[`pay_${value}` as "pay_cash"]}
              </label>
            ))}
          </div>
          <p className="text-sm text-slate">{c.payNote}</p>
          {!quote ? (
            <button type="button" disabled={busy} onClick={review} className="min-h-12 w-full rounded-card bg-ink font-bold text-paper disabled:opacity-60">
              {busy ? c.reviewing : c.review}
            </button>
          ) : null}
        </section>
      ) : null}

      {problem ? (
        <div className="space-y-2">
          <ProblemNotice code={problem.code} text={problem.text} retry={problem.retry} busy={busy} />
        </div>
      ) : null}

      {quote ? (
        <section className="space-y-3 rounded-card border border-ink bg-white p-4" aria-labelledby="step4">
          <h2 id="step4" className="font-bold">{c.step4}</h2>
          {quote.groups.map((group) => (
            <div key={group.store_slug} className="space-y-1 border-b border-line pb-3">
              <p className="font-semibold">{group.store_name}</p>
              <p className="text-sm text-slate">{fill(c.seller, { legal: group.seller_legal_name, address: group.shop_address })}</p>
              {group.return_policy ? <p className="text-sm text-slate">{fill(c.returns, { policy: group.return_policy })}</p> : null}
              <p className="flex justify-between text-sm"><span>{t.cart.itemsTotal}</span><span className="price">{formatPrice(group.items_total_santim, lang)}</span></p>
              <p className="flex justify-between text-sm"><span>{c.delivery}</span><span className="price">{formatPrice(group.delivery_fee_santim, lang)}</span></p>
              <p className="flex justify-between"><span>{c.total}</span><span className="price">{formatPrice(group.total_santim, lang)}</span></p>
            </div>
          ))}
          <p className="flex justify-between text-lg"><span className="font-bold">{c.grandTotal}</span><span className="price">{formatPrice(quote.grand_total_santim, lang)}</span></p>
          <p className="text-sm text-slate">{c.next}</p>
          <OrderNotice notice={quote.notice} id="step4-notice" />
          <button type="button" disabled={busy || !noticeReady(quote.notice)} onClick={place} className="min-h-12 w-full rounded-card bg-adey text-lg font-bold disabled:opacity-60">
            {busy ? c.placing : c.place}
          </button>
        </section>
      ) : null}
    </div>
  );
}

export function NewAddress({ lang, t, zones, onSaved }: { lang: Locale; t: Pick<Messages, "checkout" | "apiErrors">; zones: Zone[]; onSaved: (address: Address) => void }) {
  const c = t.checkout;
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<{ code: string; text: string } | null>(null);
  return (
    <form
      className="grid gap-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const text = (name: string) => String(form.get(name) ?? "").trim();
        setBusy(true);
        setFailed(null);
        const { data, error } = await browserApi.POST("/api/v1/me/addresses", {
          body: {
            recipient_name: text("recipient"),
            phone: text("phone"),
            delivery_area_id: text("area"),
            landmark: text("landmark"),
            driver_notes: text("notes") || null,
          },
        });
        setBusy(false);
        if (error || !data) {
          const code = errorCode(error);
          return setFailed({ code, text: apiErrorText(t, code) });
        }
        onSaved(data);
      }}
    >
      {[
        ["recipient", c.recipient, "text", "name"],
        ["phone", c.phone, "tel", "tel"],
      ].map(([name, label, type, auto]) => (
        <label key={name} className="space-y-1">
          <span className="block text-sm font-semibold">{label}</span>
          <input name={name} type={type} autoComplete={auto} required className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
        </label>
      ))}
      <label className="space-y-1">
        <span className="block text-sm font-semibold">{c.area}</span>
        <select name="area" required defaultValue="" className="min-h-12 w-full rounded-card border border-line bg-white px-3">
          <option value="" disabled>{c.chooseArea}</option>
          {zones.map((zone) => (
            <optgroup key={zone.id} label={lang === "am" ? zone.name_am : zone.name_en}>
              {zone.areas.filter((a) => a.is_active).map((a) => (
                <option key={a.id} value={a.id}>{lang === "am" ? a.name_am : a.name_en}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <label className="space-y-1">
        <span className="block text-sm font-semibold">{c.landmark}</span>
        <input name="landmark" required minLength={3} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
      </label>
      <label className="space-y-1">
        <span className="block text-sm font-semibold">{c.notes}</span>
        <input name="notes" className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
      </label>
      {failed ? <ProblemNotice code={failed.code} text={failed.text} retry="submit" busy={busy} className="text-clay" /> : null}
      <button type="submit" disabled={busy} className="min-h-12 rounded-card bg-ink font-bold text-paper disabled:opacity-60">{c.saveAddress}</button>
    </form>
  );
}
