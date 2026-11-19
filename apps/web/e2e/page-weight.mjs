// The page-weight check (blueprint D.26, F.1, P1; D-084), against a running
// production build (`npm run build && npm run start`) and API with the demo
// data of scripts/seed_demo.py.
//
//   node e2e/page-weight.mjs
//
// Loads each page in Chromium as a first-time visitor on a phone and counts
// the bytes really transferred (compressed, headers included), before
// images: the document, scripts, styles, fonts and data requests. Pictures
// have their own budgets (D.26), enforced when they are made (D-062).
// Exits 1 when a page is over its ceiling, so CI fails.
//
// The ceilings: the blueprint's target is 150 KB before images on product
// and search pages (D.26), and F.1 sets the hard ceiling at the measured
// framework baseline plus at most 30 KB of page-specific script. The
// baseline was measured in D-055 and again in D-084; see docs/DECISIONS.md.
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const KB = 1024;

// [name, path, ceiling in KB before images, ceiling in KB of script]
// Measured on 18 November 2026 (D-084): script 142 to 147 KB on every page;
// before images 157 KB (home) to 195 KB (product, which prefetches the pages
// it links to). The 150 KB target of D.26 is NOT met; these ceilings stop it
// getting worse while the gap is worked on: script at the framework baseline
// (about 140 KB, D-055) plus F.1's 30 KB, and 210 KB before images.
const SCRIPT_CEILING = 170;
const PAGE_CEILING = 210;
const PAGES = [
  ['home', '/am'],
  ['search', '/am/search?q=tecno'],
  ['product', '/am/p/tecno-spark-20'],
  ['product (English)', '/en/p/tecno-spark-20'],
  ['sign-in', '/en/sign-in'],
].map(([name, path]) => [name, path, PAGE_CEILING, SCRIPT_CEILING]);

async function measure(browser, path) {
  const context = await browser.newContext({ viewport: { width: 360, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  const types = new Map();
  const totals = { all: 0, script: 0, images: 0, requests: 0 };
  cdp.on('Network.responseReceived', (event) => types.set(event.requestId, event.type));
  cdp.on('Network.loadingFinished', (event) => {
    const type = types.get(event.requestId) ?? 'Other';
    if (type === 'Image') {
      totals.images += event.encodedDataLength;
      return;
    }
    totals.all += event.encodedDataLength;
    totals.requests += 1;
    if (type === 'Script') totals.script += event.encodedDataLength;
  });
  const response = await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
  if (!response || !response.ok()) throw new Error(`${path} answered ${response?.status()}`);
  await context.close();
  return totals;
}

(async () => {
  const browser = await chromium.launch();
  const over = [];
  console.log('page'.padEnd(20), 'before images'.padStart(14), 'script'.padStart(10), 'requests'.padStart(9), 'images'.padStart(9));
  for (const [name, path, ceiling, scriptCeiling] of PAGES) {
    const t = await measure(browser, path);
    const all = t.all / KB;
    const script = t.script / KB;
    console.log(
      name.padEnd(20),
      `${all.toFixed(1)} KB`.padStart(14),
      `${script.toFixed(1)} KB`.padStart(10),
      String(t.requests).padStart(9),
      `${(t.images / KB).toFixed(1)} KB`.padStart(9),
    );
    if (all > ceiling) over.push(`${name}: ${all.toFixed(1)} KB before images, ceiling ${ceiling} KB`);
    if (script > scriptCeiling) over.push(`${name}: ${script.toFixed(1)} KB of script, ceiling ${scriptCeiling} KB`);
  }
  await browser.close();
  if (over.length) {
    console.error('\nOver the page-weight budget:\n  ' + over.join('\n  '));
    process.exit(1);
  }
  console.log('\nEvery page is within its budget.');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
