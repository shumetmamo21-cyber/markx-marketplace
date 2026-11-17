import type { components } from "./schema";

type Schemas = components["schemas"];

export type ProductCard = Schemas["ProductCardOut"];
export type SearchResult = Schemas["SearchOut"];
export type Product = Schemas["ProductOut"];
export type RankedOffer = Schemas["RankedOfferOut"];
export type ProductOffers = Schemas["ProductOffersOut"];
export type CategoryNode = Schemas["CategoryNode"];
export type Zone = Schemas["ZoneOut"];
