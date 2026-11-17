// Languages and their messages (blueprint F.1, I.7). The address carries the
// language: /am/... and /en/... Amharic is the default.
import type en from "../../messages/en.json";

export const LOCALES = ["am", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "am";
export const LOCALE_COOKIE = "markx_lang";

export type Messages = typeof en;

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

export function otherLocale(locale: Locale): Locale {
  return locale === "am" ? "en" : "am";
}

/** Fill `{name}` placeholders in a message. */
export function fill(message: string, values: Record<string, string | number>): string {
  return message.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}
