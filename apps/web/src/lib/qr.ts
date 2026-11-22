// A QR code for a shop's or a product's link (S-10, blueprint D.4, B; D-107).
//
// Written here rather than taken from a package: it is small, it runs on the
// server only (the page gets plain SVG, no script), and every step is the
// published standard (ISO/IEC 18004): byte mode, error correction level M
// (about 15% of the code can be damaged or covered and it still reads),
// versions 1 to 10 (up to 213 bytes, far more than a MarkX link), the mask
// with the lowest penalty. `qr.test.ts` reads every code back with an
// independent decoder.

type Block = { count: number; data: number };
type Version = { ec: number; blocks: Block[]; align: number[] };

// Level M, versions 1 to 10: error-correction codewords per block, the
// blocks (count × data codewords) and the alignment pattern centres.
const VERSIONS: Version[] = [
  { ec: 10, blocks: [{ count: 1, data: 16 }], align: [] },
  { ec: 16, blocks: [{ count: 1, data: 28 }], align: [6, 18] },
  { ec: 26, blocks: [{ count: 1, data: 44 }], align: [6, 22] },
  { ec: 18, blocks: [{ count: 2, data: 32 }], align: [6, 26] },
  { ec: 24, blocks: [{ count: 2, data: 43 }], align: [6, 30] },
  { ec: 16, blocks: [{ count: 4, data: 27 }], align: [6, 34] },
  { ec: 18, blocks: [{ count: 4, data: 31 }], align: [6, 22, 38] },
  { ec: 22, blocks: [{ count: 2, data: 38 }, { count: 2, data: 39 }], align: [6, 24, 42] },
  { ec: 22, blocks: [{ count: 3, data: 36 }, { count: 2, data: 37 }], align: [6, 26, 46] },
  { ec: 26, blocks: [{ count: 4, data: 43 }, { count: 1, data: 44 }], align: [6, 28, 50] },
];
const LEVEL_M_BITS = 0b00;

export class QrTooLong extends Error {}

function dataCapacity(version: Version): number {
  return version.blocks.reduce((sum, block) => sum + block.count * block.data, 0);
}

// -- Reed-Solomon over GF(256), polynomial 0x11D --------------------------------------

function multiply(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

function divisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      result[j] = multiply(result[j]!, root);
      if (j + 1 < degree) result[j] = result[j]! ^ result[j + 1]!;
    }
    root = multiply(root, 0x02);
  }
  return result;
}

function remainder(data: number[], by: number[]): number[] {
  const result = new Array<number>(by.length).fill(0);
  for (const byte of data) {
    const factor = byte ^ result.shift()!;
    result.push(0);
    by.forEach((coefficient, i) => {
      result[i] = result[i]! ^ multiply(coefficient, factor);
    });
  }
  return result;
}

// -- the codewords -------------------------------------------------------------------

function codewords(bytes: Uint8Array, versionNumber: number, version: Version): number[] {
  const bits: number[] = [];
  const put = (value: number, length: number) => {
    for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  put(0b0100, 4); // byte mode
  put(bytes.length, versionNumber <= 9 ? 8 : 16);
  for (const byte of bytes) put(byte, 8);
  const capacityBits = dataCapacity(version) * 8;
  put(0, Math.min(4, capacityBits - bits.length)); // terminator
  while (bits.length % 8) bits.push(0);
  const data: number[] = [];
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((byte, bit) => (byte << 1) | bit, 0));
  for (let pad = 0xec; data.length < dataCapacity(version); pad ^= 0xec ^ 0x11) data.push(pad);

  const gen = divisor(version.ec);
  const blocks: { data: number[]; ec: number[] }[] = [];
  let at = 0;
  for (const group of version.blocks) {
    for (let i = 0; i < group.count; i++) {
      const chunk = data.slice(at, at + group.data);
      at += group.data;
      blocks.push({ data: chunk, ec: remainder(chunk, gen) });
    }
  }
  const out: number[] = [];
  const longest = Math.max(...blocks.map((block) => block.data.length));
  for (let i = 0; i < longest; i++) for (const block of blocks) if (i < block.data.length) out.push(block.data[i]!);
  for (let i = 0; i < version.ec; i++) for (const block of blocks) out.push(block.ec[i]!);
  return out;
}

// -- the matrix ------------------------------------------------------------------------

type Grid = { size: number; dark: boolean[][]; fixed: boolean[][] };

function grid(size: number): Grid {
  const rows = () => Array.from({ length: size }, () => new Array<boolean>(size).fill(false));
  return { size, dark: rows(), fixed: rows() };
}

function set(g: Grid, x: number, y: number, dark: boolean): void {
  g.dark[y]![x] = dark;
  g.fixed[y]![x] = true;
}

function finder(g: Grid, cx: number, cy: number): void {
  for (let dy = -4; dy <= 4; dy++) {
    for (let dx = -4; dx <= 4; dx++) {
      const x = cx + dx;
      const y = cy + dy;
      if (x < 0 || y < 0 || x >= g.size || y >= g.size) continue;
      const ring = Math.max(Math.abs(dx), Math.abs(dy));
      set(g, x, y, ring !== 2 && ring !== 4);
    }
  }
}

function alignment(g: Grid, cx: number, cy: number): void {
  for (let dy = -2; dy <= 2; dy++) {
    for (let dx = -2; dx <= 2; dx++) set(g, cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
  }
}

function formatBits(mask: number): number {
  const data = (LEVEL_M_BITS << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

function drawFormat(g: Grid, mask: number): void {
  const bits = formatBits(mask);
  const bit = (i: number) => ((bits >>> i) & 1) === 1;
  const n = g.size;
  for (let i = 0; i <= 5; i++) set(g, 8, i, bit(i));
  set(g, 8, 7, bit(6));
  set(g, 8, 8, bit(7));
  set(g, 7, 8, bit(8));
  for (let i = 9; i < 15; i++) set(g, 14 - i, 8, bit(i));
  for (let i = 0; i < 8; i++) set(g, n - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i++) set(g, 8, n - 15 + i, bit(i));
  set(g, 8, n - 8, true); // the dark module
}

function drawVersion(g: Grid, versionNumber: number): void {
  if (versionNumber < 7) return;
  const bits = versionBits(versionNumber);
  for (let i = 0; i < 18; i++) {
    const dark = ((bits >>> i) & 1) === 1;
    const a = g.size - 11 + (i % 3);
    const b = Math.floor(i / 3);
    set(g, a, b, dark);
    set(g, b, a, dark);
  }
}

function functionPatterns(versionNumber: number, version: Version): Grid {
  const size = versionNumber * 4 + 17;
  const g = grid(size);
  for (let i = 0; i < size; i++) {
    set(g, 6, i, i % 2 === 0);
    set(g, i, 6, i % 2 === 0);
  }
  finder(g, 3, 3);
  finder(g, size - 4, 3);
  finder(g, 3, size - 4);
  const centres = version.align;
  centres.forEach((cx, i) => {
    centres.forEach((cy, j) => {
      const corner = (i === 0 && j === 0) || (i === 0 && j === centres.length - 1) || (i === centres.length - 1 && j === 0);
      if (!corner) alignment(g, cx, cy);
    });
  });
  drawFormat(g, 0); // reserved now, drawn for real with the chosen mask
  drawVersion(g, versionNumber);
  return g;
}

function placeData(g: Grid, data: number[]): void {
  let i = 0;
  for (let right = g.size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < g.size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? g.size - 1 - vert : vert;
        if (!g.fixed[y]![x] && i < data.length * 8) {
          g.dark[y]![x] = ((data[i >>> 3]! >>> (7 - (i & 7))) & 1) === 1;
          i++;
        }
      }
    }
  }
}

const MASKS: ((x: number, y: number) => boolean)[] = [
  (x, y) => (x + y) % 2 === 0,
  (_x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

function applyMask(g: Grid, mask: number): void {
  const test = MASKS[mask]!;
  for (let y = 0; y < g.size; y++) {
    for (let x = 0; x < g.size; x++) {
      if (!g.fixed[y]![x] && test(x, y)) g.dark[y]![x] = !g.dark[y]![x];
    }
  }
}

/** The standard's penalty score: lower reads more reliably. */
export function penalty(dark: boolean[][]): number {
  const n = dark.length;
  let score = 0;
  const lines: boolean[][] = [];
  for (let y = 0; y < n; y++) lines.push(dark[y]!);
  for (let x = 0; x < n; x++) lines.push(dark.map((row) => row[x]!));
  const finderLike = [
    [true, false, true, true, true, false, true, false, false, false, false],
    [false, false, false, false, true, false, true, true, true, false, true],
  ];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= n; i++) {
      if (i < n && line[i] === line[i - 1]) {
        run++;
      } else {
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
    }
    for (let i = 0; i + 11 <= n; i++) {
      for (const pattern of finderLike) if (pattern.every((value, k) => line[i + k] === value)) score += 40;
    }
  }
  for (let y = 0; y + 1 < n; y++) {
    for (let x = 0; x + 1 < n; x++) {
      const c = dark[y]![x];
      if (dark[y]![x + 1] === c && dark[y + 1]![x] === c && dark[y + 1]![x + 1] === c) score += 3;
    }
  }
  const total = n * n;
  const darkCount = dark.reduce((sum, row) => sum + row.filter(Boolean).length, 0);
  const k = Math.ceil(Math.abs(darkCount * 20 - total * 10) / total) - 1;
  return score + Math.max(0, k) * 10;
}

/** The QR code of `text` as rows of modules (true is dark), without the
 * quiet zone. Throws `QrTooLong` past version 10. */
export function qrMatrix(text: string): boolean[][] {
  const bytes = new TextEncoder().encode(text);
  const index = VERSIONS.findIndex((version, i) => 4 + (i + 1 <= 9 ? 8 : 16) + bytes.length * 8 <= dataCapacity(version) * 8);
  if (index < 0) throw new QrTooLong(`too long for a QR code: ${bytes.length} bytes`);
  const versionNumber = index + 1;
  const version = VERSIONS[index]!;
  const data = codewords(bytes, versionNumber, version);
  let best: { score: number; dark: boolean[][] } | null = null;
  for (let mask = 0; mask < 8; mask++) {
    const g = functionPatterns(versionNumber, version);
    placeData(g, data);
    applyMask(g, mask);
    drawFormat(g, mask);
    const score = penalty(g.dark);
    if (!best || score < best.score) best = { score, dark: g.dark };
  }
  return best!.dark;
}

/** The code as one SVG path (one unit per module, with a four-module quiet
 * zone), dark on white, so it prints and scans anywhere. */
export function qrSvg(text: string, { title }: { title: string }): string {
  const matrix = qrMatrix(text);
  const quiet = 4;
  const size = matrix.length + quiet * 2;
  // Each run of dark modules in a row is one rectangle: a quarter of the size
  // of one square per module.
  let path = "";
  matrix.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (!row[x]) continue;
      let end = x;
      while (end + 1 < row.length && row[end + 1]) end++;
      path += `M${x + quiet} ${y + quiet}h${end - x + 1}v1h-${end - x + 1}z`;
      x = end;
    }
  });
  const safeTitle = title.replace(/[<>&"']/g, (c) => `&#${c.charCodeAt(0)};`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges" role="img"><title>${safeTitle}</title><rect width="${size}" height="${size}" fill="#ffffff"/><path d="${path}" fill="#000000"/></svg>`;
}

/** The building blocks, for the tests that check them against the standard. */
export const qrInternals = { formatBits, divisor, remainder, multiply, versionBits, VERSIONS };

function versionBits(versionNumber: number): number {
  let rem = versionNumber;
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
  return (versionNumber << 12) | rem;
}
