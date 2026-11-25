import "server-only";

import { serverApi } from "./api/server";
import type { components } from "./api/schema";

export type Me = components["schemas"]["MeOut"];

/** The signed-in person, or null. The API decides; this only asks. */
export async function getMe(): Promise<Me | null> {
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/me", {});
  if (response.status === 401 || !data) return null;
  return data;
}

export type SignInMethods = components["schemas"]["SignInMethodsOut"];

/** Which ways of signing in the server offers (D-101). When the API cannot
 * be asked, none: the page says signing in is unavailable, and offers no
 * button that would fail. */
export async function getSignInMethods(): Promise<SignInMethods> {
  const api = await serverApi();
  try {
    const { data } = await api.GET("/api/v1/auth/methods", {});
    if (data) return data;
  } catch {
    // The API is unreachable: the error page and "try again" are for pages
    // that need data; a sign-in page still renders and says so.
  }
  return { telegram: false, sms: false, staff_phone_password: false };
}

export type GuestCheckoutTerms = components["schemas"]["GuestCheckoutTermsOut"];

/** What ordering as a guest offers today (C-07, D-108). When the API cannot
 * be asked, guest checkout is off: no form is offered that would fail. */
export async function getGuestCheckoutTerms(): Promise<GuestCheckoutTerms> {
  const api = await serverApi();
  try {
    const { data } = await api.GET("/api/v1/checkout/guest/terms", {});
    if (data) return data;
  } catch {
    // The API is unreachable; the page says guest checkout is unavailable.
  }
  return { enabled: false, max_order_value_santim: 0, shop_collection: false };
}
