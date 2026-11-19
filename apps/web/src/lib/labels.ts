import type { Messages } from "./i18n";

/** A seller order's or order's status in words; unknown ones as they are. */
export function statusLabel(t: Messages, status: string): string {
  return status in t.status ? t.status[status as keyof Messages["status"]] : status;
}

type LabelGroup = keyof Messages["labels"];

/** A code the API sends (a staff role, a review state, a document or product
 * status) in the page's language. A code the app does not know yet is shown
 * as it is rather than hidden, so nothing silently disappears. */
export function codeLabel(t: Pick<Messages, "labels">, group: LabelGroup, code: string): string {
  const labels: Record<string, string> = t.labels[group];
  return labels[code] ?? code;
}
