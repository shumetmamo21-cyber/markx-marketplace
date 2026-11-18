import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

const FALLBACK = "/en/orders";

describe("safeNext (SEC-1: no redirect off the site after sign-in)", () => {
  it.each([
    "/en/cart",
    "/am/orders/0193a7c2-0000-7000-8000-000000000001",
    "/en/seller",
    "/en/search?q=tecno&sort=price",
    "/en/p/tecno-spark-20#offers",
  ])("keeps the internal address %s", (value) => {
    expect(safeNext(value, FALLBACK)).toBe(value);
  });

  it.each([
    // Backslashes: browsers treat them as slashes.
    "/\\evil.example",
    "/\\/evil.example",
    "\\\\evil.example",
    "/%5Cevil.example",
    "/%5cevil.example",
    "/%255Cevil.example",
    "/%5C%5Cevil.example",
    // Protocol-relative and absolute addresses.
    "//evil.example",
    "//evil.example/en/cart",
    "/%2Fevil.example",
    "/%2F%2Fevil.example",
    "%2F%2Fevil.example",
    "https://evil.example",
    "http:evil.example",
    "javascript:alert(1)",
    "data:text/html,hi",
    // Characters browsers silently drop.
    "/\t/evil.example",
    "/\n/evil.example",
    "/%09/evil.example",
    "/%0A/evil.example",
    "/%00/evil.example",
    // Not a path at all, or broken encoding.
    "evil.example",
    "",
    "/%E0%A4%A",
  ])("refuses %j", (value) => {
    expect(safeNext(value, FALLBACK)).toBe(FALLBACK);
  });

  it("takes the first of repeated parameters, and falls back when there is none", () => {
    expect(safeNext(["/en/cart", "//evil.example"], FALLBACK)).toBe("/en/cart");
    expect(safeNext(["//evil.example", "/en/cart"], FALLBACK)).toBe(FALLBACK);
    expect(safeNext(undefined, FALLBACK)).toBe(FALLBACK);
    expect(safeNext(null, FALLBACK)).toBe(FALLBACK);
  });

  it("refuses an absurdly long address", () => {
    expect(safeNext(`/en/${"a".repeat(3000)}`, FALLBACK)).toBe(FALLBACK);
  });
});
