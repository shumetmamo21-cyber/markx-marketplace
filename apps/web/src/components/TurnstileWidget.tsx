"use client";

import { useEffect, useRef } from "react";

// Cloudflare Turnstile, the "are you a person" check before a sign-in code is
// sent (blueprint D.2, H.3; D-085). Only the public site key is here; the
// secret stays on the API, which asks Cloudflare whether the token is real.
//
// A token is good for one check only, so the form bumps `resetKey` after
// every attempt and this asks Cloudflare for a fresh one.

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
export const SIGN_IN_ACTION = "sign_in"; // must match markx/core/botcheck.py
// A guest's order (C-07, D-108); the API refuses a token solved for signing in.
export const GUEST_CHECKOUT_ACTION = "guest_checkout"; // must match markx/core/botcheck.py

type RenderOptions = {
  sitekey: string;
  action: string;
  callback: (token: string) => void;
  "expired-callback": () => void;
  "error-callback": () => void;
  "timeout-callback": () => void;
};
type Turnstile = {
  render: (element: HTMLElement, options: RenderOptions) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
};
declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

let loading: Promise<Turnstile> | null = null;

function loadTurnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  loading ??= new Promise<Turnstile>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error("turnstile missing")));
    script.onerror = () => {
      loading = null; // let a later attempt try again
      reject(new Error("turnstile did not load"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

export function TurnstileWidget({
  siteKey,
  resetKey,
  onToken,
  action = SIGN_IN_ACTION,
}: {
  siteKey: string;
  resetKey: number;
  onToken: (token: string | null) => void;
  action?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);
  const report = useRef(onToken);
  useEffect(() => {
    report.current = onToken;
  }, [onToken]);

  useEffect(() => {
    let cancelled = false;
    loadTurnstile()
      .then((turnstile) => {
        if (cancelled || !box.current) return;
        widget.current = turnstile.render(box.current, {
          sitekey: siteKey,
          action,
          callback: (token) => report.current(token),
          "expired-callback": () => report.current(null),
          "error-callback": () => report.current(null),
          "timeout-callback": () => report.current(null),
        });
      })
      .catch(() => report.current(null)); // no token: the API refuses, nothing is sent
    return () => {
      cancelled = true;
      if (widget.current && window.turnstile) window.turnstile.remove(widget.current);
      widget.current = null;
    };
  }, [siteKey, action]);

  useEffect(() => {
    if (resetKey > 0 && widget.current && window.turnstile) {
      report.current(null);
      window.turnstile.reset(widget.current);
    }
  }, [resetKey]);

  return <div ref={box} className="min-h-16" />;
}
