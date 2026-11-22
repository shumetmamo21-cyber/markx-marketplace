import { describe, expect, it } from "vitest";

import { liteChoice, liteFrom, liteReturnPath } from "./lite";
import { safeNext } from "./safe-next";

describe("lite mode (C-12)", () => {
  it("follows the person's remembered choice first", () => {
    expect(liteFrom("1", null)).toBe(true);
    expect(liteFrom("0", "on")).toBe(false); // switched off: Save-Data does not override it
  });

  it("turns on by itself when the phone asks to save data", () => {
    expect(liteFrom(undefined, "on")).toBe(true);
    expect(liteFrom(undefined, " On ")).toBe(true);
    expect(liteFrom(null, "off")).toBe(false);
    expect(liteFrom(undefined, undefined)).toBe(false);
  });

  it("ignores a cookie that is not one of its two values", () => {
    expect(liteFrom("yes", null)).toBe(false);
    expect(liteFrom("yes", "on")).toBe(true);
  });

  it("accepts only 1 and 0 from the switch", () => {
    expect(liteChoice("1")).toBe("1");
    expect(liteChoice("0")).toBe("0");
    expect(liteChoice("true")).toBeNull();
    expect(liteChoice(null)).toBeNull();
  });
});

describe("the way back after the switch", () => {
  it("is the page it came from, on this site only", () => {
    expect(liteReturnPath("https://markx.example/am/p/tecno-spark-20?zone=bole")).toBe("/am/p/tecno-spark-20?zone=bole");
    // Another site's page becomes a path here, which safeNext then judges.
    expect(safeNext(liteReturnPath("https://evil.example//evil.example/x"), "/am")).toBe("/am");
    expect(liteReturnPath("https://markx.example/am/lite?on=1")).toBeNull();
    expect(liteReturnPath("not a url")).toBeNull();
    expect(liteReturnPath(null)).toBeNull();
  });
});
