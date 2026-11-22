// Formatting that every screen shares (blueprint I.3, I.7). Money arrives
// from the API in whole santim and is never computed here.
import { addisParts, ethiopianClockText, ethiopianDateText, toEthiopian } from "./ethiopian";
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

const ADDIS = "Africa/Addis_Ababa";

/** A date and time in Addis Ababa, where every MarkX shop is. In Amharic
 * (blueprint C-05, I.7): the Ethiopian date, the Gregorian date in brackets,
 * then the time on the Ethiopian clock, "13 ኅዳር 2019 (22 ኖቬም 2026) ጥዋት 3:30"
 * for 9:30 in the morning. English is unchanged: "22 Nov 2026, 09:30". */
export function formatDateTime(iso: string, locale: Locale): string {
  if (locale !== "am") {
    return new Intl.DateTimeFormat("en-GB", { timeZone: ADDIS, dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
  }
  const here = addisParts(iso);
  const gregorian = new Intl.DateTimeFormat("am-ET", { timeZone: ADDIS, dateStyle: "medium" }).format(new Date(iso));
  return `${ethiopianDateText(toEthiopian(here.year, here.month, here.day))} (${gregorian}) ${ethiopianClockText(here.hour, here.minute)}`;
}

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A calendar day the API sends as YYYY-MM-DD (a document's expiry, a week's
 * first day). In Amharic the Ethiopian date with the Gregorian one in
 * brackets, "7 ኅዳር 2019 (16 ኖቬም 2026)"; in English "16 Nov 2026". Anything
 * that is not such a day is shown as it came. */
export function formatDate(day: string, locale: Locale): string {
  const match = ISO_DAY.exec(day);
  if (!match) return day;
  const [year, month, date] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const noon = new Date(Date.UTC(year, month - 1, date, 12));
  if (noon.getUTCMonth() !== month - 1 || noon.getUTCDate() !== date) return day;
  // Noon UTC is the same calendar day everywhere from UTC-11 to UTC+11, Addis Ababa included.
  const gregorian = new Intl.DateTimeFormat(locale === "am" ? "am-ET" : "en-GB", { timeZone: "UTC", dateStyle: "medium" }).format(noon);
  if (locale !== "am") return gregorian;
  return `${ethiopianDateText(toEthiopian(year, month, date))} (${gregorian})`;
}

/** Whether a moment has passed. For server pages rendered per request, where
 * "now" is the moment of that request. */
export function isPast(iso: string, now: Date = new Date()): boolean {
  return new Date(iso).getTime() < now.getTime();
}

/** A share the API computed (0 to 1) as a whole percentage, "87%". The page
 * shows it; the API decides what it measures. */
export function formatShare(share: number): string {
  return `${Math.round(Math.min(Math.max(share, 0), 1) * 100)}%`;
}

/** The calendar day in Addis Ababa as YYYY-MM-DD, for date fields. */
export function addisDay(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Addis_Ababa", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** An average rating from the API (1 to 5, two places) to one place, "4.5". */
export function formatRating(average: number): string {
  return (Math.round(average * 10) / 10).toFixed(1);
}
