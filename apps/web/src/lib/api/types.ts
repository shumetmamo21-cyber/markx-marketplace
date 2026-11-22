import type { components } from "./schema";

type Schemas = components["schemas"];

export type ProductCard = Schemas["ProductCardOut"];
export type SearchResult = Schemas["SearchOut"];
export type DeliveredToZone = Schemas["DeliveredToZoneOut"];
export type GatePhotoLink = Schemas["GatePhotoLinkOut"];
export type Product = Schemas["ProductOut"];
export type RankedOffer = Schemas["RankedOfferOut"];
export type ProductOffers = Schemas["ProductOffersOut"];
export type CategoryNode = Schemas["CategoryNode"];
export type Zone = Schemas["ZoneOut"];
export type PriceHistory = Schemas["PriceHistoryOut"];
export type PriceStep = Schemas["PriceStepOut"];
export type Reorder = Schemas["ReorderOut"];
export type SellerCustomer = Schemas["SellerCustomerOut"];
