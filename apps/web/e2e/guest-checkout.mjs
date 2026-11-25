// Guest checkout (C-07, D-108) in a real browser, against a running API
// (port 8000) and web app (port 3000) filled by scripts/seed_demo.py (DEMO
// data).
//
//   node e2e/guest-checkout.mjs [screenshot-folder]
//
// A visitor without Telegram orders as a guest, on a 360 px phone: from the
// sign-in page's "Order as a guest", with a name, an address and a phone
// number (a new one each run). Delivered to the door, paid at the door; the
// guest gets the tracking link and nothing more, and the page shows nothing
// of the demo buyer's account. The shop accepts, packs and sends the parcel;
// the guest's link then shows the handover code, which the shop enters at
// the door. Then the same pages in Amharic. That a guest using an existing
// account's number sees nothing of it is proven by the API's tests
// (tests/api/test_d108_guest_checkout.py).
//
// It leaves one guest order delivered, which stays open until its problem
// window ends: one address may hold three open guest orders (P-108-4), so
// on one database about three runs fit in three days. Guest orders never
// count against an account, so no other journey's buyer is affected.
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { checkAccessibility } from './a11y.mjs';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SHOTS = process.argv[2] || '.';
mkdirSync(SHOTS, { recursive: true });
const SHOP_PHONES = { 'Merkato Mobile': '0911000901', 'Bole Phone House': '0911000902', 'Piassa Electronics': '0911000903' };

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function caller(page) {
  return (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const r = await fetch(p, { method: m, cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, [method, path, body]);
}

async function signInByCode(page, phone) {
  await page.goto(`${BASE}/en/sign-in`);
  const call = caller(page);
  const asked = await call('POST', '/api/v1/auth/otp/request', { phone, language: 'en' });
  expect(asked.status === 200 || asked.status === 202, `code for ${phone}: ${asked.status} ${JSON.stringify(asked.body)}`);
  const inbox = (await call('GET', `/api/v1/dev/sms-inbox?phone=${phone}`)).body;
  const verified = await call('POST', '/api/v1/auth/otp/verify', { phone, code: inbox.at(-1).text.match(/\b\d{6}\b/)[0] });
  expect(verified.status === 200, `sign-in ${phone}: ${verified.status}`);
  return call;
}

async function fits(page, label) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide <= 0, `${label} is ${wide}px wider than the screen`);
}

const browser = await chromium.launch();
const errors = [];
const watch = (page, who) => page.on('console', (m) => { if (m.type() === 'error' && !/_rsc=|404 \(Not Found\)/.test(m.text())) errors.push(`${who}: ${m.text().slice(0, 120)}`); });
try {
  const guest = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  watch(guest, 'guest');
  const call = caller(guest);

  // 1. The visitor puts a phone a shop delivers to Bole by its own rider in the cart.
  await guest.goto(`${BASE}/en/p/tecno-spark-20?zone=bole`);
  const listed = await call('GET', '/api/v1/catalog/products/tecno-spark-20/offers?zone=bole');
  const offer = listed.body.offers.find((o) => o.delivers_by_seller_rider && o.in_stock);
  expect(offer, `no offer delivered by a rider: ${JSON.stringify(listed.body)}`);
  expect((await call('PUT', `/api/v1/cart/items/${offer.id}`, { quantity: 1 })).status === 200, 'cart');
  console.log(`1 in the cart: a Tecno Spark 20 from ${offer.store_name}, delivered by its rider`);

  // 2. The cart's checkout leads to sign-in, which offers ordering as a guest.
  await guest.goto(`${BASE}/en/cart`);
  await guest.getByRole('link', { name: 'Continue to checkout' }).click();
  await guest.waitForURL(/\/en\/sign-in/);
  await guest.getByRole('heading', { name: 'No Telegram, or Telegram not working?' }).waitFor();
  await checkAccessibility(guest, 'sign-in with the guest option (en)');
  await fits(guest, '/en/sign-in with the guest option');
  await guest.getByRole('link', { name: 'Order as a guest' }).click();
  await guest.waitForURL(/\/en\/checkout\/guest$/);
  await guest.getByRole('heading', { name: 'Order as a guest', level: 1 }).waitFor();
  await checkAccessibility(guest, 'guest checkout, empty (en)');
  await fits(guest, '/en/checkout/guest');
  console.log('2 sign-in offers "Order as a guest"; the guest page opens at 360 px');

  // 3. Name, address and phone; delivery to the door only.
  await guest.fill('input[name=recipient]', 'Journey Guest Abebe');
  const number = `0911${String(Math.floor(Math.random() * 1e6)).padStart(6, '0')}`;
  await guest.fill('input[name=phone]', number);
  await guest.selectOption('select[name=area]', { label: 'Bole Medhanialem' });
  await guest.fill('input[name=landmark]', 'Opposite the journey test kiosk, green door');
  await guest.getByText('Guests are delivered to their door.').waitFor();
  expect(await guest.getByText('Collect at the shop').count() === 0, 'a guest was offered collection at the shop');
  await guest.getByText('ETB 50,000').first().waitFor();
  await guest.getByRole('button', { name: 'Review' }).click();
  await guest.getByText('Grand total').waitFor();
  await checkAccessibility(guest, 'guest checkout, review (en)');
  await guest.screenshot({ path: join(SHOTS, 'guest-review-en.png'), fullPage: true });
  await guest.getByRole('button', { name: 'Place order' }).click();
  const placed = guest.getByRole('heading', { name: /Your order MX-[A-Z0-9]{6} is placed\./ });
  const refusal = guest.locator('main [role=alert]');
  await placed.or(refusal).first().waitFor();
  if (await refusal.count()) {
    await guest.screenshot({ path: join(SHOTS, 'guest-refused.png'), fullPage: true });
    throw new Error(`the guest order was refused: ${await refusal.first().innerText()}`);
  }
  const code = (await placed.innerText()).match(/MX-[A-Z0-9]{6}/)[0];
  await guest.getByText('Save this link now.').waitFor();
  const link = await guest.locator('[data-guest-link]').innerText();
  expect(new RegExp(`^${BASE}/en/track/[0-9a-f-]{36}\\?expires=\\d+&signature=[A-Za-z0-9_-]{43}$`).test(link), `link: ${link}`);
  await checkAccessibility(guest, 'guest checkout, placed (en)');
  await fits(guest, 'guest checkout, placed');
  await guest.screenshot({ path: join(SHOTS, 'guest-placed-en.png'), fullPage: true });
  console.log(`3 ${code} placed as a guest; the page gives the tracking link to keep`);

  // 4. Nothing more: no session, no account opened, nothing of the demo buyer's.
  // Asked with the guest browser's own cookies, from outside the page, so the
  // expected "401" is not counted as a console error.
  const cookies = await guest.context().cookies();
  expect(!cookies.some((c) => c.name === 'markx_session'), 'a session cookie was set');
  const asked = await fetch(`${BASE}/api/v1/me`, { headers: { cookie: cookies.map((c) => `${c.name}=${c.value}`).join('; ') } });
  expect(asked.status === 401, `the guest was signed in: ${asked.status}`);
  await guest.getByRole('link', { name: 'Open your order page' }).click();
  await guest.waitForURL(/\/en\/track\//);
  await guest.getByText('You ordered as a guest.').waitFor();
  const page = await guest.locator('main').innerText();
  expect(page.includes(code) && !page.includes('Demo Buyer') && !page.includes('demo building'), 'the guest page shows the demo buyer or misses the order');
  expect(await guest.locator('[data-handover-code]').count() === 0, 'a code before the parcel is ready');
  await checkAccessibility(guest, 'guest tracking page, placed (en)');
  await fits(guest, 'guest tracking page');
  console.log('4 no session, no account; the link shows the order and nothing of the demo buyer');

  // 5. The shop accepts, packs and sends it; the guest's link shows the code.
  const shopPage = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  watch(shopPage, 'shop');
  const asShop = await signInByCode(shopPage, SHOP_PHONES[offer.store_name]);
  const me = (await asShop('GET', '/api/v1/me')).body;
  const sellerId = me.sellers?.[0]?.seller_id;
  expect(sellerId, `the shop's seller id: ${JSON.stringify(me)}`);
  const rows = (await asShop('GET', `/api/v1/seller/${sellerId}/orders`)).body;
  const part = rows.find((row) => row.order_code === code);
  expect(part && part.buyer === null, `the shop's view before accepting: ${JSON.stringify(part)}`);
  const base = `/api/v1/seller/${sellerId}/orders/${part.id}`;
  for (const [step, body] of [['confirm'], ['ready'], ['dispatch', { rider_name: 'Journey Rider', rider_phone: '0922000111' }]]) {
    const done = await asShop('POST', `${base}/${step}`, body);
    expect(done.status === 200, `${step}: ${done.status} ${JSON.stringify(done.body)}`);
  }
  const seen = (await asShop('GET', base)).body;
  expect(seen.buyer?.recipient_name === 'Journey Guest Abebe' && seen.buyer?.phone === `+251${number.slice(1)}`, `the shop sees the guest as any buyer: ${JSON.stringify(seen.buyer)}`);
  await guest.reload();
  const shown = guest.locator('[data-handover-code]');
  await shown.waitFor();
  const handover = (await shown.innerText()).match(/\b\d{6}\b/)[0];
  await guest.getByText('Give this code only after you have inspected the goods').waitFor();
  await checkAccessibility(guest, 'guest tracking page, on the way (en)');
  await guest.screenshot({ path: join(SHOTS, 'guest-handover-code-en.png'), fullPage: true });
  console.log('5 the shop accepted and sent it; the guest\'s link shows the handover code');

  // 6. At the door: the guest gives the code; the shop enters it.
  const handed = await asShop('POST', `${base}/handover`, { code: handover });
  expect(handed.status === 200 && handed.body.status === 'delivered', `handover: ${handed.status} ${JSON.stringify(handed.body)}`);
  await guest.reload();
  await guest.getByText('Delivered').first().waitFor();
  expect(await guest.locator('[data-handover-code]').count() === 0, 'the code is still shown after the handover');
  console.log('6 handed over with the code; the link shows it delivered');

  // 7. The same pages in Amharic, from a fresh visitor.
  const amharic = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  watch(amharic, 'amharic');
  await amharic.goto(`${BASE}/am/sign-in`);
  await amharic.getByRole('link', { name: 'እንደ እንግዳ ይዘዙ' }).click();
  await amharic.waitForURL(/\/am\/checkout\/guest$/);
  await amharic.getByRole('heading', { name: 'እንደ እንግዳ ይዘዙ', level: 1 }).waitFor();
  await checkAccessibility(amharic, 'guest checkout (am)');
  await fits(amharic, '/am/checkout/guest');
  await amharic.goto(link.replace('/en/track/', '/am/track/'));
  await amharic.getByText('እንደ እንግዳ አዝዘዋል።').waitFor();
  await checkAccessibility(amharic, 'guest tracking page (am)');
  await fits(amharic, '/am/track');
  await amharic.screenshot({ path: join(SHOTS, 'guest-tracking-am.png'), fullPage: true });
  console.log('7 the guest pages in Amharic');
} finally {
  await browser.close();
}
console.log('console errors:', errors.length ? errors : 'none');
if (errors.length) process.exit(1);
