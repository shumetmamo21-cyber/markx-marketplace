import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CheckInButton } from "@/components/CheckInButton";
import { SellerOfferRow } from "@/components/SellerOfferRow";
import { serverApi } from "@/lib/api/server";
import { timeAgo } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

export default async function SellerOffersPage({ params }: PageProps<"/[lang]/seller/[sellerId]/offers">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const path = { params: { path: { seller_id: sellerId } } };
  const [offers, dashboard] = await Promise.all([
    api.GET("/api/v1/seller/{seller_id}/offers", { params: { path: { seller_id: sellerId }, query: { lang } } }),
    api.GET("/api/v1/seller/{seller_id}/dashboard", path),
  ]);
  const s = t.seller;
  const d = dashboard.data;
  const list = offers.data ?? [];
  const rowText = { seller: s, condition: t.condition, apiErrors: t.apiErrors };
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{s.offersTitle}</h1>
      {d ? <p className="text-slate">{fill(s.counts, { active: d.active_offers, paused: d.paused_offers, stale: d.prices_to_confirm, low: d.low_stock_offers })}</p> : null}
      <CheckInButton sellerId={sellerId} label={s.checkIn} doneText={s.checkedIn} />
      {list.length === 0 ? <p className="text-slate">{s.noOffers}</p> : null}
      <ul className="space-y-3">
        {list.map((offer) => (
          <SellerOfferRow
            key={offer.id}
            sellerId={sellerId}
            offer={offer}
            t={rowText}
            confirmedText={fill(s.confirmedAgo, { ago: timeAgo(offer.price_confirmed_at, lang) })}
          />
        ))}
      </ul>
    </div>
  );
}
