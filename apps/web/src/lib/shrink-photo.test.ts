import { describe, expect, it } from "vitest";

import { chooseUpload, SHRINK_LONGEST_SIDE, shrinkPlan, shrunkName, withShrunkPhoto } from "./shrink-photo";

describe("shrinkPlan (S-06)", () => {
  it("brings a camera photo down to the longest side, keeping its shape", () => {
    expect(shrinkPlan({ type: "image/jpeg", size: 4_800_000 }, { width: 4000, height: 3000 })).toEqual({
      shrink: true, width: SHRINK_LONGEST_SIDE, height: 1200, type: "image/jpeg",
    });
    expect(shrinkPlan({ type: "image/jpeg", size: 3_000_000 }, { width: 3000, height: 4000 })).toEqual({
      shrink: true, width: 1200, height: SHRINK_LONGEST_SIDE, type: "image/jpeg",
    });
  });

  it("re-encodes a heavy photo that is already within the side, at its own size", () => {
    expect(shrinkPlan({ type: "image/jpeg", size: 2_000_000 }, { width: 1200, height: 900 })).toEqual({
      shrink: true, width: 1200, height: 900, type: "image/jpeg",
    });
  });

  it("leaves a small photo alone", () => {
    expect(shrinkPlan({ type: "image/jpeg", size: 120_000 }, { width: 800, height: 600 })).toEqual({ shrink: false, reason: "already_small" });
  });

  it("writes a PNG or WebP as WebP, which keeps transparency", () => {
    const plan = shrinkPlan({ type: "image/png", size: 3_000_000 }, { width: 2000, height: 2000 });
    expect(plan).toEqual({ shrink: true, width: 1600, height: 1600, type: "image/webp" });
  });

  it("never touches anything that is not a JPEG, PNG or WebP: the server judges it", () => {
    expect(shrinkPlan({ type: "application/pdf", size: 9_000_000 }, { width: 4000, height: 3000 })).toEqual({ shrink: false, reason: "not_a_picture" });
    expect(shrinkPlan({ type: "image/heic", size: 9_000_000 }, { width: 4000, height: 3000 }).shrink).toBe(false);
    expect(shrinkPlan({ type: "image/jpeg", size: 9_000_000 }, { width: 0, height: 3000 }).shrink).toBe(false);
  });
});

describe("chooseUpload (S-06)", () => {
  const original = { type: "image/jpeg", size: 4_000_000, name: "a" };
  it("sends the smaller file", () => {
    const shrunk = { type: "image/jpeg", size: 300_000, name: "b" };
    expect(chooseUpload(original, shrunk, "image/jpeg")).toBe(shrunk);
  });
  it("sends the original when shrinking did not help or failed", () => {
    expect(chooseUpload(original, { type: "image/jpeg", size: 5_000_000, name: "b" }, "image/jpeg")).toBe(original);
    expect(chooseUpload(original, null, "image/jpeg")).toBe(original);
    expect(chooseUpload(original, { type: "image/jpeg", size: 0, name: "b" }, "image/jpeg")).toBe(original);
  });
  it("sends the original when the browser wrote another type than asked (no WebP encoder)", () => {
    expect(chooseUpload(original, { type: "image/png", size: 100, name: "b" }, "image/webp")).toBe(original);
  });
});

describe("shrunkName", () => {
  it("gives the new type's extension", () => {
    expect(shrunkName("IMG_2041.JPG", "image/jpeg")).toBe("IMG_2041.jpg");
    expect(shrunkName("logo.png", "image/webp")).toBe("logo.webp");
    expect(shrunkName(".png", "image/webp")).toBe("photo.webp");
  });
});

describe("withShrunkPhoto outside a browser", () => {
  it("sends the form unchanged when the photo cannot be drawn here", async () => {
    const form = new FormData();
    const file = new File([new Uint8Array(10)], "gate.jpg", { type: "image/jpeg" });
    form.set("file", file);
    const sent = await withShrunkPhoto(form);
    expect(sent.get("file")).toBe(file);
  });
});
