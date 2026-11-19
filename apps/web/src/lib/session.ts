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
