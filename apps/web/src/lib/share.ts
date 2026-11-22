// Share links, QR codes and share cards for a shop and its products (S-10,
// blueprint D.4, B, E.2; D-107). Pure, so it is tested without a server.

import { formatPrice } from "./format";
import { fill, type Locale, type Messages } from "./i18n";

export type ShareKind = "store" | "product";
export type CardFormat = "telegram" | "tiktok";
type Box = { x: number; y: number; width: number; height: number };

// PROVISIONAL (P-107-7, D-107): a post-sized card for Telegram and a tall one
// for TikTok or a story, with the name, the level (and "verified" from Level
// 2) or the lowest price and number of shops, a QR code and the address.
export const CARD_SIZES: Record<CardFormat, { width: number; height: number }> = {
  telegram: { width: 1200, height: 630 },
  tiktok: { width: 1080, height: 1920 },
};

/** The site's public address: `MARKX_PUBLIC_ORIGIN`, which the production
 * server refuses to start without (deploy/check-env.mjs), or the laptop's
 * address outside production. Never the request's Host header, which the
 * person asking can set to anything. Null when it cannot be known. */
export function publicOrigin(env: { MARKX_PUBLIC_ORIGIN?: string; NODE_ENV?: string }): string | null {
  const raw = (env.MARKX_PUBLIC_ORIGIN ?? "").trim();
  if (raw) {
    try {
      const url = new URL(raw);
      const local = url.hostname === "localhost" || url.hostname === "127.0.0.1";
      if ((url.protocol === "https:" || (url.protocol === "http:" && local)) && url.pathname === "/" && !url.search && !url.hash && !url.username) {
        return url.origin;
      }
    } catch {
      // not an address: fall through
    }
    return null;
  }
  return env.NODE_ENV === "production" ? null : "http://localhost:3000";
}

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** Every link the share panel offers for one shop or product. */
export function shareLinks(origin: string, lang: Locale, kind: ShareKind, slug: string, text: string) {
  if (!SLUG.test(slug)) throw new Error("not a slug");
  const path = `/${lang}/${kind === "store" ? "s" : "p"}/${slug}`;
  const page = `${origin}${path}`;
  return {
    page,
    // Telegram's own share page: the link and a line of text, nothing else.
    telegram: `https://t.me/share/url?url=${encodeURIComponent(page)}&text=${encodeURIComponent(text)}`,
    qr: `${path}/qr`,
  };
}

export function cardFormat(value: string | null): CardFormat {
  return value === "tiktok" ? "tiktok" : "telegram";
}

/** Where everything goes on a card, in pixels (the card is drawn on the
 * phone, `ShareCards`). Wide: the words left, the QR code right. Tall: the
 * words above, the QR code below. Pure, so the tests check that every part
 * is inside the card and nothing overlaps. */
export function cardLayout(format: CardFormat) {
  const { width, height } = CARD_SIZES[format];
  if (format === "telegram") {
    const panelWidth = 420;
    const panelX = width - panelWidth;
    const side = 320;
    return {
      text: { x: 64, y: 64, width: panelX - 64 * 2 },
      bar: { y: height - 64 - 12 },
      brandSize: 34, nameSize: 60, lineSize: 32, scanSize: 26, linkSize: 20,
      qr: { panelX, panelY: 0, panelWidth, panelHeight: height, x: panelX + (panelWidth - side) / 2, y: 110, side, textX: panelX + 32, scanY: 110 + side + 30, linkY: 110 + side + 76 },
    };
  }
  const panelHeight = 900;
  const panelY = height - panelHeight;
  const side = 640;
  return {
    text: { x: 80, y: 120, width: width - 80 * 2 },
    bar: { y: panelY - 80 - 12 },
    brandSize: 44, nameSize: 84, lineSize: 44, scanSize: 40, linkSize: 30,
    qr: { panelX: 0, panelY, panelWidth: width, panelHeight, x: (width - side) / 2, y: panelY + 80, side, textX: 80, scanY: panelY + 80 + side + 40, linkY: panelY + 80 + side + 110 },
  };
}

export function insideCard(format: CardFormat, box: Box): boolean {
  const { width, height } = CARD_SIZES[format];
  return box.x >= 0 && box.y >= 0 && box.x + box.width <= width && box.y + box.height <= height;
}

/** A shop card's lines: its level, and "verified" from Level 2 (D.3). */
export function storeLines(t: Messages, level: number): string[] {
  const lines = [fill(t.store.level, { level })];
  if (level >= 2) lines.push(fill(t.share.verified, { brand: t.brand.wordmark }));
  return lines;
}

/** A product card's lines: the lowest price in stock and how many shops. */
export function productLines(t: Messages, lang: Locale, lowest: number | null, shops: number): string[] {
  const lines = [lowest !== null ? fill(t.card.from, { price: formatPrice(lowest, lang) }) : t.card.outOfStock];
  if (shops) lines.push(shops === 1 ? t.card.sellerOne : fill(t.card.sellerCount, { count: shops }));
  return lines;
}
