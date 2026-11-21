"use client";

import Link from "next/link";
import { createContext, type ReactNode, useContext, useState, useSyncExternalStore } from "react";

import { isConnectionProblem, NETWORK_FAILED } from "@/lib/api/browser";
import { FALLBACK_TEXT, type ResilienceText } from "@/lib/fallback-text";

// What every page needs when the connection or the server fails (D-100): the
// words for the two failures, the "try again" button and the error pages.
// The root layout gives them once, in the page's language, so no component
// has to be handed them and the error pages (which receive no props of their
// own) can read them.

export type { ResilienceText };


const Context = createContext<ResilienceText | null>(null);

export function ResilienceProvider({ text, children }: { text: ResilienceText; children?: ReactNode }) {
  return <Context.Provider value={text}>{children}</Context.Provider>;
}

/** The words, in the page's language. Outside the provider (which should
 * not happen) the Amharic default, never a crash: an error page must render. */
export function useResilienceText(): ResilienceText {
  return useContext(Context) ?? FALLBACK_TEXT.am;
}

type Retry = (() => void) | "submit";

/** A failed call in words, with "try again" when trying again may help.
 *
 * `code` is the API's error code (`errorCode(error)`); `text` is what the
 * component says for any other failure. A connection or server failure
 * always shows the shared words instead, and a "try again" button: inside a
 * form `retry="submit"` sends the form again (with what the person typed),
 * elsewhere `retry` repeats the call. The alert itself stays a `<p>`, as
 * before, so screen readers and the journeys read the same element. */
export function ProblemNotice({ code, text, retry, busy = false, className = "font-semibold text-clay" }: {
  code: string;
  text?: string;
  retry?: Retry;
  busy?: boolean;
  className?: string;
}) {
  const r = useResilienceText();
  const connection = isConnectionProblem(code);
  const words = connection ? (code === NETWORK_FAILED ? r.network : r.server) : (text ?? r.unknown);
  return (
    <>
      <p role="alert" className={className}>{words}</p>
      {connection && retry ? (
        <button
          type={retry === "submit" ? "submit" : "button"}
          onClick={retry === "submit" ? undefined : retry}
          disabled={busy}
          data-retry=""
          className="min-h-12 rounded-card border border-ink bg-white px-4 font-semibold text-ink disabled:opacity-60"
        >
          {busy ? r.retrying : r.tryAgain}
        </button>
      ) : null}
    </>
  );
}

const subscribe = (change: () => void) => {
  window.addEventListener("online", change);
  window.addEventListener("offline", change);
  return () => {
    window.removeEventListener("online", change);
    window.removeEventListener("offline", change);
  };
};

/** The error page of the whole site or of one section, in the page's
 * language. It never shows the error itself: no message, no code, no stack
 * (in production Next.js sends none from the server anyway). */
export function ErrorPanel({ retry, home, inside = false }: {
  retry: () => void;
  home: "shop" | "seller" | "admin";
  /** Inside a section's own frame, which already has the page's <main>. */
  inside?: boolean;
}) {
  const r = useResilienceText();
  const [trying, setTrying] = useState(false);
  const offline = useSyncExternalStore(subscribe, () => !navigator.onLine, () => false);
  const target = { shop: { href: `/${r.lang}`, label: r.goHome }, seller: { href: `/${r.lang}/seller`, label: r.goSeller }, admin: { href: `/${r.lang}/admin`, label: r.goAdmin } }[home];
  const Frame = inside ? "section" : "main";
  return (
    <Frame {...(inside ? {} : { id: "main" })} data-error-page="" className="mx-auto max-w-xl space-y-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-extrabold">{r.pageTitle}</h1>
      <p role="alert">{offline ? r.offlineLead : r.pageLead}</p>
      <div className="flex flex-wrap justify-center gap-3">
        <button
          type="button"
          disabled={trying}
          onClick={() => {
            setTrying(true);
            retry();
            // retry() re-renders this section; if it fails again this panel
            // stays, so the button is given back.
            setTimeout(() => setTrying(false), 1500);
          }}
          className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60"
        >
          {trying ? r.retrying : r.tryAgain}
        </button>
        <Link href={target.href} className="inline-flex min-h-12 items-center rounded-card border border-ink px-5 font-semibold">{target.label}</Link>
      </div>
    </Frame>
  );
}
