import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { safeTelegramLink, type TelegramConnection, telegramPanel, telegramStatus } from "./telegram";

const NOW = Date.parse("2026-11-18T12:00:00Z");
const LINK = `https://t.me/markx_test_only_bot?start=${"A".repeat(43)}`;

function connection(state: TelegramConnection["state"], extra: Partial<TelegramConnection> = {}): TelegramConnection {
  return { available: true, telegram_messages_on: false, state, connected_at: null, expires_at: null, link: null, ...extra };
}

const view = (c: TelegramConnection, link: string | null = null, requesting = false) => telegramPanel(c, { link, requesting, now: NOW });

describe("the Telegram section (D-093)", () => {
  it("offers nothing that cannot work while connecting is switched off", () => {
    const shown = view(connection("not_connected", { available: false }));
    expect(shown.status).toBe("unavailable");
    expect([shown.start, shown.openLink, shown.cancel, shown.disconnect, shown.poll]).toEqual([null, null, false, false, false]);
  });

  it("still lets a connected person disconnect while connecting is switched off", () => {
    const shown = view(connection("connected", { available: false, connected_at: "2026-11-18T10:00:00Z" }));
    expect(shown.status).toBe("connected");
    expect(shown.disconnect).toBe(true);
    expect(shown.start).toBeNull();
  });

  it("starts from not connected", () => {
    expect(view(connection("not_connected"))).toMatchObject({ status: "notConnected", start: "connect", tone: "neutral" });
  });

  it("shows the request on its way, with no other button", () => {
    expect(view(connection("not_connected"), null, true)).toMatchObject({ status: "requested", start: null, disconnect: false, cancel: false });
  });

  it("waits for Telegram with the link, a cancel and polling", () => {
    const shown = view(connection("pending", { expires_at: "2026-11-18T12:09:00Z" }), LINK);
    expect(shown).toMatchObject({ status: "waiting", openLink: LINK, cancel: true, poll: true, start: "newLink" });
  });

  it("waits without a link after a reload, offering a new one", () => {
    const shown = view(connection("pending", { expires_at: "2026-11-18T12:09:00Z" }));
    expect(shown).toMatchObject({ status: "waiting", openLink: null, start: "newLink" });
  });

  it("calls a waiting link expired once its time has passed, before the API does", () => {
    const shown = view(connection("pending", { expires_at: "2026-11-18T11:59:59Z" }), LINK);
    expect(shown).toMatchObject({ status: "expired", openLink: null, poll: false, start: "newLink", tone: "bad" });
  });

  it("shows expired, failed and disconnected with the right next step", () => {
    expect(view(connection("expired"))).toMatchObject({ status: "expired", start: "newLink" });
    expect(view(connection("failed"))).toMatchObject({ status: "failed", start: "tryAgain", tone: "bad" });
    expect(view(connection("disconnected"))).toMatchObject({ status: "disconnected", start: "connect" });
  });

  it("gives server pages the status alone", () => {
    expect(telegramStatus(connection("pending", { expires_at: "2026-11-18T12:09:00Z" }), NOW)).toBe("waiting");
    expect(telegramStatus(connection("pending", { expires_at: "2026-11-18T11:00:00Z" }), NOW)).toBe("expired");
    expect(telegramStatus(connection("not_connected", { available: false }), NOW)).toBe("unavailable");
  });

  it("shows connected as connected, with only disconnect", () => {
    expect(view(connection("connected"))).toMatchObject({ status: "connected", tone: "good", disconnect: true, start: null, poll: false });
  });

  it("has words for every status and step in both languages", () => {
    const statuses = ["unavailable", "notConnected", "requested", "waiting", "connected", "expired", "failed", "disconnected"] as const;
    for (const t of [en, am]) {
      for (const status of statuses) {
        expect(t.account.telegram.status[status]).toBeTruthy();
        expect(t.account.telegram.explain[status]).toBeTruthy();
      }
    }
    expect(en.account.telegram.status.connected).toBe("Connected");
    expect(am.account.telegram.status.connected).toBe("ተገናኝቷል");
    expect(am.account.telegram.title).not.toMatch(/[a-z]{4,}/);
  });
});

describe("the link offered to the person", () => {
  it("is only ever Telegram's own t.me address with a start parameter", () => {
    expect(safeTelegramLink(LINK)).toBe(LINK);
    expect(safeTelegramLink(null)).toBeNull();
    expect(safeTelegramLink("http://t.me/markx_test_only_bot?start=abc")).toBeNull();
    expect(safeTelegramLink("https://t.me.evil.example/markx_bot?start=abc")).toBeNull();
    expect(safeTelegramLink("https://t.me/markx_bot")).toBeNull();
    expect(safeTelegramLink("https://t.me/markx_bot/extra?start=abc")).toBeNull();
    expect(safeTelegramLink("javascript:alert(1)")).toBeNull();
    expect(safeTelegramLink("https://t.me/markx_bot?start=a%20b")).toBeNull();
  });
});
