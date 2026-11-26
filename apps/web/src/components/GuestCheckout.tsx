"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { formatPrice } from "@/lib/format";
import { type GuestForm, guestDeliveryOptions, guestDetails, guestErrorText, trackPageHref } from "@/lib/guest-checkout";
import { fill, type Locale, type Messages } from "@/lib/i18n";
import { noticeReady } from "@/lib/order-notice";

import { OrderNotice } from "./OrderNotice";
import { ProblemNotice } from "./Resilience";
import { GUEST_CHECKOUT_ACTION, TurnstileWidget } from "./TurnstileWidget";

type Schemas = components["schemas"];
type Zone = Schemas["ZoneOut"];
type Cart = Schemas["CartOut"];
type Quote = Schemas["QuoteOut"];
type Terms = Schemas["GuestCheckoutTermsOut"];
type Method = Schemas["DeliveryChoiceIn"]["method"];
type Payment = Schemas["GuestCheckoutIn"]["payment_method"];

const PAYMENTS: Payment[] = ["cash", "telebirr", "bank_transfer", "ethqr"];
const EMPTY: GuestForm = { recipient: "", phone: "", area: "", landmark: "", notes: "" };

function newKey(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

// Guest checkout (C-07, D-108): four short steps in one column, like the
// signed-in checkout. The guest types a name, a delivery address and a phone
// number; the API prices everything, checks every limit and the bot check,
// and answers with the order's code and its secure tracking link, which is
// all a guest gets. Nothing is saved in the browser but the cart MarkX
// already keeps; the link is shown once, to keep.
export function GuestCheckout({ lang, t, zones, terms, siteKey }: {
  lang: Locale;
  t: Pick<Messages, "guest" | "checkout" | "cart" | "apiErrors">;
  zones: Zone[];
  terms: Terms;
  siteKey?: string;
}) {
  const g = t.guest;
  const c = t.checkout;
  const [form, setForm] = useState<GuestForm>(EMPTY);
  const [cart, setCart] = useState<Cart | null>(null);
  const [cartFailed, setCartFailed] = useState("");
  const [methods, setMethods] = useState<Record<string, Method>>({});
  const [payment, setPayment] = useState<Payment>("cash");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [key, setKey] = useState(newKey);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ code: string; text: string; retry?: () => void } | null>(null);
  // The bot check's one-time token. Read from the ref when sending, so a
  // "try again" never sends a token an earlier attempt used up.
  const token = useRef<string | null>(null);
  const [botReset, setBotReset] = useState(0);
  const [placed, setPlaced] = useState<{ code: string; href: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const zoneCode = useMemo(() => zones.find((z) => z.areas.some((a) => a.id === form.area))?.code, [zones, form.area]);

  const showCart = useCallback(
    (data: Cart) => {
      setCart(data);
      setMethods(
        Object.fromEntries(
          data.groups.map((group) => [
            group.store_slug,
            (guestDeliveryOptions(group.delivery_options, terms.shop_collection)[0]?.method ?? "seller_rider") as Method,
          ]),
        ),
      );
    },
    [terms.shop_collection],
  );

  const loadCart = useCallback(async () => {
    if (!zoneCode) return;
    const { data, error } = await browserApi.GET("/api/v1/cart", { params: { query: { lang, zone: zoneCode } } });
    if (data) {
      setCartFailed("");
      showCart(data);
    } else setCartFailed(errorCode(error));
  }, [lang, zoneCode, showCart]);

  // The delivery choices depend on the area's zone: read them again when it changes.
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

  const edit = (field: keyof GuestForm) => (event: { target: { value: string } }) => {
    const value = event.target.value;
    setForm((current) => ({ ...current, [field]: value }));
    setQuote(null);
  };
  const deliveries = () => Object.entries(methods).map(([store_slug, method]) => ({ store_slug, method }));

  const review = async () => {
    setBusy(true);
    setProblem(null);
    const { data, error } = await browserApi.POST("/api/v1/checkout/guest/quote", {
      params: { query: { lang } },
      body: { guest: guestDetails(form), deliveries: deliveries() },
    });
    setBusy(false);
    if (error || !data) {
      const code = errorCode(error);
      return setProblem({ code, text: guestErrorText(t, code), retry: () => void review() });
    }
    setQuote(data);
    setKey(newKey());
  };

  const place = async () => {
    if (!quote) return;
    const botToken = token.current;
    if (siteKey && !botToken) return setProblem({ code: "bot_check", text: g.botCheck });
    setBusy(true);
    setProblem(null);
    const { data, error } = await browserApi.POST("/api/v1/checkout/guest", {
      params: { query: { lang } },
      body: {
        guest: guestDetails(form),
        deliveries: deliveries(),
        payment_method: payment,
        expected_total_santim: quote.grand_total_santim,
        idempotency_key: key,
        ...(botToken ? { bot_token: botToken } : {}),
      },
    });
    // A token is good once: ask for a fresh one whatever the answer.
    if (siteKey) {
      token.current = null;
      setBotReset((n) => n + 1);
    }
    setBusy(false);
    if (data) {
      setPlaced({ code: data.order_code, href: trackPageHref(data.tracking_path, lang) ?? "" });
      return;
    }
    const code = errorCode(error);
    if (code === "total_changed" || code === "price_changed") {
      setQuote(null);
      setProblem({ code, text: c.totalChanged });
      await loadCart();
    } else {
      // The same idempotency key is kept, so trying again after a dropped
      // connection can never place the order twice (G.5, D-100).
      setProblem({ code, text: guestErrorText(t, code), retry: () => void place() });
    }
  };

  if (placed) {
    const link = placed.href && typeof window !== "undefined" ? new URL(placed.href, window.location.origin).toString() : placed.href;
    return (
      <section className="space-y-4 rounded-card border border-ink bg-white p-4" aria-labelledby="guest-placed">
        <h2 id="guest-placed" className="text-lg font-bold">{fill(g.placed, { code: placed.code })}</h2>
        <p role="status" className="font-semibold">{g.saveLink}</p>
        <p className="break-all rounded-card border border-line bg-paper p-3 text-sm" data-guest-link="">{link}</p>
        <div className="flex flex-wrap gap-3">
          <a href={placed.href} className="inline-flex min-h-12 items-center rounded-card bg-adey px-5 font-bold">{g.openOrder}</a>
          <button
            type="button"
            className="min-h-12 rounded-card border border-ink px-4 font-semibold"
            onClick={() => {
              void navigator.clipboard?.writeText(link).then(() => setCopied(true), () => setCopied(false));
            }}
          >
            {g.copyLink}
          </button>
        </div>
        {copied ? <p role="status" className="text-sm font-semibold">{g.copied}</p> : null}
        <p className="text-sm text-slate">{c.next}</p>
      </section>
    );
  }

  const area = form.area;
  return (
    <div className="space-y-6">
      <section className="space-y-3 rounded-card border border-line bg-white p-4" aria-labelledby="guest-step1">
        <h2 id="guest-step1" className="font-bold">{g.step1}</h2>
        <label className="block space-y-1">
          <span className="block text-sm font-semibold">{g.name}</span>
          <input name="recipient" autoComplete="name" required value={form.recipient} onChange={edit("recipient")} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
        </label>
        <label className="block space-y-1">
          <span className="block text-sm font-semibold">{g.phone}</span>
          <input name="phone" type="tel" inputMode="tel" autoComplete="tel" required value={form.phone} onChange={edit("phone")} aria-describedby="guest-phone-hint" className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
          <span id="guest-phone-hint" className="block text-sm text-slate">{g.phoneHint}</span>
        </label>
        <label className="block space-y-1">
          <span className="block text-sm font-semibold">{c.area}</span>
          <select name="area" required value={area} onChange={edit("area")} className="min-h-12 w-full rounded-card border border-line bg-white px-3">
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
        <label className="block space-y-1">
          <span className="block text-sm font-semibold">{c.landmark}</span>
          <input name="landmark" required minLength={3} value={form.landmark} onChange={edit("landmark")} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
        </label>
        <label className="block space-y-1">
          <span className="block text-sm font-semibold">{c.notes}</span>
          <input name="notes" value={form.notes} onChange={edit("notes")} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
        </label>
        <p className="text-sm text-slate">{g.noAccount}</p>
      </section>

      {!area ? <p className="text-sm text-slate">{g.chooseAreaFirst}</p> : null}
      {area && !cart && cartFailed ? <ProblemNotice code={cartFailed} text={t.cart.failed} retry={() => void loadCart()} /> : null}

      {cart && area ? (
        <section className="space-y-3 rounded-card border border-line bg-white p-4" aria-labelledby="guest-step2">
          <h2 id="guest-step2" className="font-bold">{g.step2}</h2>
          {!cart.line_count ? <p>{g.emptyCart}</p> : null}
          {!terms.shop_collection ? <p className="text-sm text-slate">{g.doorOnly}</p> : null}
          {cart.groups.map((group) => {
            const options = guestDeliveryOptions(group.delivery_options, terms.shop_collection);
            return (
              <fieldset key={group.store_slug} className="space-y-2">
                <legend className="font-semibold">{group.store_name}</legend>
                {options.length ? null : <p className="text-sm text-clay">{g.noDoorDelivery}</p>}
                {options.map((option) => (
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
            );
          })}
        </section>
      ) : null}

      {cart && area && cart.line_count ? (
        <section className="space-y-3 rounded-card border border-line bg-white p-4" aria-labelledby="guest-step3">
          <h2 id="guest-step3" className="font-bold">{g.step3}</h2>
          <div className="grid grid-cols-2 gap-2">
            {PAYMENTS.map((value) => (
              <label key={value} className="flex min-h-12 items-center gap-3 rounded-card border border-line px-3">
                <input type="radio" name="payment" className="h-5 w-5" checked={payment === value} onChange={() => setPayment(value)} />
                {c[`pay_${value}` as "pay_cash"]}
              </label>
            ))}
          </div>
          <p className="text-sm text-slate">{c.payNote}</p>
          <p className="text-sm text-slate">{fill(g.limit, { amount: formatPrice(terms.max_order_value_santim, lang) })}</p>
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
        <section className="space-y-3 rounded-card border border-ink bg-white p-4" aria-labelledby="guest-step4">
          <h2 id="guest-step4" className="font-bold">{g.step4}</h2>
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
          <OrderNotice notice={quote.notice} id="guest-step4-notice" />
          {siteKey ? (
            <TurnstileWidget
              siteKey={siteKey}
              resetKey={botReset}
              action={GUEST_CHECKOUT_ACTION}
              onToken={(value) => {
                token.current = value;
              }}
            />
          ) : null}
          <button type="button" disabled={busy || !noticeReady(quote.notice)} onClick={place} className="min-h-12 w-full rounded-card bg-adey text-lg font-bold disabled:opacity-60">
            {busy ? c.placing : c.place}
          </button>
        </section>
      ) : null}
    </div>
  );
}
