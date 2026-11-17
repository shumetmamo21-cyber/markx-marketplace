"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { fill, type Locale, type Messages } from "@/lib/i18n";

type Step = { kind: "phone" } | { kind: "code"; masked: string; minutes: number };

// Phone first, then the six-digit code (blueprint F.4). The API sets the
// session cookie on the verify response; a full page load then carries it.
export function SignInForm({ lang, t, next, dev }: { lang: Locale; t: Messages["auth"]; next: string; dev: boolean }) {
  const router = useRouter();
  const [step, setStep] = useState<Step>({ kind: "phone" });
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const fail = (error: unknown) => setProblem(errorCode(error) === "rate_limited" ? t.rateLimited : t.failed);

  if (step.kind === "phone") {
    return (
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setProblem(null);
          const { data, error } = await browserApi.POST("/api/v1/auth/otp/request", { body: { phone, language: lang } });
          setBusy(false);
          if (error || !data) return fail(error);
          setStep({ kind: "code", masked: data.phone_masked, minutes: Math.round(data.expires_in_seconds / 60) });
        }}
      >
        <label className="block space-y-1">
          <span className="font-semibold">{t.phone}</span>
          <input
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            required
            minLength={9}
            aria-describedby="phone-hint"
            className="min-h-12 w-full rounded-card border border-line bg-white px-4 text-lg"
          />
          <span id="phone-hint" className="block text-sm text-slate">{t.phoneHint}</span>
        </label>
        {problem ? <p role="alert" className="text-clay">{problem}</p> : null}
        <button type="submit" disabled={busy} className="min-h-12 w-full rounded-card bg-adey font-bold disabled:opacity-60">
          {busy ? t.sending : t.sendCode}
        </button>
        {dev ? <p className="text-sm text-slate">{t.devHint}</p> : null}
      </form>
    );
  }
  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const code = String(new FormData(event.currentTarget).get("code") ?? "").trim();
        setBusy(true);
        setProblem(null);
        const { error } = await browserApi.POST("/api/v1/auth/otp/verify", { body: { phone, code, language: lang } });
        if (error) {
          setBusy(false);
          return fail(error);
        }
        router.replace(next);
        router.refresh();
      }}
    >
      <p role="status">{fill(t.codeSent, { phone: step.masked, minutes: step.minutes })}</p>
      <label className="block space-y-1">
        <span className="font-semibold">{t.code}</span>
        <input
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          required
          className="min-h-12 w-full rounded-card border border-line bg-white px-4 text-center text-2xl tracking-[0.4em]"
        />
      </label>
      {problem ? <p role="alert" className="text-clay">{problem}</p> : null}
      <button type="submit" disabled={busy} className="min-h-12 w-full rounded-card bg-adey font-bold disabled:opacity-60">
        {busy ? t.verifying : t.verify}
      </button>
      <button type="button" onClick={() => setStep({ kind: "phone" })} className="min-h-12 w-full font-semibold underline">
        {t.changePhone}
      </button>
    </form>
  );
}
