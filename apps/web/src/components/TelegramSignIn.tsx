"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { formatDateTime } from "@/lib/format";
import { apiErrorText, fill, type Locale, type Messages } from "@/lib/i18n";
import { safeNext } from "@/lib/safe-next";
import { safeTelegramSignInLink, signInStep, type TelegramSignInState } from "@/lib/telegram-sign-in";

import { ProblemNotice } from "./Resilience";

// Signing in with Telegram (D-101, decision SI-1). One button opens the
// Telegram app on the phone; the person presses Start and shares their
// number with Telegram's own button; this page notices by itself and
// signs in. Nothing is typed, and nothing about Telegram is believed from
// this page: the API hears it from Telegram. The browser's private half of
// the sign-in is an HttpOnly cookie the page cannot read, so a reloaded tab
// (a low-memory phone often reloads it on the way back from Telegram)
// carries on where it was.

type T = Pick<Messages, "auth" | "apiErrors">;

const POLL_MS = 2_500;
const primary = "inline-flex min-h-12 w-full items-center justify-center rounded-card bg-[#0F6A9E] px-5 text-lg font-bold text-white disabled:opacity-60";
const secondary = "inline-flex min-h-12 w-full items-center justify-center rounded-card border border-ink px-4 font-semibold disabled:opacity-60";

export function TelegramSignIn({ lang, t, next }: { lang: Locale; t: T; next: string }) {
  const g = t.auth.telegram;
  const router = useRouter();
  const [state, setState] = useState<TelegramSignInState>({ state: "none" });
  const [link, setLink] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [checkFailed, setCheckFailed] = useState(false);
  const [problem, setProblem] = useState<{ code: string; text: string } | null>(null);
  const done = useRef(false);
  const step = signInStep(state);

  const check = useCallback(async () => {
    if (done.current) return;
    const { data, error } = await browserApi.POST("/api/v1/auth/telegram/sign-in/check", {});
    if (error || !data) return setCheckFailed(true);
    setCheckFailed(false);
    setState(data);
    if (data.state === "signed_in") {
      done.current = true;
      // Checked again here, so this is safe whoever renders it (SEC-1).
      router.replace(safeNext(next, `/${lang}/orders`));
      router.refresh();
    }
  }, [lang, next, router]);

  // A sign-in this browser had already started (a reloaded tab) carries on.
  useEffect(() => {
    const id = setTimeout(() => void check(), 0);
    return () => clearTimeout(id);
  }, [check]);

  // While Telegram has not confirmed, ask every few seconds and at once
  // when the person comes back to this tab from Telegram.
  useEffect(() => {
    if (!step.poll) return;
    const id = setInterval(() => void check(), POLL_MS);
    const onReturn = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onReturn);
    window.addEventListener("focus", onReturn);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onReturn);
      window.removeEventListener("focus", onReturn);
    };
  }, [step.poll, check]);

  async function start() {
    setStarting(true);
    setProblem(null);
    const { data, error } = await browserApi.POST("/api/v1/auth/telegram/sign-in", { body: { language: lang } });
    setStarting(false);
    if (error || !data) return setProblem({ code: errorCode(error), text: apiErrorText(t, errorCode(error)) });
    setLink(safeTelegramSignInLink(data.link));
    setState({ state: "waiting", expires_at: data.expires_at });
  }

  const refusal = state.state === "refused" && state.reason ? g[`refused_${state.reason}`] : g.refused;

  return (
    <section aria-labelledby="telegram-sign-in" className="space-y-4 rounded-card border border-line bg-white p-5" data-telegram-sign-in={step.status}>
      <h2 id="telegram-sign-in" className="sr-only">{g.start}</h2>
      {step.status === "start" ? (
        <button type="button" onClick={start} disabled={starting} className={primary}>
          {starting ? g.starting : g.start}
        </button>
      ) : null}

      {step.status === "waiting" ? (
        <div className="space-y-3">
          {link ? (
            <>
              <p className="font-semibold">{g.steps}</p>
              <ol className="list-decimal space-y-1 pl-6">
                <li>{g.step1}</li>
                <li>{g.step2}</li>
                <li>{g.step3}</li>
              </ol>
              <a href={link} target="_blank" rel="noopener noreferrer" className={primary}>{g.open}</a>
            </>
          ) : (
            <p className="font-semibold">{g.continueInTelegram}</p>
          )}
          <p className="text-sm text-slate">{state.state === "waiting_for_phone" ? g.waitingForPhone : g.waiting}</p>
          {state.expires_at ? <p className="text-sm text-slate" suppressHydrationWarning>{fill(g.expiresAt, { time: formatDateTime(state.expires_at, lang) })}</p> : null}
          <button type="button" onClick={start} disabled={starting} className={secondary}>{g.startAgain}</button>
        </div>
      ) : null}

      {step.status === "expired" || step.status === "refused" ? (
        <div className="space-y-3">
          <p role="alert" className="font-semibold text-clay">{step.status === "expired" ? g.expired : refusal}</p>
          <button type="button" onClick={start} disabled={starting} className={primary}>{g.startAgain}</button>
        </div>
      ) : null}

      <p role="status" aria-live="polite" className="font-semibold">{step.status === "signedIn" ? g.signedIn : ""}</p>
      {problem ? <ProblemNotice code={problem.code} text={problem.text} retry={() => void start()} busy={starting} className="text-clay" /> : null}
      {checkFailed && step.poll ? <p role="alert" className="text-sm font-semibold text-clay">{g.checkFailed}</p> : null}
      {step.status === "start" ? <p className="text-sm text-slate">{g.noTelegram}</p> : null}
    </section>
  );
}
