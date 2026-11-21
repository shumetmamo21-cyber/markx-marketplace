"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

import { ProblemNotice } from "../Resilience";

// The staff step on top of a Telegram sign-in (D-101): the existing second
// step, the password and the authenticator code. No phone number: the API
// takes it from the signed-in account.
export function StaffStepForm({ next, t }: { next: string; t: Pick<Messages, "admin" | "apiErrors"> }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ code: string; text: string } | null>(null);
  const field = "min-h-12 w-full rounded-card border border-line bg-white px-4";
  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        setBusy(true);
        setProblem(null);
        const { error } = await browserApi.POST("/api/v1/auth/staff/step-up", {
          body: { password: String(form.get("password") ?? ""), totp_code: String(form.get("totp") ?? "").trim() },
        });
        if (error) {
          setBusy(false);
          setProblem({ code: errorCode(error), text: apiErrorText(t, errorCode(error)) });
          return;
        }
        router.replace(next);
        router.refresh();
      }}
    >
      <label className="block space-y-1">
        <span className="font-semibold">{t.admin.password}</span>
        <input name="password" type="password" autoComplete="current-password" required className={field} />
      </label>
      <label className="block space-y-1">
        <span className="font-semibold">{t.admin.totp}</span>
        <input name="totp" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" required className={field} />
      </label>
      {problem ? <ProblemNotice code={problem.code} text={problem.text} retry="submit" busy={busy} className="text-clay" /> : null}
      <button type="submit" disabled={busy} className="min-h-12 w-full rounded-card bg-ink font-bold text-paper disabled:opacity-60">
        {t.admin.signIn}
      </button>
    </form>
  );
}
