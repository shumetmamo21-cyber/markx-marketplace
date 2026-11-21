// What the "Sign in with Telegram" box shows (D-101). The API decides every
// state; this only chooses which part of the box is shown and whether to
// keep asking, so each state can be tested without a browser.
import type { components } from "./api/schema";

type Answer = components["schemas"]["TelegramWebSignInStateOut"];

/** What the box needs of the API's answer. */
export type TelegramSignInState = Pick<Answer, "state"> & Partial<Pick<Answer, "expires_at" | "reason">>;

export type SignInStatus = "start" | "waiting" | "signedIn" | "expired" | "refused";

export function signInStep(state: Pick<TelegramSignInState, "state">): { status: SignInStatus; poll: boolean } {
  switch (state.state) {
    case "waiting":
    case "waiting_for_phone":
      return { status: "waiting", poll: true };
    case "signed_in":
      return { status: "signedIn", poll: false };
    case "expired":
      return { status: "expired", poll: false };
    case "refused":
      return { status: "refused", poll: false };
    default:
      return { status: "start", poll: false };
  }
}

const SIGN_IN_LINK = /^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}\?start=si-[A-Za-z0-9_-]{43}$/;

/** Only a t.me link to the bot with a sign-in payload is ever shown. */
export function safeTelegramSignInLink(link: string | null | undefined): string | null {
  return link && SIGN_IN_LINK.test(link) ? link : null;
}
