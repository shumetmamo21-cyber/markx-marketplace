"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { formatDateTime } from "@/lib/format";
import { apiErrorText, fill, type Locale, type Messages } from "@/lib/i18n";
import { safeTelegramLink, type TelegramConnection as Connection, telegramPanel, type TelegramTone } from "@/lib/telegram";

// The person's own Telegram connection (D-093). Every state comes from the
// API; the page never shows "connected" until the API says so. The one-time
// link exists only in this browser's memory: the API never shows it again.

type T = Pick<Messages, "account" | "apiErrors">;

const POLL_MS = 3_000;
const TICK_MS = 5_000;
function subscribe(callback: () => void) {
  const id = setInterval(callback, TICK_MS);
  return () => clearInterval(id);
}
const clientNow = () => Math.floor(Date.now() / TICK_MS) * TICK_MS;
// On the server, trust the API's state; the browser then checks the expiry.
const serverNow = () => null;

const PILL: Record<TelegramTone, string> = {
  neutral: "border border-line bg-paper text-ink",
  waiting: "bg-adey text-ink",
  good: "bg-highland text-paper",
  bad: "bg-clay text-paper",
};
const primary = "inline-flex min-h-12 items-center justify-center rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60";
const secondary = "inline-flex min-h-12 items-center justify-center rounded-card border border-ink px-4 font-semibold disabled:opacity-60";
const dangerSolid = "inline-flex min-h-12 items-center justify-center rounded-card bg-clay px-5 font-bold text-paper disabled:opacity-60";
const danger = "inline-flex min-h-12 items-center justify-center rounded-card border border-clay px-4 font-semibold text-clay disabled:opacity-60";

export function TelegramConnection({ initial, lang, t }: { initial: Connection; lang: Locale; t: T }) {
  const g = t.account.telegram;
  const [connection, setConnection] = useState<Connection>(initial);
  const [link, setLink] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [checkFailed, setCheckFailed] = useState(false);
  const state = useRef(initial.state);
  const now = useSyncExternalStore(subscribe, clientNow, serverNow);
  const shown = telegramPanel(connection, { link, requesting, now: now ?? 0 });

  const show = useCallback(
    (next: Connection) => {
      if (next.state === "connected" && state.current !== "connected") setAnnouncement(g.nowConnected);
      if (next.state !== "connected" && state.current === "connected") setAnnouncement(g.nowDisconnected);
      if (next.state !== "pending") setLink(null);
      state.current = next.state;
      setConnection(next);
    },
    [g.nowConnected, g.nowDisconnected],
  );

  const refresh = useCallback(async () => {
    const { data, error } = await browserApi.GET("/api/v1/me/telegram", { cache: "no-store" });
    if (error || !data) return setCheckFailed(true);
    setCheckFailed(false);
    show(data);
  }, [show]);

  // While a link waits, ask every few seconds and whenever the person comes
  // back to this tab from Telegram.
  useEffect(() => {
    if (!shown.poll) return;
    const id = setInterval(() => void refresh(), POLL_MS);
    const onReturn = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onReturn);
    window.addEventListener("focus", onReturn);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onReturn);
      window.removeEventListener("focus", onReturn);
    };
  }, [shown.poll, refresh]);

  async function start() {
    setRequesting(true);
    setProblem(null);
    setAnnouncement(null);
    const { data, error } = await browserApi.POST("/api/v1/me/telegram/link", {});
    setRequesting(false);
    if (error || !data) {
      setProblem(apiErrorText(t, errorCode(error)));
      return void refresh();
    }
    show({ ...data, link: null });
    setLink(safeTelegramLink(data.link));
  }

  async function remove() {
    setBusy(true);
    setProblem(null);
    const { data, error } = await browserApi.DELETE("/api/v1/me/telegram", {});
    setBusy(false);
    setConfirming(false);
    if (error || !data) return setProblem(apiErrorText(t, errorCode(error)));
    show(data);
  }

  const startLabel = shown.start === "newLink" ? g.newLink : shown.start === "tryAgain" ? g.tryAgain : g.connect;
  const locked = requesting || busy;

  return (
    <section aria-labelledby="telegram" className="space-y-3 rounded-card border border-line bg-white p-4" data-telegram-status={shown.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="telegram" className="text-xl font-bold">{g.title}</h2>
        <span className={`rounded-full px-3 py-1 text-sm font-bold ${PILL[shown.tone]}`}>{g.status[shown.status]}</span>
      </div>
      <p className="text-sm text-slate">{g.lead}</p>
      <p className="font-semibold">{g.explain[shown.status]}</p>

      {shown.status === "waiting" ? (
        <div className="space-y-3">
          <ol className="list-decimal space-y-1 pl-6">
            <li>{g.step1}</li>
            <li>{g.step2}</li>
            <li>{g.step3}</li>
          </ol>
          {shown.openLink ? (
            <a href={shown.openLink} target="_blank" rel="noopener noreferrer" className={primary}>{g.openTelegram}</a>
          ) : (
            <p className="text-sm">{g.linkHidden}</p>
          )}
          {connection.expires_at ? <p className="text-sm text-slate" suppressHydrationWarning>{fill(g.expiresAt, { time: formatDateTime(connection.expires_at, lang) })}</p> : null}
        </div>
      ) : null}

      {shown.status === "connected" ? (
        <div className="space-y-1 text-sm">
          {connection.connected_at ? <p suppressHydrationWarning>{fill(g.connectedSince, { date: formatDateTime(connection.connected_at, lang) })}</p> : null}
          <p>{connection.telegram_messages_on ? g.messagesOn : g.messagesOff}</p>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3">
        {shown.start ? (
          <button type="button" onClick={start} disabled={locked} className={shown.start === "newLink" && shown.status === "waiting" ? secondary : primary}>{startLabel}</button>
        ) : null}
        {requesting ? (
          <button type="button" disabled aria-busy="true" className={primary}>{g.status.requested}</button>
        ) : null}
        {shown.cancel ? (
          <button type="button" onClick={remove} disabled={locked} className={secondary}>{g.cancel}</button>
        ) : null}
        {shown.disconnect && !confirming ? (
          <button type="button" onClick={() => setConfirming(true)} disabled={locked} className={danger}>{g.disconnect}</button>
        ) : null}
      </div>

      {shown.disconnect && confirming ? (
        <div role="group" aria-labelledby="telegram-confirm" className="space-y-2 rounded-card border border-clay p-3">
          <p id="telegram-confirm" className="font-bold">{g.confirmTitle}</p>
          <p className="text-sm">{g.confirmText}</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={remove} disabled={busy} className={dangerSolid}>{g.confirmYes}</button>
            <button type="button" onClick={() => setConfirming(false)} disabled={busy} className={secondary} autoFocus>{g.confirmNo}</button>
          </div>
        </div>
      ) : null}

      <p role="status" aria-live="polite" className="font-semibold">{announcement ?? ""}</p>
      {problem ? <p role="alert" className="font-semibold text-clay">{problem}</p> : null}
      {checkFailed && shown.poll ? <p role="alert" className="text-sm font-semibold text-clay">{g.checkFailed}</p> : null}
    </section>
  );
}
