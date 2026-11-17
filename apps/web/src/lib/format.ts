// Formatting that every screen shares (blueprint I.3, I.7). Money arrives
// from the API in whole santim and is never computed here.
import type { Locale } from "./i18n";

const SANTIM_PER_BIRR = 100;

/** "ETB 12,500" in English, "12,500 ብር" in Amharic; santim only when present. */
export function formatPrice(santim: number, locale: Locale): string {
  const birr = santim / SANTIM_PER_BIRR;
  const digits = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: santim % SANTIM_PER_BIRR === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(birr);
  return locale === "am" ? `${digits} ብር` : `ETB ${digits}`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** How long ago, in words: "3 hours ago", "ከ3 ሰዓት በፊት". */
export function timeAgo(iso: string, locale: Locale, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (seconds >= size) return format.format(-Math.floor(seconds / size), unit);
  }
  return format.format(0, "minute");
}

/** A date and time in Addis Ababa, where every MarkX shop is. */
export function formatDateTime(iso: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "am" ? "am-ET" : "en-GB", {
    timeZone: "Africa/Addis_Ababa",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}
