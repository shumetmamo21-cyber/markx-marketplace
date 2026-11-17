import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";

function keys(value: unknown, prefix = ""): string[] {
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, inner]) => keys(inner, `${prefix}${key}.`));
  }
  return [prefix.slice(0, -1)];
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1] ?? "").sort();
}

describe("messages", () => {
  it("have the same keys in both languages (blueprint I.1: two languages, equal quality)", () => {
    expect(keys(am).sort()).toEqual(keys(en).sort());
  });
  it("use the same placeholders in both languages", () => {
    const lookup = (root: unknown, path: string): string =>
      path.split(".").reduce<unknown>((node, key) => (node as Record<string, unknown>)[key], root) as string;
    for (const path of keys(en)) {
      expect(placeholders(lookup(am, path)), path).toEqual(placeholders(lookup(en, path)));
    }
  });
});
