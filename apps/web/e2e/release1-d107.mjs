// D-107's five Release 1 features in a real browser, against a running API
// (port 8000) and web app (port 3000) filled by scripts/seed_demo.py (DEMO
// data). It leaves the order it places accepted: it cancels nothing, since
// cancelling starts the demo buyer's cooldown (D-099). Run it after the other
// journeys that place orders, as the journeys workflow does.
//
//   node e2e/release1-d107.mjs [screenshot-folder]
//
// C-03  search by the total to the door and by delivery speed;
// C-12  lite mode: the switch, remembered, and on by itself for Save-Data;
// S-10  a shop's share page: the QR code and both cards, saved as PNG;
// S-06  a gate photo is made smaller on the phone before it is sent;
// C-08  the gate photo: the buyer's own, then the delivering shop's.
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { deflateSync } from 'node:zlib';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SHOTS = process.argv[2] || '.';
mkdirSync(SHOTS, { recursive: true });

async function code(page, phone) {
  const inbox = await page.evaluate(async (p) => (await fetch(`/api/v1/dev/sms-inbox?phone=${p}`)).json(), phone);
  return inbox[inbox.length - 1].text.match(/\b\d{6}\b/)[0];
}

async function signIn(page, phone, next) {
  await page.goto(`${BASE}/en/sign-in?next=${next}`);
  await page.fill('input[type=tel]', phone);
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('We sent a code').waitFor();
  await page.fill('input[name=code]', await code(page, phone));
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}

function pngSize(buffer) {
  if (buffer.subarray(1, 4).toString() !== 'PNG') throw new Error('not a PNG');
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

// A big, noisy picture like a camera's (3000 × 2000), written as an
// uncompressed PNG so it is several megabytes: the phone must shrink it.
function bigPhoto() {
  const width = 3000;
  const height = 2000;
  const raw = Buffer.alloc((width * 3 + 1) * height);
  let seed = 7;
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    for (let i = 1; i <= width * 3; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      raw[y * (width * 3 + 1) + i] = (seed >> 16) & 0xff;
    }
  }
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b) => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]); const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body)); return Buffer.concat([len, body, sum]); };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(raw, { level: 0 })), chunk('IEND', Buffer.alloc(0))]);
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const watch = (page, who) => page.on('console', (m) => { if (m.type() === 'error' && !/_rsc=|404 \(Not Found\)/.test(m.text())) errors.push(`${who}: ${m.text().slice(0, 120)}`); });
  const visitor = await (await browser.newContext({ viewport: { width: 360, height: 800 }, acceptDownloads: true })).newPage();
  watch(visitor, 'visitor');

  // C-03: sorted by the total to the door in Bole, each card saying it.
  await visitor.goto(`${BASE}/en/search?zone=bole&sort=total`);
  const totals = (await visitor.locator('main li').allInnerTexts())
    .map((text) => text.match(/ETB ([\d,]+) to your door/)?.[1])
    .filter(Boolean)
    .map((n) => Number(n.replace(/,/g, '')));
  if (totals.length < 2) throw new Error('no totals to the door on the cards');
  if (totals.some((n, i) => i && n < totals[i - 1])) throw new Error(`not sorted by the total: ${totals}`);
  console.log('C-03 totals to the door, lowest first:', totals.join(', '));
  await visitor.goto(`${BASE}/en/search?sort=total&speed=24`);
  await visitor.getByText('Choose your area to sort by the total').waitFor();
  console.log('     without an area: the page asks for one');
  await visitor.goto(`${BASE}/en/search?zone=bole&speed=24`);
  if (!(await visitor.getByText('Arrives within 24 hours').count())) throw new Error('no delivery time on the cards');
  console.log('     within 24 hours:', await visitor.locator('h1').innerText());

  // C-12: the switch, remembered, and back on the same page.
  await visitor.goto(`${BASE}/en/p/tecno-spark-20?zone=bole`);
  await visitor.getByRole('link', { name: 'Lite mode (smaller pictures)' }).click();
  await visitor.waitForURL((url) => url.pathname === '/en/p/tecno-spark-20');
  await visitor.getByText('Lite mode is on.').waitFor();
  const cookie = (await visitor.context().cookies()).find((c) => c.name === 'markx_lite');
  if (cookie?.value !== '1') throw new Error('lite mode was not remembered');
  await visitor.goto(`${BASE}/en/search?q=tecno`);
  if (await visitor.locator('main li img').count()) throw new Error('lite mode still shows card pictures');
  await visitor.getByRole('link', { name: 'Turn lite mode off' }).click();
  await visitor.getByRole('link', { name: 'Lite mode (smaller pictures)' }).waitFor();
  const saver = await (await browser.newContext({ viewport: { width: 360, height: 800 }, extraHTTPHeaders: { 'Save-Data': 'on' } })).newPage();
  await saver.goto(`${BASE}/am`);
  await saver.getByText('ቀላል ሁነታ በርቷል።').waitFor();
  console.log('C-12 lite mode: switched on and off, remembered; on by itself with Save-Data');

  // S-10: a shop's share page in Amharic, its QR code and both cards.
  await visitor.goto(`${BASE}/am/s/merkato-mobile`);
  await visitor.getByRole('link', { name: 'አጋራ' }).click();
  await visitor.waitForURL(/\/am\/s\/merkato-mobile\/share$/);
  const qr = visitor.locator('main img[alt*="QR"]');
  await qr.waitFor();
  await visitor.waitForFunction(() => document.querySelector('main img[alt*="QR"]')?.naturalWidth > 0);
  const svg = await visitor.evaluate(async () => (await fetch('/am/s/merkato-mobile/qr?download=1')).text());
  if (!svg.startsWith('<svg')) throw new Error('the QR file is not an SVG');
  for (const [format, size] of [['telegram', { width: 1200, height: 630 }], ['tiktok', { width: 1080, height: 1920 }]]) {
    const [download] = await Promise.all([visitor.waitForEvent('download'), visitor.locator(`button[data-card=${format}]`).click()]);
    const file = join(SHOTS, `share-card-${format}.png`);
    await download.saveAs(file);
    const got = pngSize(readFileSync(file));
    if (got.width !== size.width || got.height !== size.height) throw new Error(`${format} card is ${got.width}×${got.height}`);
    console.log(`S-10 ${format} card saved: ${got.width} × ${got.height} PNG, ${download.suggestedFilename()}`);
  }
  await visitor.screenshot({ path: join(SHOTS, 'share-page.png'), fullPage: true });

  // S-06 and C-08: the buyer adds a gate photo; the phone sends a small one.
  const buyer = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  watch(buyer, 'buyer');
  await signIn(buyer, '0911000950', '/en/account');
  await buyer.waitForURL((url) => url.pathname === '/en/account');
  const photo = bigPhoto();
  const photoPath = join(SHOTS, 'camera-photo.png');
  writeFileSync(photoPath, photo);
  // What the upload really hands to fetch: the file after the phone's shrinking.
  await buyer.addInitScript(() => {
    const send = window.fetch;
    window.fetch = (input, init) => {
      const file = init?.body instanceof FormData ? init.body.get('file') : null;
      if (file instanceof File) window.__sentFile = { size: file.size, type: file.type, name: file.name };
      return send(input, init);
    };
  });
  await buyer.reload();
  const address = buyer.locator('main li', { hasText: 'Gate photo' }).first();
  await address.locator('input[type=file]').setInputFiles(photoPath);
  await address.getByRole('button', { name: 'Save the gate photo' }).click();
  await buyer.getByText('Gate photo saved.').waitFor();
  const file = await buyer.evaluate(() => window.__sentFile);
  const sent = file?.size ?? 0;
  if (!sent || sent >= photo.length / 4 || file.type !== 'image/webp') throw new Error(`the photo was not made smaller: ${photo.length} bytes picked, ${JSON.stringify(file)} sent`);
  console.log(`S-06 picked ${(photo.length / 1e6).toFixed(1)} MB (PNG, 3000 × 2000), sent ${(sent / 1e3).toFixed(0)} KB (${file.type}, ${file.name})`);
  const own = buyer.locator('main img[alt^="The gate at"]').first();
  await own.waitFor();
  await buyer.waitForFunction(() => document.querySelector('main img[alt^="The gate at"]')?.naturalWidth > 0);
  console.log('C-08 the buyer sees their own gate photo, from a private link');

  // The buyer orders with delivery to that address; the shop accepts and
  // sees the gate (Merkato Mobile delivers to Bole by its own rider).
  await buyer.goto(`${BASE}/en/p/tecno-spark-20?zone=bole`);
  await buyer.getByRole('button', { name: 'Add to cart' }).first().click();
  await buyer.getByText('Added to your cart').waitFor();
  await buyer.goto(`${BASE}/en/checkout`);
  await buyer.getByRole('button', { name: 'Review' }).click();
  await buyer.getByText('Grand total').waitFor();
  await buyer.getByRole('button', { name: 'Place order' }).click();
  await buyer.waitForURL(/\/en\/orders\/[0-9a-f-]{36}$/);
  const store = await buyer.locator('section h2').first().innerText();
  const shopPhone = { 'Merkato Mobile': '0911000901', 'Bole Phone House': '0911000902', 'Piassa Electronics': '0911000903' }[store];
  const method = await buyer.locator('main').innerText();
  const shop = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  watch(shop, 'shop');
  await signIn(shop, shopPhone, '/en/seller');
  await shop.waitForURL(/\/en\/seller\/[0-9a-f-]{36}\/orders/);
  await shop.getByRole('link', { name: /Order MX-/ }).first().click();
  if (await shop.getByRole('heading', { name: "The buyer's gate" }).count()) throw new Error('the shop saw the gate before accepting');
  await shop.getByRole('button', { name: 'Accept the order' }).click();
  await shop.getByText('Confirmed by the shop').first().waitFor();
  await shop.reload();
  if (/collect/i.test(method) && !(await shop.getByRole('heading', { name: "The buyer's gate" }).count())) {
    console.log('C-08 collected at the shop: no gate photo shown, as intended');
  } else {
    await shop.getByRole('heading', { name: "The buyer's gate" }).waitFor();
    await shop.waitForFunction(() => document.querySelector('img[alt="Photo of the buyer\'s gate"]')?.naturalWidth > 0);
    console.log(`C-08 ${store} accepted and sees the buyer's gate photo`);
    await shop.screenshot({ path: join(SHOTS, 'shop-gate-photo.png'), fullPage: true });
  }
  await browser.close();
  console.log('console errors:', errors.length ? errors : 'none');
  if (errors.length) process.exit(1);
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
