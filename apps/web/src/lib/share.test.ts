import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { CARD_SIZES, cardFormat, cardLayout, insideCard, productLines, publicOrigin, shareLinks, storeLines } from "./share";

describe("publicOrigin (S-10)", () => {
  it("uses the site's configured https address", () => {
    expect(publicOrigin({ MARKX_PUBLIC_ORIGIN: "https://markx.example", NODE_ENV: "production" })).toBe("https://markx.example");
    expect(publicOrigin({ MARKX_PUBLIC_ORIGIN: "https://markx.example/", NODE_ENV: "production" })).toBe("https://markx.example");
  });
  it("refuses anything that is not a bare https origin (plain http only on a laptop)", () => {
    for (const bad of ["http://markx.example", "https://markx.example/shop", "javascript:alert(1)", "https://a@markx.example", "markx.example"]) {
      expect(publicOrigin({ MARKX_PUBLIC_ORIGIN: bad, NODE_ENV: "production" }), bad).toBeNull();
    }
    expect(publicOrigin({ MARKX_PUBLIC_ORIGIN: "http://localhost:3000" })).toBe("http://localhost:3000");
  });
  it("knows no address in production without the setting: no QR code is drawn rather than a wrong one", () => {
    expect(publicOrigin({ NODE_ENV: "production" })).toBeNull();
    expect(publicOrigin({ NODE_ENV: "development" })).toBe("http://localhost:3000");
  });
});

describe("shareLinks (S-10)", () => {
  it("gives the page, Telegram's share page, both cards and the QR file", () => {
    expect(shareLinks("https://markx.example", "am", "store", "alpha", "Alpha ሱቅ")).toEqual({
      page: "https://markx.example/am/s/alpha",
      telegram: "https://t.me/share/url?url=https%3A%2F%2Fmarkx.example%2Fam%2Fs%2Falpha&text=Alpha%20%E1%88%B1%E1%89%85",
      qr: "/am/s/alpha/qr",
    });
    expect(shareLinks("https://markx.example", "en", "product", "samsung-galaxy-a16", "x").page).toBe("https://markx.example/en/p/samsung-galaxy-a16");
  });
  it("refuses anything that is not a slug", () => {
    expect(() => shareLinks("https://markx.example", "am", "store", "../admin", "x")).toThrow();
  });
  it("lays every part of both cards inside the card, the QR code clear of the words", () => {
    for (const format of ["telegram", "tiktok"] as const) {
      const l = cardLayout(format);
      const qr = { x: l.qr.x, y: l.qr.y, width: l.qr.side, height: l.qr.side };
      const panel = { x: l.qr.panelX, y: l.qr.panelY, width: l.qr.panelWidth, height: l.qr.panelHeight };
      const words = { x: l.text.x, y: l.text.y, width: l.text.width, height: l.bar.y + 12 - l.text.y };
      for (const box of [qr, panel, words, { x: l.qr.textX, y: l.qr.linkY, width: 1, height: l.linkSize }]) expect(insideCard(format, box), format).toBe(true);
      // The QR code sits inside its white panel; the words never reach it.
      expect(qr.x >= panel.x && qr.y >= panel.y && qr.x + qr.width <= panel.x + panel.width).toBe(true);
      const apart = format === "telegram" ? words.x + words.width <= panel.x : words.y + words.height <= panel.y;
      expect(apart, format).toBe(true);
      // The scan line and the address are under the code, inside the panel.
      expect(l.qr.scanY).toBeGreaterThan(qr.y + qr.height);
      expect(l.qr.linkY + l.linkSize).toBeLessThanOrEqual(panel.y + panel.height);
    }
  });

  it("sizes the cards for Telegram and TikTok", () => {
    expect(CARD_SIZES).toEqual({ telegram: { width: 1200, height: 630 }, tiktok: { width: 1080, height: 1920 } });
    expect(cardFormat("tiktok")).toBe("tiktok");
    expect(cardFormat("anything")).toBe("telegram");
    expect(cardFormat(null)).toBe("telegram");
  });
});

describe("the cards' words (S-10)", () => {
  it("say a shop's level, and verified from Level 2, in both languages", () => {
    expect(storeLines(en, 2)).toEqual(["Level 2 shop", "Verified on MarkX"]);
    expect(storeLines(en, 1)).toEqual(["Level 1 shop"]);
    expect(storeLines(am, 2)[1]).toBe("በማርክኤክስ የተረጋገጠ");
  });
  it("say a product's lowest price and how many shops", () => {
    expect(productLines(en, "en", 1_200_000, 2)).toEqual(["from ETB 12,000", "2 sellers"]);
    expect(productLines(en, "en", null, 0)).toEqual(["Out of stock"]);
    expect(productLines(am, "am", 1_200_000, 1)).toEqual(["ከ12,000 ብር ጀምሮ", "1 ሻጭ"]);
  });
});
