"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { apiErrorText, fill, type Messages } from "@/lib/i18n";

type Offer = components["schemas"]["SellerOfferOut"];

// Quick edit (blueprint I.5): price and stock in place, pause and resume.
// Prices are typed in birr and sent in santim; the API checks the rest.
export function SellerOfferRow({ sellerId, offer, t, confirmedText }: { sellerId: string; offer: Offer; t: Pick<Messages, "seller" | "condition" | "apiErrors">; confirmedText: string }) {
  const s = t.seller;
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const path = { params: { path: { seller_id: sellerId, offer_id: offer.id } } };

  const run = async (call: () => Promise<{ error?: unknown }>) => {
    setBusy(true);
    setNote(null);
    const { error } = await call();
    setBusy(false);
    if (error) {
      setNote({ ok: false, text: apiErrorText(t, (error as { error?: { code?: string } }).error?.code ?? "unknown") });
      return;
    }
    setNote({ ok: true, text: s.saved });
    router.refresh();
  };

  const statusText = s[`offer_${offer.status}` as "offer_active"] ?? offer.status;
  return (
    <li className="space-y-3 rounded-card border border-line bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{offer.product_name}</p>
          <p className="text-sm text-slate">
            {[...Object.values(offer.variant_attributes).map(String), t.condition[offer.condition as keyof Messages["condition"]] ?? offer.condition].join(" · ")}
          </p>
          <p className="text-sm text-slate">{confirmedText}</p>
        </div>
        <div className="flex flex-wrap gap-1 text-sm font-semibold">
          <span className={`rounded-full border px-2 py-0.5 ${offer.status === "active" ? "border-ink" : "border-clay text-clay"}`}>{statusText}</span>
          {offer.is_low_stock ? <span className="rounded-full border border-clay px-2 py-0.5 text-clay">{s.lowStock}</span> : null}
          {offer.needs_confirmation ? <span className="rounded-full border border-clay px-2 py-0.5 text-clay">{s.needsConfirmation}</span> : null}
        </div>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const birr = Number(form.get("price"));
          const stock = Number(form.get("stock"));
          void run(async () => {
            if (Math.round(birr * 100) !== offer.price_santim) {
              const { error } = await browserApi.PATCH("/api/v1/seller/{seller_id}/offers/{offer_id}", { ...path, body: { price_santim: Math.round(birr * 100) } });
              if (error) return { error };
            }
            if (stock !== offer.on_hand) {
              return browserApi.PUT("/api/v1/seller/{seller_id}/offers/{offer_id}/stock", { ...path, body: { on_hand: stock } });
            }
            return {};
          });
        }}
      >
        <label className="space-y-1">
          <span className="block text-sm font-semibold">{s.price}</span>
          <input name="price" type="number" min={1} step="0.01" inputMode="decimal" defaultValue={offer.price_santim / 100} className="min-h-12 w-36 rounded-card border border-line bg-white px-3" />
        </label>
        <label className="space-y-1">
          <span className="block text-sm font-semibold">{s.stock}</span>
          <input name="stock" type="number" min={0} inputMode="numeric" defaultValue={offer.on_hand} className="min-h-12 w-24 rounded-card border border-line bg-white px-3" />
        </label>
        <button type="submit" disabled={busy} className="min-h-12 rounded-card bg-ink px-4 font-bold text-paper disabled:opacity-60">{s.save}</button>
        {offer.status === "active" || offer.status === "paused" ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => browserApi.POST(offer.status === "active" ? "/api/v1/seller/{seller_id}/offers/{offer_id}/pause" : "/api/v1/seller/{seller_id}/offers/{offer_id}/resume", path))}
            className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60"
          >
            {offer.status === "active" ? s.pause : s.resume}
          </button>
        ) : null}
      </form>
      {offer.reserved > 0 ? <p className="text-sm text-slate">{fill(s.held, { count: offer.reserved })}</p> : null}
      {note ? <p role={note.ok ? "status" : "alert"} className={note.ok ? "text-sm font-semibold" : "text-sm font-semibold text-clay"}>{note.text}</p> : null}
    </li>
  );
}
