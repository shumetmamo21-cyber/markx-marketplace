import "server-only";

import type { Locale, Messages } from "./i18n";

const loaders: Record<Locale, () => Promise<Messages>> = {
  am: () => import("../../messages/am.json").then((module) => module.default),
  en: () => import("../../messages/en.json").then((module) => module.default),
};

export function getMessages(locale: Locale): Promise<Messages> {
  return loaders[locale]();
}
