"use client";

import "./globals.css";

import Link from "next/link";

import { FALLBACK_TEXT } from "@/lib/fallback-text";

// The whole-site error page (D-100): shown when even the root layout fails,
// so it brings its own <html> and styles. It cannot know the language for
// certain, so, like the 404 page, it speaks both, Amharic first. It never
// shows the error itself.
export default function GlobalError({ retry }: { error: unknown; retry: () => void }) {
  const am = FALLBACK_TEXT.am;
  const en = FALLBACK_TEXT.en;
  return (
    <html lang="am">
      <body className="min-h-dvh bg-paper text-ink antialiased">
        <title>{`${am.pageTitle} · ${en.pageTitle}`}</title>
        <main id="main" data-error-page="" className="mx-auto max-w-xl space-y-6 px-4 py-16 text-center">
          <div className="space-y-2">
            <h1 className="text-2xl font-extrabold">{am.pageTitle}</h1>
            <p>{am.pageLead}</p>
          </div>
          <div lang="en" className="space-y-2">
            <h2 className="text-xl font-bold">{en.pageTitle}</h2>
            <p>{en.pageLead}</p>
          </div>
          <div className="flex flex-wrap justify-center gap-3">
            <button type="button" onClick={() => retry()} className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">
              {am.tryAgain} · <span lang="en">{en.tryAgain}</span>
            </button>
            <Link href="/" className="inline-flex min-h-12 items-center rounded-card border border-ink px-5 font-semibold">
              {am.goHome} · <span lang="en">{en.goHome}</span>
            </Link>
          </div>
        </main>
      </body>
    </html>
  );
}
