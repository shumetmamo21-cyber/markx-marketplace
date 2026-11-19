import { describe, expect, it } from "vitest";

import { forwardedHeaders } from "./forwarded";

const from = (values: Record<string, string>) => new Headers(values);

describe("forwardedHeaders", () => {
  it("passes on the address the proxy saw, and the request id", () => {
    expect(forwardedHeaders(from({ "x-forwarded-for": "196.188.12.34", "x-request-id": "abc123" }))).toEqual({
      "x-forwarded-for": "196.188.12.34",
      "x-request-id": "abc123",
    });
  });

  it("keeps only the nearest address of a chain", () => {
    expect(forwardedHeaders(from({ "x-forwarded-for": "6.6.6.6, 196.188.12.34" }))).toEqual({
      "x-forwarded-for": "196.188.12.34",
    });
  });

  it("accepts an IPv6 address", () => {
    expect(forwardedHeaders(from({ "x-forwarded-for": "2001:db8::1" }))["x-forwarded-for"]).toBe("2001:db8::1");
  });

  it("passes nothing that is not an address or a plain id", () => {
    expect(
      forwardedHeaders(from({ "x-forwarded-for": "evil.example", "x-request-id": 'x"; drop table' })),
    ).toEqual({});
    // Headers itself refuses a line break; a raw source must not get one through either.
    const raw = { get: (name: string) => (name === "x-forwarded-for" ? "1.2.3.4\r\nX-Admin: 1" : null) };
    expect(forwardedHeaders(raw)).toEqual({});
    expect(forwardedHeaders(from({}))).toEqual({});
  });
});
