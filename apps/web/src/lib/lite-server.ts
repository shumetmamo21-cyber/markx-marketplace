import "server-only";

import { cookies, headers } from "next/headers";

import { LITE_COOKIE, liteFrom } from "./lite";

/** Whether this request is drawn in lite mode (C-12; D-107). */
export async function isLite(): Promise<boolean> {
  const [jar, sent] = await Promise.all([cookies(), headers()]);
  return liteFrom(jar.get(LITE_COOKIE)?.value, sent.get("save-data"));
}
