import type { Locale, Messages } from "@/lib/i18n";
import { fill } from "@/lib/i18n";
import { type ShareKind, shareLinks } from "@/lib/share";

import { ShareCards } from "./ShareCards";

// Share a shop or a product (S-10; D-107): its link, Telegram's own share
// page, a QR code to print, and the two share cards. The QR code is a plain
// SVG picture from this site; the cards are drawn on the phone (ShareCards).
// Used on the share pages and the shop's own settings, never on the product
// page itself, whose weight is budgeted (D.26).
export function SharePanel({ origin, lang, kind, slug, name, lines, t, heading }: { origin: string; lang: Locale; kind: ShareKind; slug: string; name: string; lines: string[]; t: Messages; heading?: string }) {
  const links = shareLinks(origin, lang, kind, slug, name);
  const s = t.share;
  return (
    <section aria-labelledby={`share-${kind}`} className="space-y-3 rounded-card border border-line bg-white p-4">
      <h2 id={`share-${kind}`} className="text-lg font-bold">{heading ?? s.title}</h2>
      <p className="text-sm text-slate">{kind === "store" ? s.storeLead : s.productLead}</p>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        {/* eslint-disable-next-line @next/next/no-img-element -- an SVG drawn by this site's server (D-107) */}
        <img src={links.qr} alt={fill(s.qrAlt, { name })} width={160} height={160} className="h-40 w-40 shrink-0 rounded-card border border-line bg-white" />
        <div className="min-w-0 flex-1 space-y-2 text-sm">
          <label className="block space-y-1">
            <span className="block font-semibold">{s.link}</span>
            <input readOnly value={links.page} className="min-h-12 w-full rounded-card border border-line bg-paper px-3" />
          </label>
          <ul className="space-y-1">
            <li><a href={links.telegram} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-12 items-center font-semibold underline">{s.telegram}</a></li>
            <li><a href={`${links.qr}?download=1`} download className="inline-flex min-h-12 items-center underline">{s.qrDownload}</a></li>
          </ul>
          <ShareCards
            text={{ brand: t.brand.wordmark, name, lines, scan: fill(s.scan, { brand: t.brand.wordmark }), link: links.page }}
            fileStem={`markx-${slug}`}
            labels={{ telegram: s.cardTelegram, tiktok: s.cardTiktok, failed: s.cardFailed }}
          />
        </div>
      </div>
    </section>
  );
}
