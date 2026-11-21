// The error pages (D-100): every section has one, in the page's language,
// with "try again" and a way home, and none of them shows the error itself.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { NETWORK_FAILED, SERVER_FAILED } from "@/lib/api/browser";
import { FALLBACK_TEXT, resilienceText } from "@/lib/fallback-text";
import type { Locale } from "@/lib/i18n";

import SiteError from "../app/[lang]/error";
import ShopError from "../app/[lang]/(shop)/error";
import AdminError from "../app/[lang]/admin/error";
import DeskError from "../app/[lang]/admin/(desk)/error";
import SellerAreaError from "../app/[lang]/seller/error";
import SellerError from "../app/[lang]/seller/[sellerId]/error";
import GlobalError from "../app/global-error";
import { ProblemNotice, ResilienceProvider } from "./Resilience";

const MESSAGES = { am, en } as const;
const LOCALES: Locale[] = ["am", "en"];

// A server error as Next.js would forward it in development (with its
// message), so a page that printed it would be caught.
const SECRET = "connect ECONNREFUSED 10.0.0.5:5432 password=hunter2";
function thrown(): Error {
  const error = new Error(SECRET) as Error & { digest: string };
  error.digest = "DIGEST-1234567";
  error.stack = `Error: ${SECRET}\n    at Page (/app/src/app/page.tsx:12:3)`;
  return error;
}

function render(lang: Locale, Page: ComponentType<{ error: unknown; retry: () => void }>): string {
  const page = createElement(Page, { error: thrown(), retry: vi.fn() });
  return renderToStaticMarkup(createElement(ResilienceProvider, { text: resilienceText(lang, MESSAGES[lang]) }, page));
}

const SECTIONS = [
  { name: "whole site under a language", Page: SiteError, home: "", main: true },
  { name: "storefront and buyer pages", Page: ShopError, home: "", main: false },
  { name: "staff area frame and sign-in", Page: AdminError, home: "/admin", main: true },
  { name: "staff screens", Page: DeskError, home: "/admin", main: false },
  { name: "seller area frame", Page: SellerAreaError, home: "/seller", main: true },
  { name: "seller dashboard screens", Page: SellerError, home: "/seller", main: false },
];

describe("each section's error page", () => {
  for (const section of SECTIONS) {
    for (const lang of LOCALES) {
      it(`${section.name} (${lang}): in the page's language, with try again and a way back`, () => {
        const t = MESSAGES[lang];
        const html = render(lang, section.Page);
        expect(html).toContain(t.errors.pageTitle);
        expect(html).toContain(t.errors.pageLead);
        expect(html).toContain(`>${t.errors.tryAgain}</button>`);
        expect(html).toContain(`href="/${lang}${section.home}"`);
        expect(html).toContain("data-error-page");
        // Inside a section's own frame there is already a <main>.
        expect(html.includes("<main")).toBe(section.main);
        // The other language's words are not on the page.
        const other = MESSAGES[lang === "am" ? "en" : "am"];
        expect(html).not.toContain(other.errors.pageTitle);
      });
    }

    it(`${section.name}: never shows the error, its code or where it happened`, () => {
      for (const lang of LOCALES) {
        const html = render(lang, section.Page);
        for (const leak of ["ECONNREFUSED", "hunter2", "10.0.0.5", "DIGEST-1234567", "page.tsx", "Error:", "stack"]) {
          expect(html).not.toContain(leak);
        }
      }
    });
  }

  it("the go-home links name the right place", () => {
    expect(render("en", ShopError)).toContain(en.errors.goHome);
    expect(render("am", SellerError)).toContain(am.errors.goSeller);
    expect(render("en", DeskError)).toContain(en.errors.goAdmin);
  });
});

describe("the whole-site error page", () => {
  it("speaks both languages, offers try again and home, and shows nothing of the error", () => {
    const html = renderToStaticMarkup(createElement(GlobalError, { error: thrown(), retry: vi.fn() }));
    expect(html).toMatch(/^<html lang="am">/);
    for (const t of [am, en]) {
      expect(html).toContain(t.errors.pageTitle);
      expect(html).toContain(t.errors.pageLead);
      expect(html).toContain(t.errors.tryAgain);
      expect(html).toContain(t.errors.goHome);
    }
    for (const leak of ["ECONNREFUSED", "hunter2", "DIGEST-1234567", "page.tsx"]) expect(html).not.toContain(leak);
  });

  it("uses an exact copy of the message files' words", () => {
    for (const lang of LOCALES) expect(FALLBACK_TEXT[lang]).toEqual(resilienceText(lang, MESSAGES[lang]));
  });
});

describe("the problem notice", () => {
  const notice = (lang: Locale, props: Parameters<typeof ProblemNotice>[0]) =>
    renderToStaticMarkup(createElement(ResilienceProvider, { text: resilienceText(lang, MESSAGES[lang]) }, createElement(ProblemNotice, props)));

  it("says the connection dropped, in the page's language, with try again", () => {
    for (const lang of LOCALES) {
      const html = notice(lang, { code: NETWORK_FAILED, text: "component words", retry: () => undefined });
      expect(html).toContain(`<p role="alert"`);
      expect(html).toContain(MESSAGES[lang].apiErrors.network_unavailable);
      expect(html).not.toContain("component words");
      expect(html).toContain(`type="button"`);
      expect(html).toContain(MESSAGES[lang].errors.tryAgain);
    }
  });

  it("says the server failed, and inside a form sends the form again", () => {
    const html = notice("en", { code: SERVER_FAILED, retry: "submit" });
    expect(html).toContain(en.apiErrors.server_unavailable);
    expect(html).toContain(`type="submit"`);
  });

  it("shows the busy state while trying again", () => {
    const html = notice("am", { code: NETWORK_FAILED, retry: () => undefined, busy: true });
    expect(html).toContain(am.errors.retrying);
    expect(html).toContain("disabled");
  });

  it("keeps the API's own refusal in the component's words, without try again", () => {
    const html = notice("en", { code: "too_many_open_orders", text: en.apiErrors.too_many_open_orders, retry: () => undefined });
    expect(html).toContain(en.apiErrors.too_many_open_orders);
    expect(html).not.toContain("<button");
  });

  it("falls back to the generic words when a component has none", () => {
    expect(notice("am", { code: "something_new" })).toContain(am.apiErrors.unknown);
  });
});
