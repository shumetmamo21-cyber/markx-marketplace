import { describe, expect, it } from "vitest";

import { webEnvironmentProblems } from "../../deploy/check-env.mjs";

const production = {
  MARKX_ENV: "production",
  NODE_ENV: "production",
  MARKX_API_ORIGIN: "http://api:8000",
  MARKX_PUBLIC_ORIGIN: "https://markx.example",
  MARKX_MEDIA_ORIGIN: "https://media.markx.example",
  MARKX_TURNSTILE_SITE_KEY: "test-only-site-key",
};

describe("webEnvironmentProblems (D-091)", () => {
  it("accepts a complete staging or production environment", () => {
    expect(webEnvironmentProblems(production)).toEqual([]);
    expect(webEnvironmentProblems({ ...production, MARKX_ENV: "staging" })).toEqual([]);
  });

  it("requires nothing on a laptop or in CI", () => {
    expect(webEnvironmentProblems({})).toEqual([]);
    expect(webEnvironmentProblems({ MARKX_ENV: "local" })).toEqual([]);
    expect(webEnvironmentProblems({ MARKX_ENV: "test", NODE_ENV: "production" })).toEqual([]);
  });

  it("refuses an unknown stage instead of treating it as a laptop", () => {
    expect(webEnvironmentProblems({ MARKX_ENV: "prod" })).toEqual([
      'MARKX_ENV must be local, test, staging or production, not "prod"',
    ]);
  });

  it.each([
    ["NODE_ENV", "development", "NODE_ENV must be production"],
    ["MARKX_API_ORIGIN", undefined, "MARKX_API_ORIGIN"],
    ["MARKX_API_ORIGIN", "http://api:8000/api", "MARKX_API_ORIGIN"],
    ["MARKX_PUBLIC_ORIGIN", "http://markx.example", "MARKX_PUBLIC_ORIGIN"],
    ["MARKX_PUBLIC_ORIGIN", undefined, "MARKX_PUBLIC_ORIGIN"],
    ["MARKX_MEDIA_ORIGIN", undefined, "MARKX_MEDIA_ORIGIN"],
    ["MARKX_MEDIA_ORIGIN", "http://media.markx.example", "MARKX_MEDIA_ORIGIN"],
    ["MARKX_MEDIA_ORIGIN", "https://markx.example", "on its own domain"],
    ["MARKX_TURNSTILE_SITE_KEY", undefined, "MARKX_TURNSTILE_SITE_KEY must be set"],
    ["MARKX_TURNSTILE_SITE_KEY", "1x00000000000000000000AA", "not a Cloudflare test key"],
    ["MARKX_HSTS_MAX_AGE", "31536000", "the reverse proxy sends HSTS"],
  ])("refuses %s=%s by name", (name, value, expected) => {
    const problems = webEnvironmentProblems({ ...production, [name]: value });
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain(expected);
  });

  it("never repeats a value in a refusal", () => {
    const problems = webEnvironmentProblems({ ...production, MARKX_TURNSTILE_SITE_KEY: "1x00000000000000000000AA" });
    expect(problems.join(" ")).not.toContain("1x00000000000000000000AA");
  });
});
