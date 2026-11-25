// Guest checkout (C-07, D-108): the pure parts of the guest's page, tested
// in guest-checkout.test.ts. Every rule is the API's: the page only shows
// what it allows and sends the guest's choices.

import { apiErrorText, type Locale, type Messages } from "./i18n";

/** A refusal in words for the guest's page: the guest checkout's own words
 * first (kept in its own section, so no other page carries them, D-107's
 * page weight), then the words every page shares. Never the raw code. */
export function guestErrorText(t: Pick<Messages, "guest" | "apiErrors">, code: string): string {
  const own: Record<string, string> = t.guest.errors;
  return own[code] ?? apiErrorText(t, code);
}

const API_TRACK = "/api/v1/track/";

/** The order page on this site for the API's tracking link. The API's path
 * is the only input: anything else is refused, never followed. */
export function trackPageHref(trackingPath: string, lang: Locale): string | null {
  if (!trackingPath.startsWith(API_TRACK)) return null;
  const rest = trackingPath.slice(API_TRACK.length);
  // An order id, then the signed query; nothing that could leave the site.
  if (!/^[0-9a-f-]{36}\?expires=\d+&signature=[A-Za-z0-9_-]{20,64}$/.test(rest)) return null;
  return `/${lang}/track/${rest}`;
}

/** The ways a guest may receive one shop's part: delivered to the door, and
 * collected at the shop only while operations allow it (the founder's
 * decision of 24 November 2026: a guest pays at the door). */
export function guestDeliveryOptions<T extends { method: string }>(
  options: readonly T[] | null | undefined,
  collectionAllowed: boolean,
): T[] {
  return (options ?? []).filter((option) => collectionAllowed || option.method !== "shop_collection");
}

export type GuestForm = {
  recipient: string;
  phone: string;
  area: string;
  landmark: string;
  notes: string;
};

/** The guest's details as the API reads them (`GuestDetailsIn`): trimmed,
 * and the rider's notes left out when empty. The API checks every field. */
export function guestDetails(form: GuestForm) {
  const notes = form.notes.trim();
  return {
    recipient_name: form.recipient.trim(),
    phone: form.phone.trim(),
    delivery_area_id: form.area,
    landmark: form.landmark.trim(),
    driver_notes: notes || null,
  };
}
