import { describe, expect, it } from "vitest";

import { qrInternals, qrMatrix, qrSvg, QrTooLong } from "./qr";

// S-06/S-10 proof without a QR package (D-107): the encoder's parts against
// values published in the standard (ISO/IEC 18004), then every code read
// back by a separate reader written here from the standard's layout: find
// the mask from the format bits, skip the fixed patterns, read the modules
// in their zigzag order, check each block's error correction by evaluating
// its polynomial (not by the encoder's division) and decode the bytes.

const { formatBits, versionBits, remainder, divisor, multiply } = qrInternals;

// ISO/IEC 18004 Table C.1: the format information of level M, masks 0 to 7.
const LEVEL_M_FORMATS = [
  "101010000010010", "101000100100101", "101111001111100", "101101101001011",
  "100010111111001", "100000011001110", "100111110010111", "100101010100000",
];
// ISO/IEC 18004 Table D.1: the version information of versions 7 to 10.
const VERSION_INFO: Record<number, number> = { 7: 0x07c94, 8: 0x085bc, 9: 0x09a99, 10: 0x0a4d3 };

describe("the QR code's parts match the standard", () => {
  it("format information, level M", () => {
    LEVEL_M_FORMATS.forEach((bits, mask) => expect(formatBits(mask).toString(2).padStart(15, "0")).toBe(bits));
  });
  it("version information, versions 7 to 10", () => {
    for (const [version, bits] of Object.entries(VERSION_INFO)) expect(versionBits(Number(version))).toBe(bits);
  });
  it("Reed-Solomon: the standard's worked example (1-M, HELLO WORLD)", () => {
    const data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
    expect(remainder(data, divisor(10))).toEqual([196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
  });
});

// -- a reader, written from the standard's layout ----------------------------------------

const BLOCKS: Record<number, { ec: number; data: number[] }> = {
  1: { ec: 10, data: [16] }, 2: { ec: 16, data: [28] }, 3: { ec: 26, data: [44] },
  4: { ec: 18, data: [32, 32] }, 5: { ec: 24, data: [43, 43] }, 6: { ec: 16, data: [27, 27, 27, 27] },
  7: { ec: 18, data: [31, 31, 31, 31] }, 8: { ec: 22, data: [38, 38, 39, 39] },
  9: { ec: 22, data: [36, 36, 36, 37, 37] }, 10: { ec: 26, data: [43, 43, 43, 43, 44] },
};
const ALIGN: Record<number, number[]> = {
  1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
  7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
};

function fixedModules(n: number, version: number): boolean[][] {
  const fixed = Array.from({ length: n }, () => new Array<boolean>(n).fill(false));
  const mark = (x0: number, y0: number, w: number, h: number) => {
    for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) if (x >= 0 && y >= 0 && x < n && y < n) fixed[y]![x] = true;
  };
  mark(0, 0, 9, 9); // finder, separator and format bits
  mark(n - 8, 0, 8, 9);
  mark(0, n - 8, 9, 8);
  mark(6, 0, 1, n); // timing
  mark(0, 6, n, 1);
  const centres = ALIGN[version]!;
  const last = centres[centres.length - 1];
  for (const cx of centres) for (const cy of centres) {
    // Every pair of centres, but the three that fall on a finder.
    if ((cx === 6 && cy === 6) || (cx === 6 && cy === last) || (cx === last && cy === 6)) continue;
    mark(cx - 2, cy - 2, 5, 5);
  }
  if (version >= 7) {
    mark(n - 11, 0, 3, 6);
    mark(0, n - 11, 6, 3);
  }
  return fixed;
}

const MASK: ((x: number, y: number) => boolean)[] = [
  (x, y) => (x + y) % 2 === 0, (_x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

function readFormat(m: boolean[][]): { mask: number } {
  const n = m.length;
  const b = (x: number, y: number) => (m[y]![x] ? "1" : "0");
  // The first copy, bit 14 first, around the top-left finder.
  const first = [b(0, 8), b(1, 8), b(2, 8), b(3, 8), b(4, 8), b(5, 8), b(7, 8), b(8, 8), b(8, 7), b(8, 5), b(8, 4), b(8, 3), b(8, 2), b(8, 1), b(8, 0)].join("");
  // The second copy, split between the other two finders.
  const second = [b(8, n - 1), b(8, n - 2), b(8, n - 3), b(8, n - 4), b(8, n - 5), b(8, n - 6), b(8, n - 7), b(n - 8, 8), b(n - 7, 8), b(n - 6, 8), b(n - 5, 8), b(n - 4, 8), b(n - 3, 8), b(n - 2, 8), b(n - 1, 8)].join("");
  expect(second).toBe(first);
  expect(m[n - 8]![8]).toBe(true); // the dark module
  const mask = LEVEL_M_FORMATS.indexOf(first);
  expect(mask).toBeGreaterThanOrEqual(0);
  return { mask };
}

/** α^i in GF(256), and a polynomial (highest power first) evaluated at x. */
function evaluate(coefficients: number[], x: number): number {
  return coefficients.reduce((acc, c) => multiply(acc, x) ^ c, 0);
}

function read(m: boolean[][]): string {
  const n = m.length;
  const version = (n - 17) / 4;
  expect(Number.isInteger(version)).toBe(true);
  const { mask } = readFormat(m);
  const fixed = fixedModules(n, version);
  const bits: number[] = [];
  let upward = true;
  for (let right = n - 1; right > 0; right -= 2) {
    if (right === 6) right--;
    for (let k = 0; k < n; k++) {
      const y = upward ? n - 1 - k : k;
      for (const x of [right, right - 1]) {
        if (fixed[y]![x]) continue;
        bits.push((m[y]![x] !== MASK[mask]!(x, y)) ? 1 : 0);
      }
    }
    upward = !upward;
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(bits.slice(i, i + 8).reduce((a, bit) => (a << 1) | bit, 0));
  const layout = BLOCKS[version]!;
  const blocks = layout.data.map(() => [] as number[]);
  let at = 0;
  const longest = Math.max(...layout.data);
  for (let i = 0; i < longest; i++) layout.data.forEach((length, b) => { if (i < length) blocks[b]!.push(bytes[at++]!); });
  const ec = layout.data.map(() => [] as number[]);
  for (let i = 0; i < layout.ec; i++) layout.data.forEach((_, b) => ec[b]!.push(bytes[at++]!));
  const data: number[] = [];
  blocks.forEach((block, b) => {
    // A block is a code word when its polynomial vanishes at α^0 … α^(ec-1).
    let alpha = 1;
    for (let i = 0; i < layout.ec; i++) {
      expect(evaluate([...block, ...ec[b]!], alpha)).toBe(0);
      alpha = multiply(alpha, 2);
    }
    data.push(...block);
  });
  const stream = data.flatMap((byte) => [7, 6, 5, 4, 3, 2, 1, 0].map((i) => (byte >>> i) & 1));
  const take = (count: number) => stream.splice(0, count).reduce((a, bit) => (a << 1) | bit, 0);
  expect(take(4)).toBe(0b0100); // byte mode
  const length = take(version <= 9 ? 8 : 16);
  return new TextDecoder().decode(new Uint8Array(Array.from({ length }, () => take(8))));
}

describe("every code reads back to its link", () => {
  const links = [
    "https://markx.example/am/s/alpha",
    "https://markx.example/en/p/samsung-galaxy-a16",
    "https://markx.et/am/s/abebe-mobile-and-electronics-bole-medhanialem",
    `https://markx.example/am/p/${"a".repeat(85)}`, // version 7: version information
    `https://markx.example/am/p/${"a".repeat(110)}`, // version 8: two kinds of block
    `https://markx.example/am/p/${"a".repeat(150)}`, // version 9
    `https://markx.example/${"x".repeat(185)}`, // version 10: a 16-bit length
    "https://markx.example/am/s/ሳምሰንግ", // not only ASCII: UTF-8 bytes
  ];
  for (const link of links) {
    it(`${link.length} characters`, () => {
      expect(read(qrMatrix(link))).toBe(link);
    });
  }

  it("picks the smallest version that fits, and the links above cover versions 3 to 10", () => {
    const version = (link: string) => (qrMatrix(link).length - 17) / 4;
    expect(version("https://markx.example/am/s/alpha")).toBe(3);
    expect(links.map(version)).toEqual([3, 4, 5, 7, 8, 9, 10, 3]);
  });

  it("refuses what is too long, rather than drawing something wrong", () => {
    expect(() => qrMatrix("x".repeat(300))).toThrow(QrTooLong);
  });
});

describe("qrSvg", () => {
  it("draws exactly the matrix's dark modules, four modules in from the edge", () => {
    const link = "https://markx.example/en/p/samsung-galaxy-a16";
    const matrix = qrMatrix(link);
    const svg = qrSvg(link, { title: "x" });
    const drawn = matrix.map((row) => row.map(() => false));
    for (const [, x, y, width] of svg.matchAll(/M(\d+) (\d+)h(\d+)v1h-\3z/g)) {
      for (let i = 0; i < Number(width); i++) drawn[Number(y) - 4]![Number(x) - 4 + i] = true;
    }
    expect(drawn).toEqual(matrix);
  });

  it("is plain SVG with a quiet zone and an escaped title", () => {
    const svg = qrSvg("https://markx.example/am/s/alpha", { title: "Alpha <shop> & co" });
    expect(svg.startsWith("<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 37 37\"")).toBe(true);
    expect(svg).toContain("<title>Alpha &#60;shop&#62; &#38; co</title>");
    expect(svg).not.toContain("<script");
  });
});
