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
// Pictures: the shop adds a real photo of what it sells, sees it rendered and
// on the product page, and withdraws it; on a second order the buyer reports
// a problem with a message and a photo, and the shop adds its own photo.
// With MARKX_DEMO_TOTP_SECRET (the staff secret seed_demo.py printed), staff
// also see both photos in the orders desk and decide the problem, and a
// catalogue picture is shown on the product page and the product card, then
// taken down again. Every page is checked at 360 pixels in both languages.
//
// Each run signs the buyer and one shop in once (the API allows five codes per
// phone an hour), buys one unit of demo stock, and writes one review; a buyer's
// fourth review of one shop in 30 days is held for staff, so the run picks the
// shop the buyer has reviewed least, and stops if every shop is at the limit.
import { execFileSync } from 'node:child_process';
import { createHmac } from 'node:crypto';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const API_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'api');
const shots = process.argv[2];
const BUYER = '0911000950';
const SHOPS = { 'merkato-mobile': '0911000901', 'bole-phone-house': '0911000902', 'piassa-electronics': '0911000903' };
const SECRET = process.env.MARKX_DEMO_TOTP_SECRET;
// Marks this run's review, so a run never mistakes an earlier run's for its own.
const TAG = `run ${Date.now().toString(36)}`;
// A 120 x 90 PNG, as a phone might send it.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAHgAAABaCAIAAAD8YgW4AAAA4UlEQVR4nO3QQRHAIADAMEDIdCIRWVOx8liioNf57DP43rod8BdGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjL6p6AhINcwbMAAAAAElFTkSuQmCC', 'base64');
const photo = (name) => ({ name, mimeType: 'image/png', buffer: PNG });

/** RFC 6238: the current six-digit code for a base-32 secret. */
function totp(secret) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret.replace(/=+$/, '').toUpperCase()].map((c) => alphabet.indexOf(c).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const mac = createHmac('sha1', key).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return ((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, '0');
}

const render = () => execFileSync('uv', ['run', 'python', '-m', 'markx.worker', '--once'], { cwd: API_DIR, stdio: 'ignore' });

/** True when every picture in the locator has really loaded. */
async function allLoaded(locator) {
  const sizes = await locator.evaluateAll((images) => images.map((image) => image.complete && image.naturalWidth > 0));
  return sizes.length > 0 && sizes.every(Boolean);
}

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

/** Staff sign in with password and authenticator code. A code typed at the
 * end of its 30 seconds can expire before the API checks it: then the next
 * code is tried once more. */
async function staffSignIn(page) {
  await page.goto(`${BASE}/en/admin`);
  await page.waitForURL(/\/en\/admin\/sign-in$/);
  await page.fill('input[name=phone]', '0911000900');
  await page.fill('input[name=password]', 'demo-only-staff-password-1');
  for (let attempt = 1; ; attempt++) {
    await page.fill('input[name=totp]', totp(SECRET));
    await page.getByRole('button', { name: 'Sign in' }).click();
    // The form's own refusal, not Next.js's route announcer (also an alert).
    const refusal = page.locator('form [role=alert]');
    const outcome = await Promise.race([
      page.waitForURL(/\/en\/admin\/(?!sign-in)/, { waitUntil: 'commit' }).then(() => 'in'),
      refusal.waitFor().then(() => 'refused'),
    ]);
    if (outcome === 'in') return caller(page);
    expect(attempt < 2, `staff sign-in refused: ${await refusal.innerText()}`);
    await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 1_000);
  }
}

/** Problems an interrupted earlier run of this journey left open block the
 * buyer's next order (too many open orders): staff decide them first. */
async function decideLeftovers(asStaff) {
  for (const open of (await asStaff('GET', '/api/v1/admin/orders/problems?limit=100')).body ?? []) {
    const found = (await asStaff('GET', `/api/v1/admin/orders/${open.order_code}?lang=en`)).body;
    const part = found?.seller_orders?.find((p) => p.id === open.seller_order_id);
    if (part?.problem?.description === 'Demo: the screen has a scratch.') {
      const decided = await asStaff('POST', `/api/v1/admin/orders/seller-orders/${open.seller_order_id}/resolve-problem`, { decision: 'no_action', reason: 'Demo: left open by an interrupted run', goods_returned: false });
      console.log('  decided a demo problem an interrupted run left open:', open.order_code, decided.status);
    }
  }
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
  let staff = null;
  let asStaff = null;
  if (SECRET) {
    staff = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
    watch(staff, 'staff');
    asStaff = await staffSignIn(staff);
    await decideLeftovers(asStaff);
  }
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
  await rate.getByLabel('What should other buyers know? (optional)').fill(`Demo review (${TAG}): sealed box, works well.`);
  await rate.getByRole('button', { name: 'Send review' }).click();
  await buyer.getByRole('status').filter({ hasText: 'Your review is saved' }).waitFor();
  await buyer.reload();
  expect(await buyer.locator('details', { hasText: 'Rate this purchase' }).count() === 0, 'the rated item is still offered for rating');
  console.log('4 rated on the order page; it is no longer offered');

  // 5. Change it on "Your reviews" while the shop has not replied.
  await buyer.goto(`${BASE}/en/reviews`);
  const mine = buyer.locator('li', { hasText: TAG }).first();
  expect((await mine.innerText()).includes('Published'), 'the new review is not shown as published');
  await mine.getByText('Change your review').click();
  await mine.getByRole('group', { name: 'How good is the product?' }).getByText('5 ★').click();
  await mine.getByLabel('What should other buyers know? (optional)').fill(`Demo review (${TAG}): sealed box, works well. Fast handover.`);
  await mine.getByRole('button', { name: 'Save the change' }).click();
  await buyer.getByRole('status').filter({ hasText: 'Your review is saved' }).waitFor();
  console.log('5 changed on Your reviews');
  if (shots) await buyer.screenshot({ path: `${shots}/my-reviews.png`, fullPage: true });

  // 6. The totals follow in the background; the review shows on the product and shop pages.
  render();
  await buyer.goto(`${BASE}/en/p/${offer.product_slug}`);
  const onProduct = buyer.locator('section[aria-labelledby=reviews] li', { hasText: TAG });
  await onProduct.waitFor();
  const summary = await buyer.locator('section[aria-labelledby=reviews] p').first().innerText();
  console.log('6 product page reviews:', summary.replace(/\s+/g, ' '));
  await buyer.goto(`${BASE}/en/s/${store}`);
  await buyer.locator('section[aria-labelledby=reviews] li', { hasText: TAG }).waitFor();
  console.log('  shop page shows it too');

  // 7. The shop replies on its reviews screen.
  await shop.goto(`${BASE}/en/seller/${sellerId}/reviews`);
  const card = shop.locator('li', { hasText: TAG }).first();
  await card.getByLabel('Your reply').fill('Thank you for buying from us. (demo)');
  await card.getByRole('button', { name: 'Send reply' }).click();
  await card.getByRole('status').waitFor();
  await shop.reload();
  await shop.locator('li', { hasText: TAG }).first().getByRole('button', { name: 'Change reply' }).waitFor();
  console.log('7 the shop replied; it may reword the reply');
  if (shots) await shop.screenshot({ path: `${shots}/shop-reviews.png`, fullPage: true });

  // 8. The buyer sees the reply and can no longer change the review.
  await buyer.goto(`${BASE}/en/reviews`);
  const answered = buyer.locator('li', { hasText: TAG }).first();
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
    const item = buyer.locator('section[aria-labelledby=reviews] li', { hasText: TAG });
    await item.getByText('Report this review').click();
    await item.getByLabel('What is wrong?').selectOption('spam');
    refusalExpected = attempt === 2;
    await item.getByRole('button', { name: 'Send report' }).click();
    if (attempt === 1) await item.getByRole('status').filter({ hasText: 'MarkX will look at it' }).waitFor();
    else console.log('  second time:', await item.getByRole('alert').innerText());
    refusalExpected = false;
  }
  console.log('  the buyer reported the review; a second report is refused in words');

  // 10. The shop adds a real photo of what it sells, sees it rendered, then withdraws it.
  await shop.goto(`${BASE}/en/seller/${sellerId}/offers`);
  await shop.locator('li', { hasText: offer.product_name }).first().getByRole('link', { name: 'Photos of this product' }).click();
  await shop.waitForURL(/\/photos\/[0-9a-f-]{36}$/);
  const photosPath = new URL(shop.url()).pathname;
  await shop.getByLabel('Photo (JPEG, PNG or WebP)').setInputFiles(photo('shop.png'));
  await shop.getByRole('button', { name: 'Upload photo' }).click();
  await shop.getByRole('status').filter({ hasText: 'The photo shows once it is ready' }).waitFor();
  render();
  await shop.reload();
  const ready = shop.locator('li', { hasText: 'Shown to buyers' }).first();
  await ready.waitFor();
  expect(await allLoaded(ready.locator('img')), 'the rendered photo does not load');
  const thumb = await ready.locator('img').getAttribute('src');
  await buyer.goto(`${BASE}/en/p/${offer.product_slug}`);
  const real = buyer.locator(`section[aria-labelledby=real-photos] img[src="${thumb}"]`);
  await real.waitFor();
  expect(await allLoaded(real), 'the shop photo does not load on the product page');
  console.log('10 the shop added a photo; rendered, it shows on the product page', await buyer.locator('section[aria-labelledby=real-photos] li', { has: buyer.locator(`img[src="${thumb}"]`) }).innerText());
  await ready.getByRole('button', { name: 'Withdraw this photo' }).click();
  await shop.locator('li', { hasText: 'Taken down' }).first().waitFor();
  await buyer.reload();
  expect(await buyer.locator(`img[src="${thumb}"]`).count() === 0, 'a withdrawn photo is still on the product page');
  console.log('  withdrawn: gone from the product page');

  // 11. A second order, delivered: the buyer reports a problem with a message and a photo.
  await asBuyer('DELETE', '/api/v1/cart');
  const again = (await asBuyer('GET', `/api/v1/catalog/stores/${store}/offers?lang=en`)).body.find((o) => o.in_stock);
  expect(again, `${store} has no stock left for a second order`);
  await asBuyer('PUT', `/api/v1/cart/items/${again.id}`, { quantity: 1 });
  const quote2 = await asBuyer('POST', '/api/v1/checkout/quote', { address_id: address.id, deliveries });
  const placed2 = await asBuyer('POST', '/api/v1/checkout', {
    address_id: address.id, deliveries, payment_method: 'cash',
    expected_total_santim: quote2.body.grand_total_santim, idempotency_key: `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  });
  expect(placed2.status === 201, `second checkout: ${placed2.status} ${JSON.stringify(placed2.body)}`);
  const order2 = placed2.body.id;
  const part2 = placed2.body.seller_orders[0].id;
  for (const step of ['confirm', 'ready']) await asShop('POST', `/api/v1/seller/${sellerId}/orders/${part2}/${step}`);
  const code2 = (await asBuyer('GET', `/api/v1/me/orders/${order2}`)).body.seller_orders[0].handover_code;
  expect((await asShop('POST', `/api/v1/seller/${sellerId}/orders/${part2}/handover`, { code: code2 })).status === 200, 'second handover');
  await buyer.goto(`${BASE}/en/orders/${order2}`);
  await buyer.getByRole('button', { name: 'Report a problem' }).click();
  await buyer.locator('select[name=type]').selectOption('damaged');
  await buyer.getByLabel('Tell us what happened').fill('Demo: the screen has a scratch.');
  await buyer.getByRole('button', { name: 'Send report' }).click();
  await buyer.getByText('Photos of the problem').or(buyer.getByText('Add a photo')).first().waitFor();
  await buyer.getByLabel('Add a message').fill('Demo: it was there when I opened the box.');
  await buyer.getByRole('button', { name: 'Send message' }).click();
  await buyer.getByRole('status').filter({ hasText: 'Message sent' }).waitFor();
  await buyer.getByLabel('Add a photo').setInputFiles(photo('scratch.png'));
  await buyer.getByRole('button', { name: 'Upload photo' }).click();
  await buyer.getByRole('status').filter({ hasText: 'Photo added' }).waitFor();
  await buyer.reload();
  const buyerEvidence = buyer.locator('img[alt^="Photo from the Buyer"]');
  await buyerEvidence.first().waitFor();
  expect(await allLoaded(buyerEvidence), 'the buyer cannot see their own evidence photo');
  expect((await buyer.locator('section', { hasText: 'Demo: the screen has a scratch' }).innerText()).includes('Buyer: Demo: it was there'), 'the message is not shown with its author in words');
  console.log('11 the buyer reported a problem, added a message and a photo, and sees it');
  if (shots) await buyer.screenshot({ path: `${shots}/problem-buyer.png`, fullPage: true });

  // 12. The shop sees the buyer's photo and adds its own.
  await shop.goto(`${BASE}/en/seller/${sellerId}/orders/${part2}`);
  const seen = shop.locator('img[alt^="Photo from the Buyer"]');
  await seen.first().waitFor();
  expect(await allLoaded(seen), 'the shop cannot see the buyer\'s photo');
  await shop.getByLabel('Add a photo').setInputFiles(photo('packed.png'));
  await shop.getByRole('button', { name: 'Upload photo' }).click();
  await shop.getByRole('status').filter({ hasText: 'Photo added' }).waitFor();
  await shop.reload();
  expect(await allLoaded(shop.locator('img[alt^="Photo from the Shop"]')), 'the shop cannot see its own photo');
  console.log('12 the shop sees the buyer\'s photo and added its own');

  // 13. Staff (with the secret): both photos in the orders desk, the problem
  // decided; a catalogue picture on the product page and the card, then taken down.
  if (staff) {
    await staff.goto(`${BASE}/en/admin/orders?code=${placed2.body.code}`);
    const evidence = staff.locator('img[alt^="Photo from the"]');
    await evidence.first().waitFor();
    expect(await evidence.count() === 2 && await allLoaded(evidence), 'staff do not see both photos');
    const decided = await asStaff('POST', `/api/v1/admin/orders/seller-orders/${part2}/resolve-problem`, { decision: 'no_action', reason: 'Demo: photos checked', goods_returned: false });
    expect(decided.status === 200, `decide: ${decided.status} ${JSON.stringify(decided.body)}`);
    console.log('13 staff see both photos in the orders desk and decided the problem');
    const known = new Set((await asBuyer('GET', `/api/v1/catalog/products/${offer.product_slug}/images`)).body.catalogue.map((i) => i.id));
    await staff.goto(`${BASE}/en/admin/pictures?product=${offer.product_slug}`);
    await staff.getByLabel('Photo (JPEG, PNG or WebP)').setInputFiles(photo('catalogue.png'));
    await staff.getByRole('button', { name: 'Upload', exact: true }).click();
    await staff.getByRole('status').filter({ hasText: 'Done' }).waitFor();
    render();
    const images = (await asBuyer('GET', `/api/v1/catalog/products/${offer.product_slug}/images`)).body.catalogue;
    const added = images.find((i) => !known.has(i.id));
    expect(added, 'the new catalogue picture is not shown to buyers');
    await buyer.goto(`${BASE}/en/p/${offer.product_slug}`);
    expect(await allLoaded(buyer.locator('section[aria-label=Pictures] img')), 'the product page pictures do not load');
    await buyer.goto(`${BASE}/en/search?q=${encodeURIComponent(offer.product_name)}`);
    const card = buyer.locator(`a[href="/en/p/${offer.product_slug}"] img`);
    await card.first().waitFor();
    expect(await allLoaded(card.first()), 'the product card picture does not load');
    console.log('  a catalogue picture shows on the product page and on the product card');
    const removed = await asStaff('POST', `/api/v1/admin/catalog/images/${added.id}/remove`, { reason: 'Demo picture from the e2e journey' });
    expect(removed.status === 200, `take the demo picture down: ${removed.status}`);
    console.log('  the demo picture is taken down again');
  } else {
    console.log('13 skipped: set MARKX_DEMO_TOTP_SECRET for the staff steps (the problem stays open in the demo data)');
  }

  // 14. Amharic, and every page at 360 pixels.
  await buyer.goto(`${BASE}/am/p/${offer.product_slug}`);
  expect(await buyer.locator('#reviews').innerText() === 'ግምገማዎች', 'the Amharic product page has no reviews heading');
  const buyerCookies = await buyerContext.cookies();
  const shopCookies = await shopContext.cookies();
  for (const lang of ['en', 'am']) {
    for (const path of [`/${lang}/reviews`, `/${lang}/orders/${orderId}`, `/${lang}/orders/${order2}`, `/${lang}/orders`]) await noOverflow(browser, buyerCookies, path);
    for (const path of [`/${lang}/p/${offer.product_slug}`, `/${lang}/s/${store}`, `/${lang}/search`]) await noOverflow(browser, [], path);
    for (const path of [`/${lang}/seller/${sellerId}/reviews`, `/${lang}/seller/${sellerId}/offers`, photosPath.replace('/en/', `/${lang}/`), `/${lang}/seller/${sellerId}/orders/${part2}`]) await noOverflow(browser, shopCookies, path);
  }
  console.log('14 Amharic headings shown; every page fits 360 px in both languages');

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
