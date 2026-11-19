import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";

import { signInProblem } from "./sign-in-problem";

const tooSoon = (details: unknown) => ({ error: { code: "otp_resend_too_soon", details } });

describe("signInProblem (D-089: the resend cooldown)", () => {
  it("says how many seconds are left, in English and Amharic", () => {
    expect(signInProblem(en.auth, tooSoon({ retry_after_seconds: 42 }))).toBe(
      "A code was just sent to this number. You can ask for another in 42 seconds.",
    );
    const amharic = signInProblem(am.auth, tooSoon({ retry_after_seconds: 42 }));
    expect(amharic).toContain("42");
    expect(amharic).not.toContain("{seconds}");
  });

  it.each([undefined, {}, { retry_after_seconds: "42" }, { retry_after_seconds: -1 }, { retry_after_seconds: 1e9 }])(
    "falls back to the general line when the wait is missing or odd (%j)",
    (details) => {
      expect(signInProblem(en.auth, tooSoon(details))).toBe(en.auth.rateLimited);
    },
  );

  it("keeps the existing messages", () => {
    expect(signInProblem(en.auth, { error: { code: "rate_limited" } })).toBe(en.auth.rateLimited);
    expect(signInProblem(en.auth, { error: { code: "bot_check_failed" } })).toBe(en.auth.botCheckFailed);
    expect(signInProblem(en.auth, { error: { code: "otp_invalid" } })).toBe(en.auth.failed);
    expect(signInProblem(en.auth, undefined)).toBe(en.auth.failed);
  });
});
