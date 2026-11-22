"use client";

import { useState } from "react";

import { qrMatrix } from "@/lib/qr";
import { CARD_SIZES, type CardFormat, cardLayout } from "@/lib/share";

export type CardText = {
  brand: string; // the wordmark in the page's language
  name: string; // the shop's or the product's name
  lines: string[]; // a level, "verified", a price, a number of sellers
  scan: string; // "Scan to open on MarkX"
  link: string; // the page's address, also in the QR code
};

// The share cards (S-10; D-107): a picture the size Telegram shows a post
// (1200 × 630) and a tall one for TikTok or a story (1080 × 1920), drawn here
// on the phone and saved as PNG. Only on the share page, so no other page
// carries this script or the font. The font is Noto Sans Ethiopic (OFL,
// assets/fonts), so Amharic is drawn the same on every phone.
const FONT_FAMILY = "MarkX Card";
const FONTS = [
  new URL("../../assets/fonts/noto-sans-ethiopic-ethiopic-700-normal.woff", import.meta.url),
  new URL("../../assets/fonts/noto-sans-ethiopic-latin-700-normal.woff", import.meta.url),
];
const INK = "#0e1b2a";
const PAPER = "#faf7f2";
const ADEY = "#f5b700";
const HIGHLAND = "#11694e";
const SLATE = "#5b6675";

let fontsReady: Promise<void> | null = null;
function loadFonts(): Promise<void> {
  fontsReady ??= Promise.all(
    FONTS.map(async (url) => {
      const face = new FontFace(FONT_FAMILY, `url(${url.href})`, { weight: "700" });
      document.fonts.add(await face.load());
    }),
  ).then(() => undefined);
  return fontsReady;
}

function wrap(context: CanvasRenderingContext2D, text: string, width: number, maxLines: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (context.measureText(next).width <= width || !line) {
      line = next;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    kept[maxLines - 1] = `${kept[maxLines - 1]}…`;
    return kept;
  }
  return lines;
}

async function draw(format: CardFormat, text: CardText): Promise<Blob | null> {
  await loadFonts();
  const { width, height } = CARD_SIZES[format];
  const layout = cardLayout(format);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const c = canvas.getContext("2d");
  if (!c) return null;
  const font = (size: number) => `700 ${size}px "${FONT_FAMILY}"`;
  c.fillStyle = PAPER;
  c.fillRect(0, 0, width, height);
  // The QR code on white, with its quiet zone.
  const { qr } = layout;
  c.fillStyle = "#ffffff";
  c.fillRect(qr.panelX, qr.panelY, qr.panelWidth, qr.panelHeight);
  const matrix = qrMatrix(text.link);
  const cell = Math.floor(qr.side / (matrix.length + 8));
  const left = qr.x + Math.floor((qr.side - cell * matrix.length) / 2);
  const top = qr.y + Math.floor((qr.side - cell * matrix.length) / 2);
  c.fillStyle = "#000000";
  matrix.forEach((row, y) => row.forEach((dark, x) => dark && c.fillRect(left + x * cell, top + y * cell, cell, cell)));
  c.textBaseline = "top";
  c.fillStyle = INK;
  c.font = font(layout.scanSize);
  c.fillText(text.scan, qr.textX, qr.scanY, qr.panelWidth - 2 * (qr.textX - qr.panelX));
  c.fillStyle = SLATE;
  c.font = font(layout.linkSize);
  c.fillText(text.link.replace(/^https?:\/\//, ""), qr.textX, qr.linkY, qr.panelWidth - 2 * (qr.textX - qr.panelX));
  // The words.
  let y = layout.text.y;
  c.fillStyle = HIGHLAND;
  c.font = font(layout.brandSize);
  c.fillText(text.brand, layout.text.x, y);
  y += layout.brandSize * 2;
  c.fillStyle = INK;
  c.font = font(layout.nameSize);
  for (const line of wrap(c, text.name, layout.text.width, 3)) {
    c.fillText(line, layout.text.x, y);
    y += Math.round(layout.nameSize * 1.25);
  }
  y += Math.round(layout.lineSize * 0.5);
  c.font = font(layout.lineSize);
  for (const line of text.lines) {
    c.fillText(line, layout.text.x, y, layout.text.width);
    y += Math.round(layout.lineSize * 1.4);
  }
  c.fillStyle = ADEY;
  c.fillRect(layout.text.x, layout.bar.y, layout.text.width, 12);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

export function ShareCards({ text, fileStem, labels }: { text: CardText; fileStem: string; labels: Record<CardFormat, string> & { failed: string } }) {
  const [busy, setBusy] = useState<CardFormat | null>(null);
  const [failed, setFailed] = useState(false);
  const save = async (format: CardFormat) => {
    setBusy(format);
    setFailed(false);
    try {
      const blob = await draw(format, text);
      if (!blob) throw new Error("no picture");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${fileStem}-${format}.png`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-2">
        {(["telegram", "tiktok"] as const).map((format) => (
          <li key={format}>
            <button type="button" onClick={() => save(format)} disabled={busy !== null} data-card={format} className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60">
              {labels[format]}
            </button>
          </li>
        ))}
      </ul>
      {failed ? <p role="alert" className="font-semibold text-clay">{labels.failed}</p> : null}
    </div>
  );
}
