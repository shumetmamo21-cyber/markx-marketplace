// The Ethiopian calendar and clock (blueprint C-05, I.7; D-106). In Amharic,
// MarkX shows dates in the Ethiopian calendar with the Gregorian date in
// brackets, and times on the Ethiopian clock, where 9:00 in the morning is
// 3:00. Pure arithmetic, so the server and the phone always agree; the tests
// check every day from 1900 to 2100 against the calendar data built into
// Node (ICU).
//
// The month names and the four parts of the day are the Amharic words of
// that same data (CLDR), listed here like the currency word in format.ts.
// PROVISIONAL (P-106-1): how a date and a time are laid out; the native
// editor reviews them with every other Amharic text before launch.

/** Meskerem 1 of year 0 (Amete Mihret) as a Julian day number. With it,
 * every fourth year of a cycle is the leap year (year % 4 === 3). */
const EPOCH = 1_723_856;
const ADDIS_OFFSET_MS = 3 * 3_600_000; // UTC+3 all year: Ethiopia has no summer time

export const ETHIOPIAN_MONTHS = [
  "መስከረም", "ጥቅምት", "ኅዳር", "ታኅሣሥ", "ጥር", "የካቲት", "መጋቢት",
  "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜን",
] as const;

/** The four parts of the day; each starts at 12 on the Ethiopian clock. */
const DAY_PARTS = [
  { from: 0, words: "በሌሊት" }, // night: 6:00 to 11:59 (midnight to 5:59)
  { from: 6, words: "ጥዋት" }, // morning: 12:00 to 5:59 (6:00 to 11:59)
  { from: 12, words: "ከሰዓት" }, // afternoon: 6:00 to 11:59 (noon to 5:59 pm)
  { from: 18, words: "በምሽት" }, // evening: 12:00 to 5:59 (6:00 pm to 11:59 pm)
] as const;

export type EthiopianDate = { year: number; month: number; day: number };

function julianDay(year: number, month: number, day: number): number {
  const a = Math.floor((14 - month) / 12);
  const y = year + 4800 - a;
  const m = month + 12 * a - 3;
  return day + Math.floor((153 * m + 2) / 5) + 365 * y + Math.floor(y / 4) - Math.floor(y / 100) + Math.floor(y / 400) - 32_045;
}

/** A Gregorian calendar day (month 1 to 12) as an Ethiopian one (month 1 to 13). */
export function toEthiopian(year: number, month: number, day: number): EthiopianDate {
  const days = julianDay(year, month, day) - EPOCH;
  const cycle = Math.floor(days / 1461);
  const inCycle = days - cycle * 1461; // 0 to 1460: four years, the last one long
  const yearInCycle = Math.floor(inCycle / 365) - Math.floor(inCycle / 1460);
  const dayOfYear = (inCycle % 365) + 365 * Math.floor(inCycle / 1460);
  return {
    year: 4 * cycle + yearInCycle,
    month: Math.floor(dayOfYear / 30) + 1,
    day: (dayOfYear % 30) + 1,
  };
}

type AddisParts = { year: number; month: number; day: number; hour: number; minute: number };

/** The moment's calendar day and clock time in Addis Ababa. */
export function addisParts(iso: string): AddisParts {
  const local = new Date(new Date(iso).getTime() + ADDIS_OFFSET_MS);
  return {
    year: local.getUTCFullYear(),
    month: local.getUTCMonth() + 1,
    day: local.getUTCDate(),
    hour: local.getUTCHours(),
    minute: local.getUTCMinutes(),
  };
}

/** "13 ኅዳር 2019": the day, the month's name and the year. */
export function ethiopianDateText(date: EthiopianDate): string {
  return `${date.day} ${ETHIOPIAN_MONTHS[date.month - 1]} ${date.year}`;
}

/** The Ethiopian clock: "ጥዋት 3:05" for 9:05 in the morning (blueprint I.7). */
export function ethiopianClockText(hour: number, minute: number): string {
  const part = [...DAY_PARTS].reverse().find((p) => hour >= p.from) ?? DAY_PARTS[0];
  const onClock = (hour + 6) % 12 || 12;
  return `${part.words} ${onClock}:${String(minute).padStart(2, "0")}`;
}
