import type { Messages } from "./i18n";

/** A seller order's or order's status in words; unknown ones as they are. */
export function statusLabel(t: Messages, status: string): string {
  return status in t.status ? t.status[status as keyof Messages["status"]] : status;
}
