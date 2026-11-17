// The buyer's and the shop's screens beyond the order itself, in a real
// browser against a running API (8000) and web app (3000) filled by
// scripts/seed_demo.py (DEMO data):
//
//   node e2e/shop-screens.mjs [screenshot-folder]
//
// The demo buyer completes an order through the API (the buyer journey
// already drives those screens), then rates the purchase on the order page,
// changes the rating on "Your reviews", sees it on the product and shop pages,
// the shop replies on its reviews screen, and the buyer can no longer change
// it. Reports: a signed-out visitor reports a shop, the buyer a review, twice.
// Every page is checked at 360 pixels in both languages.
//
// Each run signs the buyer and one shop in once (the API allows five codes per
// phone an hour), buys one unit of demo stock, and writes one review; a buyer's
// fourth review of one shop in 30 days is held for staff, so the run picks the
// shop the buyer has reviewed least, and stops if every shop is at the limit.
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const API_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'api');
const shots = process.argv[2];
const BUYER = '0911000950';
const SHOPS = { 'merkato-mobile': '0911000901', 'bole-phone-house': '0911000902', 'piassa-electronics': '0911000903' };

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function caller(page) {
  return (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const r = await fetch(p, { method: m, headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
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

async function noOverflow(browser, cookies, path) {
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  await context.addCookies(cookies);
  const page = await context.newPage();
  const response = await page.goto(`${BASE}${path}`);
  expect(response.status() === 200, `${path} answered ${response.status()}`);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  await context.close();
  expect(wide <= 0, `${path} is ${wide}px wider than a 360px screen`);
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  let refusalExpected = false;
  const watch = (page, who) => page.on('console', (m) => {
    if (m.type() !== 'error' || /_rsc=|404 \(Not Found\)/.test(m.text())) return;
    if (refusalExpected && /409 \(Conflict\)/.test(m.text())) return;
    errors.push(`${who}: ${m.text().slice(0, 140)}`);
  });
  const buyerContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const buyer = await buyerContext.newPage();
  watch(buyer, 'buyer');

  // 1. The buyer signs in; leftovers of earlier runs are cancelled.
  const asBuyer = await signInByCode(buyer, BUYER);
  for (const order of (await asBuyer('GET', '/api/v1/me/orders')).body) {
    for (const part of order.seller_orders) {
      if (part.can_cancel) await asBuyer('POST', `/api/v1/me/orders/${order.id}/seller-orders/${part.id}/cancel`, {});
    }
  }
  const reviewed = {};
  for (const review of (await asBuyer('GET', '/api/v1/me/reviews?lang=en')).body) reviewed[review.store_slug] = (reviewed[review.store_slug] ?? 0) + 1;
  const order = Object.keys(SHOPS).sort((a, b) => (reviewed[a] ?? 0) - (reviewed[b] ?? 0));
  console.log('1 buyer signed in; earlier reviews per shop:', JSON.stringify(reviewed));

  // 2. Buy one unit from the shop reviewed least, collected at the shop.
  let store;
  let offer;
  for (const slug of order) {
    const listed = (await asBuyer('GET', `/api/v1/catalog/stores/${slug}/offers?lang=en`)).body;
    offer = listed.find((o) => o.in_stock);
    if (offer) { store = slug; break; }
  }
  expect(offer, 'no demo shop has stock left: run scripts/seed_demo.py on a fresh database');
  expect((reviewed[store] ?? 0) < 3, `the demo buyer has reviewed ${store} three times in 30 days; a fourth review would be held for staff`);
  await asBuyer('DELETE', '/api/v1/cart');
  expect((await asBuyer('PUT', `/api/v1/cart/items/${offer.id}`, { quantity: 1 })).status === 200, 'add to cart');
  const address = (await asBuyer('GET', '/api/v1/me/addresses')).body[0];
  const deliveries = [{ store_slug: store, method: 'shop_collection' }];
  const quote = await asBuyer('POST', '/api/v1/checkout/quote', { address_id: address.id, deliveries });
  expect(quote.status === 200, `quote: ${JSON.stringify(quote.body)}`);
  const placed = await asBuyer('POST', '/api/v1/checkout', {
    address_id: address.id, deliveries, payment_method: 'cash',
    expected_total_santim: quote.body.grand_total_santim, idempotency_key: `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  });
  expect(placed.status === 201, `checkout: ${placed.status} ${JSON.stringify(placed.body)}`);
  const orderId = placed.body.id;
  const partId = placed.body.seller_orders[0].id;

  // 3. The shop confirms, packs and hands over with the buyer's code; the buyer confirms.
  const shopContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const shop = await shopContext.newPage();
  watch(shop, 'shop');
  const asShop = await signInByCode(shop, SHOPS[store]);
  const sellerId = (await asShop('GET', '/api/v1/me')).body.sellers[0].seller_id;
  for (const step of ['confirm', 'ready']) {
    const moved = await asShop('POST', `/api/v1/seller/${sellerId}/orders/${partId}/${step}`);
    expect(moved.status === 200, `${step}: ${moved.status} ${JSON.stringify(moved.body)}`);
  }
  const code = (await asBuyer('GET', `/api/v1/me/orders/${orderId}`)).body.seller_orders[0].handover_code;
  expect((await asShop('POST', `/api/v1/seller/${sellerId}/orders/${partId}/handover`, { code })).status === 200, 'handover');
  expect((await asBuyer('POST', `/api/v1/me/orders/${orderId}/seller-orders/${partId}/confirm-received`)).status === 200, 'confirm received');
  console.log(`2-3 bought ${offer.product_name} from ${store}; the order is completed`);

  // 4. Rate this purchase on the order page.
  await buyer.goto(`${BASE}/en/orders/${orderId}`);
  const rate = buyer.locator('details', { hasText: 'Rate this purchase' });
  await rate.locator('summary').click();
  await rate.getByRole('group', { name: 'How good is the product?' }).getByText('4 ★').click();
  await rate.getByRole('group', { name: 'How was the shop?' }).getByText('5 ★').click();
  await rate.getByLabel('What should other buyers know? (optional)').fill('Demo review: sealed box, works well.');
  await rate.getByRole('button', { name: 'Send review' }).click();
  await buyer.getByRole('status').filter({ hasText: 'Your review is saved' }).waitFor();
  await buyer.reload();
  expect(await buyer.locator('details', { hasText: 'Rate this purchase' }).count() === 0, 'the rated item is still offered for rating');
  console.log('4 rated on the order page; it is no longer offered');

  // 5. Change it on "Your reviews" while the shop has not replied.
  await buyer.goto(`${BASE}/en/reviews`);
  const mine = buyer.locator('li', { hasText: 'Demo review: sealed box' }).first();
  expect((await mine.innerText()).includes('Published'), 'the new review is not shown as published');
  await mine.getByText('Change your review').click();
  await mine.getByRole('group', { name: 'How good is the product?' }).getByText('5 ★').click();
  await mine.getByLabel('What should other buyers know? (optional)').fill('Demo review: sealed box, works well. Fast handover.');
  await mine.getByRole('button', { name: 'Save the change' }).click();
  await buyer.getByRole('status').filter({ hasText: 'Your review is saved' }).waitFor();
  console.log('5 changed on Your reviews');
  if (shots) await buyer.screenshot({ path: `${shots}/my-reviews.png`, fullPage: true });

  // 6. The totals follow in the background; the review shows on the product and shop pages.
  execFileSync('uv', ['run', 'python', '-m', 'markx.worker', '--once'], { cwd: API_DIR, stdio: 'ignore' });
  await buyer.goto(`${BASE}/en/p/${offer.product_slug}`);
  const onProduct = buyer.locator('section[aria-labelledby=reviews] li', { hasText: 'Fast handover' });
  await onProduct.waitFor();
  const summary = await buyer.locator('section[aria-labelledby=reviews] p').first().innerText();
  console.log('6 product page reviews:', summary.replace(/\s+/g, ' '));
  await buyer.goto(`${BASE}/en/s/${store}`);
  await buyer.locator('section[aria-labelledby=reviews] li', { hasText: 'Fast handover' }).waitFor();
  console.log('  shop page shows it too');

  // 7. The shop replies on its reviews screen.
  await shop.goto(`${BASE}/en/seller/${sellerId}/reviews`);
  const card = shop.locator('li', { hasText: 'Fast handover' }).first();
  await card.getByLabel('Your reply').fill('Thank you for buying from us. (demo)');
  await card.getByRole('button', { name: 'Send reply' }).click();
  await card.getByRole('status').waitFor();
  await shop.reload();
  await shop.locator('li', { hasText: 'Fast handover' }).first().getByRole('button', { name: 'Change reply' }).waitFor();
  console.log('7 the shop replied; it may reword the reply');
  if (shots) await shop.screenshot({ path: `${shots}/shop-reviews.png`, fullPage: true });

  // 8. The buyer sees the reply and can no longer change the review.
  await buyer.goto(`${BASE}/en/reviews`);
  const answered = buyer.locator('li', { hasText: 'Fast handover' }).first();
  expect((await answered.innerText()).includes('Thank you for buying from us'), 'the reply is not on Your reviews');
  expect(await answered.getByText('Change your review').count() === 0, 'an answered review can still be changed');
  console.log('8 the buyer sees the reply; no change offered any more');

  // 9. Reports: a signed-out visitor reports the shop; the buyer reports the review, twice.
  const visitorContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const visitor = await visitorContext.newPage();
  watch(visitor, 'visitor');
  await visitor.goto(`${BASE}/en/s/${store}`);
  await visitor.getByText('Report this shop').click();
  await visitor.getByRole('form', { name: 'Report this shop' }).getByLabel('What is wrong?').selectOption('fraud');
  await visitor.getByRole('button', { name: 'Send report' }).click();
  await visitor.getByRole('status').filter({ hasText: 'MarkX will look at it' }).waitFor();
  console.log('9 a signed-out visitor reported the shop');
  for (const attempt of [1, 2]) {
    await buyer.goto(`${BASE}/en/p/${offer.product_slug}`);
    const item = buyer.locator('section[aria-labelledby=reviews] li', { hasText: 'Fast handover' });
    await item.getByText('Report this review').click();
    await item.getByLabel('What is wrong?').selectOption('spam');
    refusalExpected = attempt === 2;
    await item.getByRole('button', { name: 'Send report' }).click();
    if (attempt === 1) await item.getByRole('status').filter({ hasText: 'MarkX will look at it' }).waitFor();
    else console.log('  second time:', await item.getByRole('alert').innerText());
    refusalExpected = false;
  }
  console.log('  the buyer reported the review; a second report is refused in words');

  // 10. Amharic, and every page at 360 pixels.
  await buyer.goto(`${BASE}/am/p/${offer.product_slug}`);
  expect(await buyer.locator('#reviews').innerText() === 'ግምገማዎች', 'the Amharic product page has no reviews heading');
  const buyerCookies = await buyerContext.cookies();
  const shopCookies = await shopContext.cookies();
  for (const lang of ['en', 'am']) {
    for (const path of [`/${lang}/reviews`, `/${lang}/orders/${orderId}`, `/${lang}/orders`]) await noOverflow(browser, buyerCookies, path);
    for (const path of [`/${lang}/p/${offer.product_slug}`, `/${lang}/s/${store}`]) await noOverflow(browser, [], path);
    await noOverflow(browser, shopCookies, `/${lang}/seller/${sellerId}/reviews`);
  }
  console.log('10 Amharic headings shown; every page fits 360 px in both languages');

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
