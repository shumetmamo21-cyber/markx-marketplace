// S-06 (blueprint F.6; D-107): a photo is made smaller on the phone before
// it is sent, so a seller on a prepaid data bundle does not pay to upload a
// 5 MB camera file. This is only a saving: the server still checks every
// upload itself (its size limit, that the bytes are a picture), decodes it,
// strips everything but the pixels and draws its own sizes (D-062). Nothing
// here is trusted, and when anything goes wrong the original file is sent
// unchanged for the server to judge.

// PROVISIONAL (P-107-5, D-107): the longest side a photo keeps on the phone.
// The server's largest size is 1,600 pixels (problem evidence), so nothing the
// server keeps is lost.
export const SHRINK_LONGEST_SIDE = 1600;
// PROVISIONAL (P-107-5, D-107): JPEG quality on the phone; a photo already
// within the side and under this size is sent as it is.
export const SHRINK_QUALITY = 0.82;
export const SHRINK_SKIP_BELOW_BYTES = 400_000;

const PICTURES = new Set(["image/jpeg", "image/png", "image/webp"]);

export type ShrinkPlan =
  | { shrink: false; reason: "not_a_picture" | "already_small" }
  | { shrink: true; width: number; height: number; type: "image/jpeg" | "image/webp" };

/** What to do with one photo, from its type, size in bytes and pixel size.
 * Pure, so it is tested without a browser. A JPEG stays a JPEG; a PNG or
 * WebP becomes WebP, which keeps transparency (a shop's logo). */
export function shrinkPlan(file: { type: string; size: number }, pixels: { width: number; height: number }): ShrinkPlan {
  if (!PICTURES.has(file.type) || pixels.width <= 0 || pixels.height <= 0) {
    return { shrink: false, reason: "not_a_picture" };
  }
  const longest = Math.max(pixels.width, pixels.height);
  if (longest <= SHRINK_LONGEST_SIDE && file.size <= SHRINK_SKIP_BELOW_BYTES) {
    return { shrink: false, reason: "already_small" };
  }
  const scale = Math.min(1, SHRINK_LONGEST_SIDE / longest);
  return {
    shrink: true,
    width: Math.max(1, Math.round(pixels.width * scale)),
    height: Math.max(1, Math.round(pixels.height * scale)),
    type: file.type === "image/jpeg" ? "image/jpeg" : "image/webp",
  };
}

/** The file to send: the smaller one, only when the browser really made the
 * type that was asked for (a browser that cannot write WebP answers PNG). */
export function chooseUpload<T extends { type: string; size: number }>(original: T, shrunk: T | null, wanted: string): T {
  if (!shrunk || shrunk.type !== wanted || shrunk.size <= 0) return original;
  return shrunk.size < original.size ? shrunk : original;
}

/** The new file's name: the same name with the extension of its new type. */
export function shrunkName(name: string, type: string): string {
  const extension = type === "image/jpeg" ? "jpg" : "webp";
  const stem = name.replace(/\.[A-Za-z0-9]{1,5}$/, "") || "photo";
  return `${stem}.${extension}`;
}

/** In the browser: the photo made smaller, or the original when it is small
 * already, cannot be read, or would not get smaller. Never throws. The
 * picture is drawn upright (the camera's rotation applied), which also
 * leaves its location and camera data behind. */
export async function shrinkPhoto(file: File): Promise<File> {
  try {
    if (typeof createImageBitmap !== "function" || typeof document === "undefined") return file;
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    try {
      const plan = shrinkPlan(file, bitmap);
      if (!plan.shrink) return file;
      const canvas = document.createElement("canvas");
      canvas.width = plan.width;
      canvas.height = plan.height;
      const context = canvas.getContext("2d");
      if (!context) return file;
      context.drawImage(bitmap, 0, 0, plan.width, plan.height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, plan.type, SHRINK_QUALITY));
      const shrunk = blob ? new File([blob], shrunkName(file.name, blob.type), { type: blob.type, lastModified: file.lastModified }) : null;
      return chooseUpload(file, shrunk, plan.type);
    } finally {
      bitmap.close();
    }
  } catch {
    return file;
  }
}

/** The same form with its photo field shrunk, ready for `sendForm`. */
export async function withShrunkPhoto(form: FormData, field = "file"): Promise<FormData> {
  const value = form.get(field);
  if (!(value instanceof File) || value.size === 0) return form;
  const smaller = await shrinkPhoto(value);
  if (smaller === value) return form;
  form.set(field, smaller, smaller.name);
  return form;
}
