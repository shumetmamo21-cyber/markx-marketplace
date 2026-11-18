// What the Telegram section of the account page shows (D-093). The API
// decides every state; this only chooses the words and which buttons work,
// so each state can be tested without a browser.
import type { components } from "./api/schema";

export type TelegramConnection = components["schemas"]["TelegramConnectionOut"];

export type TelegramStatus =
  | "unavailable"
  | "notConnected"
  | "requested"
  | "waiting"
  | "connected"
  | "expired"
  | "failed"
  | "disconnected";

export type TelegramTone = "neutral" | "waiting" | "good" | "bad";

export interface TelegramPanel {
  status: TelegramStatus;
  tone: TelegramTone;
  /** The one-time t.me link, only while it is waiting and still known. */
  openLink: string | null;
  /** "connect": the first link; "newLink": another one; "tryAgain": after a refusal. */
  start: "connect" | "newLink" | "tryAgain" | null;
  cancel: boolean;
  disconnect: boolean;
  /** Ask the API again every few seconds: Telegram may confirm at any moment. */
  poll: boolean;
}

const TONES: Record<TelegramStatus, TelegramTone> = {
  unavailable: "neutral",
  notConnected: "neutral",
  requested: "waiting",
  waiting: "waiting",
  connected: "good",
  expired: "bad",
  failed: "bad",
  disconnected: "neutral",
};

function panel(status: TelegramStatus, rest: Partial<Omit<TelegramPanel, "status" | "tone">> = {}): TelegramPanel {
  return { status, tone: TONES[status], openLink: null, start: null, cancel: false, disconnect: false, poll: false, ...rest };
}

/** The section for a connection as the API reported it. `link` is the one the
 * browser was given when it asked (never shown again by the API); `requesting`
 * is true while that request is on its way; `now` is in milliseconds. */
export function telegramPanel(connection: TelegramConnection, { link, requesting, now }: { link: string | null; requesting: boolean; now: number }): TelegramPanel {
  if (connection.state === "connected") return panel("connected", { disconnect: true });
  if (requesting) return panel("requested");
  if (!connection.available) return panel("unavailable");
  switch (connection.state) {
    case "pending": {
      const expires = connection.expires_at ? Date.parse(connection.expires_at) : 0;
      if (expires <= now) return panel("expired", { start: "newLink" });
      return panel("waiting", { openLink: link, start: "newLink", cancel: true, poll: true });
    }
    case "expired":
      return panel("expired", { start: "newLink" });
    case "failed":
      return panel("failed", { start: "tryAgain" });
    case "disconnected":
      return panel("disconnected", { start: "connect" });
    default:
      return panel("notConnected", { start: "connect" });
  }
}

/** The status alone, as of now. For server pages rendered per request,
 * where "now" is the moment of that request. */
export function telegramStatus(connection: TelegramConnection, now: number = Date.now()): TelegramStatus {
  return telegramPanel(connection, { link: null, requesting: false, now }).status;
}

/** Only a link to Telegram's own t.me address with a start parameter is ever
 * offered to the person; anything else from the API is not shown. */
export function safeTelegramLink(link: string | null | undefined): string | null {
  if (!link) return null;
  try {
    const url = new URL(link);
    const ok = url.protocol === "https:" && url.hostname === "t.me" && /^\/[A-Za-z0-9_]{5,32}$/.test(url.pathname) && /^[A-Za-z0-9_-]{1,64}$/.test(url.searchParams.get("start") ?? "");
    return ok ? url.toString() : null;
  } catch {
    return null;
  }
}
