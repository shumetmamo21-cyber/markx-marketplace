// The words of the error pages and of a failed call, in both languages, for
// the one place that cannot read the message files: the whole-site error page
// (global-error.tsx replaces the root layout, so nothing is handed to it), and
// as a safety net if the root layout's provider is ever missing. Importing the
// message files here would put all of both into every page's script.
//
// A COPY of messages/{am,en}.json ("apiErrors" and "errors"):
// fallback-text.test.ts fails if the two ever differ. Change the message
// files, then this file.

import type { Locale, Messages } from "./i18n";

export type ResilienceText = {
  lang: Locale;
  network: string;
  server: string;
  /** Any other failure, when the component has no words of its own. */
  unknown: string;
  tryAgain: string;
  retrying: string;
  pageTitle: string;
  pageLead: string;
  offlineLead: string;
  goHome: string;
  goSeller: string;
  goAdmin: string;
};

/** The words from the page's message file, for the root layout's provider. */
export function resilienceText(lang: Locale, t: Pick<Messages, "apiErrors" | "errors">): ResilienceText {
  return {
    lang,
    network: t.apiErrors.network_unavailable,
    server: t.apiErrors.server_unavailable,
    unknown: t.apiErrors.unknown,
    tryAgain: t.errors.tryAgain,
    retrying: t.errors.retrying,
    pageTitle: t.errors.pageTitle,
    pageLead: t.errors.pageLead,
    offlineLead: t.errors.offlineLead,
    goHome: t.errors.goHome,
    goSeller: t.errors.goSeller,
    goAdmin: t.errors.goAdmin,
  };
}

export const FALLBACK_TEXT: Record<Locale, ResilienceText> = {
  am: {
    lang: "am",
    network: "ግንኙነት የለም። ኢንተርኔትዎን ያረጋግጡ፣ ከዚያ እንደገና ይሞክሩ።",
    server: "ማርክኤክስ አሁን መልስ መስጠት አልቻለም። እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።",
    unknown: "የሆነ ችግር ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።",
    tryAgain: "እንደገና ይሞክሩ",
    retrying: "እንደገና በመሞከር ላይ…",
    pageTitle: "ይህን ገጽ ማሳየት አልተቻለም",
    pageLead: "በእኛ በኩል ወይም በግንኙነቱ ላይ ችግር ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።",
    offlineLead: "ከኢንተርኔት ጋር ያልተገናኙ ይመስላል። ግንኙነትዎን ያረጋግጡ፣ ከዚያ እንደገና ይሞክሩ።",
    goHome: "ወደ መነሻ ገጽ ይሂዱ",
    goSeller: "ወደ ሻጭ ክፍል ይሂዱ",
    goAdmin: "ወደ ሠራተኞች ክፍል ይሂዱ",
  },
  en: {
    lang: "en",
    network: "No connection. Check your internet, then try again.",
    server: "MarkX could not answer just now. Please try again in a moment.",
    unknown: "Something went wrong. Please try again.",
    tryAgain: "Try again",
    retrying: "Trying again…",
    pageTitle: "This page could not be shown",
    pageLead: "Something went wrong on our side or with the connection. Please try again.",
    offlineLead: "You seem to be offline. Check your internet connection, then try again.",
    goHome: "Go to the home page",
    goSeller: "Go to the seller area",
    goAdmin: "Go to the staff area",
  },
};
