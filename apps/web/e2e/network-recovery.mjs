// A purchase in a real browser with the network cut halfway (D-100): every
// part of it must say what happened, offer "try again" and recover, and no
// button may stay stuck. Against a running API and web app filled by
// scripts/seed_demo.py (DEMO data), like the other journeys.
//
//   MARKX_E2E_STOP_API="..." MARKX_E2E_START_API="..." node e2e/network-recovery.mjs [screenshot-folder]
//
// The two commands stop and start the API itself (CI: `docker compose stop
// api` and `docker compose up -d --wait api`), for the last part: the server
// cannot reach the API, so a page cannot be built and the error page shows.
// Both are required; without them the journey fails rather than skip.
//
// 1. Add to cart with the browser offline: a message and "try again", the
//    button free; back online, "try again" adds it.
// 2. A proxy's 502 page on the cart: "MarkX could not answer", try again.
// 3. Checkout, review, then "Place order" offline: nothing is sent, the
//    order button is free, "try again" is offered.
// 4. Online, but the answer to "Place order" is lost after the server took
//    the order (the connection resets on the way back): the page says so.
// 5. "Try again": the same order (same idempotency key) is shown; exactly
//    ONE new order exists.
// 6. The API itself stops: the next page is the error page, in English and
//    in Amharic, with no technical details; the API starts again and "try
//    again" brings the page back.
// The shop then declines the order, so its stock is free for the next run
// (a buyer's cancellation would count towards the cancel cool-down, D-099).
// Every page on the way, the notices and the error pages included, and the
// main public pages in both languages pass the automatic accessibility check
// (axe, WCAG 2.1 A and AA; e2e/a11y.mjs).
import { execSync } from 'node:child_process';
import { createRequire } from 'node:module';

import { checkAccessibility } from './a11y.mjs';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const BUYER = '0911000950';
const SHOPS = { 'Merkato Mobile': '0911000901', 'Bole Phone House': '0911000902', 'Piassa Electronics': '0911000903' };
const SHOTS = process.argv[2] || '.';
const STOP_API = process.env.MARKX_E2E_STOP_API;
const START_API = process.env.MARKX_E2E_START_API;

function expect(ok, what) {
  if (!ok) throw new Error(what);
}

function caller(page) {
  return (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const r = await fetch(p, { method: m, cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, [method, path, body]);
}

async function signIn(page, phone, next, landing = (url) => url.pathname === next) {
  await page.goto(`${BASE}/en/sign-in?next=${next}`);
  await page.fill('input[type=tel]', phone);
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('We sent a code').waitFor();
  const inbox = await page.evaluate(async (p) => (await fetch(`/api/v1/dev/sms-inbox?phone=${p}`)).json(), phone);
  await page.fill('input[name=code]', inbox.at(-1).text.match(/\b\d{6}\b/)[0]);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL(landing);
}

/** The alert the page shows now, and that the button named is not stuck. */
async function saysAndIsFree(page, words, button) {
  const alert = page.getByRole('alert').filter({ hasText: words });
  await alert.first().waitFor({ timeout: 15000 });
  const retry = page.getByRole('button', { name: 'Try again' });
  await retry.first().waitFor();
  expect(await retry.first().isEnabled(), '"Try again" is disabled');
  if (button) expect(await page.getByRole('button', { name: button }).first().isEnabled(), `"${button}" stays disabled`);
}

(async () => {
  expect(STOP_API && START_API, 'MARKX_E2E_STOP_API and MARKX_E2E_START_API are required (see the header)');
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const buyer = await context.newPage();
  const errors = [];
  // While the API is stopped on purpose (step 6), React reports the failed
  // server render as error #441 (its message is withheld in production);
  // those are expected then and only then, and at least one must appear.
  let apiDown = false;
  let serverRenderErrors = 0;
  // A cut connection makes the browser log failed requests; those are the test.
  buyer.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (apiDown && /Minified React error #441|500 \(Internal Server Error\)/.test(m.text())) return void (serverRenderErrors += 1);
    if (!/_rsc=|404 \(Not Found\)|Failed to fetch|ERR_INTERNET_DISCONNECTED|ERR_CONNECTION_RESET|502 \(Bad Gateway\)|net::ERR/.test(m.text())) errors.push(m.text().slice(0, 160));
  });

  // The main public pages, before signing in.
  for (const path of ['/en', '/am', '/en/search?q=phone', '/am/p/tecno-spark-20?zone=bole', '/en/s/merkato-mobile', '/en/sign-in', '/am/sign-in', '/en/admin/sign-in']) {
    await buyer.goto(`${BASE}${path}`);
    await checkAccessibility(buyer, path);
  }

  await signIn(buyer, BUYER, '/en/cart');
  const call = caller(buyer);
  console.log('0 signed in as the demo buyer');

  // 1. Add to cart with no network.
  await buyer.goto(`${BASE}/en/p/tecno-spark-20?zone=bole`);
  await context.setOffline(true);
  await buyer.getByRole('button', { name: 'Add to cart' }).first().click();
  await saysAndIsFree(buyer, 'No connection. Check your internet, then try again.', 'Add to cart');
  await buyer.screenshot({ path: `${SHOTS}/offline-add-to-cart.png`, fullPage: true });
  await checkAccessibility(buyer, 'product page with the no-connection notice');
  await context.setOffline(false);
  await buyer.getByRole('button', { name: 'Try again' }).first().click();
  await buyer.getByText('Added to your cart').waitFor();
  console.log('1 add to cart offline: message, "Try again", button free; back online, "Try again" added it');

  // 2. Something between the browser and the API answers instead of it.
  await buyer.route('**/api/v1/cart?*', (route) => route.fulfill({ status: 502, contentType: 'text/html', body: '<html><body><h1>502 Bad Gateway</h1>nginx</body></html>' }));
  await buyer.goto(`${BASE}/en/cart`);
  await saysAndIsFree(buyer, 'MarkX could not answer just now. Please try again in a moment.');
  await checkAccessibility(buyer, 'cart with the server notice');
  expect(!(await buyer.getByText('nginx').count()), 'the proxy page leaks into the page');
  await buyer.unroute('**/api/v1/cart?*');
  await buyer.getByRole('button', { name: 'Try again' }).click();
  await buyer.getByRole('link', { name: 'Continue to checkout' }).waitFor();
  await checkAccessibility(buyer, 'cart');
  console.log('2 a 502 page on the cart: "MarkX could not answer", try again shows the cart');

  // 3. Checkout; the network drops just before "Place order".
  const before = (await call('GET', '/api/v1/me/orders')).body.length;
  await buyer.getByRole('link', { name: 'Continue to checkout' }).click();
  await buyer.waitForURL(/\/en\/checkout$/);
  await buyer.getByRole('button', { name: 'Review' }).click();
  await buyer.getByText('Grand total').waitFor();
  await checkAccessibility(buyer, 'checkout review');
  await context.setOffline(true);
  await buyer.getByRole('button', { name: 'Place order' }).click();
  await saysAndIsFree(buyer, 'No connection. Check your internet, then try again.', 'Place order');
  await buyer.screenshot({ path: `${SHOTS}/offline-place-order.png`, fullPage: true });
  await checkAccessibility(buyer, 'checkout with the no-connection notice');
  await context.setOffline(false);
  expect((await call('GET', '/api/v1/me/orders')).body.length === before, 'an order was placed while offline');
  console.log('3 "Place order" offline: message, "Try again", button free; no order placed');

  // 4. Online, but the answer is lost after the server took the order.
  let reached = 0;
  await buyer.route('**/api/v1/checkout?*', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    reached += 1;
    await route.fetch(); // the server receives it and places the order...
    await route.abort('connectionreset'); // ...and the answer never arrives
  });
  await buyer.getByRole('button', { name: 'Try again' }).click();
  await saysAndIsFree(buyer, 'No connection. Check your internet, then try again.', 'Place order');
  await buyer.unroute('**/api/v1/checkout?*');
  expect(reached === 1, `the server was reached ${reached} times`);
  expect((await call('GET', '/api/v1/me/orders')).body.length === before + 1, 'the server did not take the order');
  console.log('4 the answer lost on the way back: the page says so; the server had the order');

  // 5. Try again: the same order, not a second one.
  await buyer.getByRole('button', { name: 'Try again' }).click();
  await buyer.waitForURL(/\/en\/orders\/[0-9a-f-]{36}$/);
  const orders = (await call('GET', '/api/v1/me/orders')).body;
  expect(orders.length === before + 1, `${orders.length - before} new orders instead of one`);
  const orderId = new URL(buyer.url()).pathname.split('/').at(-1);
  expect(orders.some((o) => o.id === orderId), 'the page shows another order');
  const store = await buyer.locator('section h2').first().innerText();
  await checkAccessibility(buyer, 'order page');
  console.log('5 "Try again" opened the order page; exactly one new order, from', store);

  // 6. The API stops: the error page, in both languages, without details.
  execSync(STOP_API, { stdio: 'inherit' });
  apiDown = true;
  try {
    for (const [lang, title, lead, home] of [
      ['en', 'This page could not be shown', 'Something went wrong on our side or with the connection. Please try again.', 'Go to the home page'],
      ['am', 'ይህን ገጽ ማሳየት አልተቻለም', 'በእኛ በኩል ወይም በግንኙነቱ ላይ ችግር ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።', 'ወደ መነሻ ገጽ ይሂዱ'],
    ]) {
      await buyer.goto(`${BASE}/${lang}/orders/${orderId}`);
      await buyer.getByRole('heading', { name: title }).waitFor();
      await buyer.getByText(lead).waitFor();
      await buyer.getByRole('link', { name: home }).waitFor();
      expect((await buyer.locator('html').getAttribute('lang')) === lang, `the page is not marked ${lang}`);
      const text = await buyer.locator('body').innerText();
      for (const leak of ['ECONNREFUSED', 'fetch failed', 'Error:', 'digest', ' at /', '127.0.0.1', 'Internal Server Error']) {
        expect(!text.includes(leak), `the error page shows "${leak}"`);
      }
      await buyer.screenshot({ path: `${SHOTS}/error-page-${lang}.png`, fullPage: true });
      await checkAccessibility(buyer, `error page (${lang})`);
    }
  } finally {
    execSync(START_API, { stdio: 'inherit' });
  }
  expect(serverRenderErrors > 0, 'the stopped API caused no failed server render');
  await buyer.getByRole('button', { name: 'እንደገና ይሞክሩ' }).click();
  await buyer.getByRole('heading', { name: 'ይህን ገጽ ማሳየት አልተቻለም' }).waitFor({ state: 'detached', timeout: 20000 });
  await buyer.locator('section h2').first().waitFor();
  apiDown = false;
  console.log('6 API stopped: the error page in English and Amharic, no details; API back, "try again" shows the order');

  // The shop declines the order, so its stock is free again.
  const shop = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  await signIn(shop, SHOPS[store], '/en/seller', /\/en\/seller\/[0-9a-f-]{36}\//);
  const sellerId = new URL(shop.url()).pathname.split('/')[3];
  const part = orders.find((o) => o.id === orderId).seller_orders[0];
  const declined = await caller(shop)('POST', `/api/v1/seller/${sellerId}/orders/${part.id}/decline`, { reason: 'Demo: network test order' });
  expect(declined.status === 200, `decline: ${declined.status} ${JSON.stringify(declined.body)}`);
  console.log('  the shop declined the test order');

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
