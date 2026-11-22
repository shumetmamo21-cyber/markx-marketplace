import "server-only";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { forwardedHeaders } from "./api/forwarded";
import type { components } from "./api/schema";
import type { Locale, Messages } from "./i18n";

// What the QR routes read (S-10; D-107): public data only, the same the
// shop's and the product's pages show, so they need no visitor's cookies.

const API_ORIGIN = process.env.MARKX_API_ORIGIN ?? "http://127.0.0.1:8000";

type Store = components["schemas"]["PublicStoreOut"];
type Product = components["schemas"]["ProductOut"];

export function messagesFor(lang: Locale): Messages {
  return lang === "am" ? (am as Messages) : en;
}

async function read<T>(request: Request, path: string): Promise<T | null> {
  const response = await fetch(`${API_ORIGIN}${path}`, { cache: "no-store", headers: forwardedHeaders(request.headers) });
  if (!response.ok) return null;
  return (await response.json()) as T;
}

export function publicStore(request: Request, slug: string): Promise<Store | null> {
  return read<Store>(request, `/api/v1/catalog/stores/${encodeURIComponent(slug)}`);
}

export function publicProduct(request: Request, slug: string, lang: Locale): Promise<Product | null> {
  return read<Product>(request, `/api/v1/catalog/products/${encodeURIComponent(slug)}?lang=${lang}`);
}
