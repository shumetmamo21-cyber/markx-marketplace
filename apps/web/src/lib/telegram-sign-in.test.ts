import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { safeTelegramSignInLink, signInStep } from "./telegram-sign-in";

const TOKEN = "A".repeat(43);

describe("Telegram sign-in (D-101)", () => {
  it("keeps asking only while Telegram has not answered", () => {
    expect(signInStep({ state: "none" })).toEqual({ status: "start", poll: false });
    expect(signInStep({ state: "waiting" })).toEqual({ status: "waiting", poll: true });
    expect(signInStep({ state: "waiting_for_phone" })).toEqual({ status: "waiting", poll: true });
    expect(signInStep({ state: "signed_in" })).toEqual({ status: "signedIn", poll: false });
    expect(signInStep({ state: "expired" })).toEqual({ status: "expired", poll: false });
    expect(signInStep({ state: "refused" })).toEqual({ status: "refused", poll: false });
  });

  it("shows only a t.me sign-in link to a bot", () => {
    expect(safeTelegramSignInLink(`https://t.me/markx_bot?start=si-${TOKEN}`)).toBe(`https://t.me/markx_bot?start=si-${TOKEN}`);
    for (const bad of [
      `http://t.me/markx_bot?start=si-${TOKEN}`,
      `https://t.me.evil.example/markx_bot?start=si-${TOKEN}`,
      `https://t.me/markx_bot?start=${TOKEN}`,
      `javascript:alert(1)//https://t.me/markx_bot?start=si-${TOKEN}`,
      `https://t.me/markx_bot?start=si-${TOKEN}&x=1`,
      "",
      null,
    ]) {
      expect(safeTelegramSignInLink(bad)).toBeNull();
    }
  });

  it("has words in both languages for every refusal the API may give", () => {
    for (const reason of ["phone_not_ethiopian", "phone_on_other_telegram", "phone_in_use", "account_inactive"] as const) {
      expect(en.auth.telegram[`refused_${reason}`]).toBeTruthy();
      expect(am.auth.telegram[`refused_${reason}`]).toMatch(/[ሀ-፿]/);
    }
  });
});
