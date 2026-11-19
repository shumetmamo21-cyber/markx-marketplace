// Staff work a problem case in a real browser, against a running API (8000)
// and web app (3000) filled by scripts/seed_demo.py (DEMO data).
//
//   MARKX_DEMO_TOTP=$(cd ../api && uv run python -c "import pyotp,sys; print(pyotp.TOTP(sys.argv[1]).now())" SECRET) \
//     node e2e/staff-journey.mjs [screenshot-folder]
//
// SECRET is the demo staff authenticator secret seed_demo.py printed. A
// buyer orders, the shop delivers (set up through the API), the buyer reports
// a problem on the order page, and staff decide it in the admin dashboard.
//
// Or give the secret itself (MARKX_DEMO_TOTP_SECRET=SECRET), and the code is
// computed at the moment staff sign in, so it cannot expire on the way.
import { createHmac } from 'node:crypto';
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SECRET = process.env.MARKX_DEMO_TOTP_SECRET;
if (!process.env.MARKX_DEMO_TOTP && !SECRET) throw new Error('set MARKX_DEMO_TOTP_SECRET (or MARKX_DEMO_TOTP, the current code)');

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

async function code(page, phone) {
  const inbox = await page.evaluate(async (p) => (await fetch(`/api/v1/dev/sms-inbox?phone=${p}`)).json(), phone);
  return inbox[inbox.length - 1].text.match(/\b\d{6}\b/)[0];
}

function caller(page) {
  return (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const r = await fetch(p, { method: m, headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json() };
  }, [method, path, body]);
}

async function signIn(page, phone) {
  await page.goto(`${BASE}/en/sign-in`);
  const call = caller(page);
  await call('POST', '/api/v1/auth/otp/request', { phone, language: 'en' });
  const verified = await call('POST', '/api/v1/auth/otp/verify', { phone, code: await code(page, phone) });
  if (verified.status !== 200) throw new Error(`sign-in ${phone}: ${verified.status}`);
  return call;
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  let refusalsExpected = false; // only during the deliberate isolation checks
  let signingIn = false; // a replayed staff code is refused once, then retried
  const watch = (page, who) => page.on('console', (m) => {
    if (m.type() !== 'error' || /_rsc=|404 \(Not Found\)/.test(m.text())) return;
    if (signingIn && /401 \(Unauthorized\)/.test(m.text())) return;
    if (refusalsExpected && /40[34] \(/.test(m.text())) return;
    errors.push(`${who}: ${m.text().slice(0, 120)}`);
  });

  // Set-up through the API: an order from Merkato Mobile (collection), delivered.
  const buyer = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  watch(buyer, 'buyer');
  const asBuyer = await signIn(buyer, '0911000950');
  const orders = await asBuyer('GET', '/api/v1/me/orders');
  for (const o of orders.body) for (const p of o.seller_orders) if (p.can_cancel) await asBuyer('POST', `/api/v1/me/orders/${o.id}/seller-orders/${p.id}/cancel`, {});
  const offers = await asBuyer('GET', '/api/v1/catalog/products/xiaomi-redmi-13c/offers');
  const offer = offers.body.offers.find((o) => o.store_slug === 'merkato-mobile' && o.in_stock);
  await asBuyer('DELETE', '/api/v1/cart');
  await asBuyer('PUT', `/api/v1/cart/items/${offer.id}`, { quantity: 1 });
  const address = (await asBuyer('GET', '/api/v1/me/addresses')).body[0];
  const deliveries = [{ store_slug: 'merkato-mobile', method: 'shop_collection' }];
  const quote = await asBuyer('POST', '/api/v1/checkout/quote', { address_id: address.id, deliveries });
  const placed = await asBuyer('POST', '/api/v1/checkout', {
    address_id: address.id, deliveries, payment_method: 'cash',
    expected_total_santim: quote.body.grand_total_santim, idempotency_key: `staffjourney${Date.now()}`,
  });
  if (placed.status !== 201) throw new Error(`checkout ${placed.status} ${JSON.stringify(placed.body)}`);
  const order = placed.body;
  const part = order.seller_orders[0];

  const shop = await (await browser.newContext()).newPage();
  const asShop = await signIn(shop, '0911000901');
  const sellerId = (await asShop('GET', '/api/v1/me')).body.sellers[0].seller_id;
  for (const step of ['confirm', 'ready']) await asShop('POST', `/api/v1/seller/${sellerId}/orders/${part.id}/${step}`, {});
  const mine = await asBuyer('GET', `/api/v1/me/orders/${order.id}`);
  const handover = mine.body.seller_orders[0].handover_code;
  const delivered = await asShop('POST', `/api/v1/seller/${sellerId}/orders/${part.id}/handover`, { code: handover });
  console.log('set-up:', order.code, 'collected at the shop ->', delivered.body.status);

  // 1. The buyer reports a problem on the order page.
  await buyer.goto(`${BASE}/en/orders/${order.id}`);
  await buyer.getByRole('button', { name: 'Report a problem' }).click();
  await buyer.selectOption('select[name=type]', 'damaged');
  await buyer.fill('textarea[name=description]', 'The screen has a crack along the top edge.');
  await buyer.getByRole('button', { name: 'Send report' }).click();
  await buyer.getByText('Problem reported').first().waitFor();
  console.log('1 buyer reported a problem; status:', await buyer.locator('section span.rounded-full').first().innerText());

  // 2. Staff sign in with password and authenticator code.
  const staff = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(staff, 'staff');
  await staff.goto(`${BASE}/en/admin`);
  await staff.waitForURL(/\/en\/admin\/sign-in$/);
  await staff.fill('input[name=phone]', '0911000900');
  await staff.fill('input[name=password]', process.env.MARKX_DEMO_STAFF_PASSWORD || 'demo-only-staff-password-1');
  // A code already used in this 30-second step (by another journey just
  // before) is refused once as a replay; with the secret, the next code is tried.
  signingIn = true;
  for (let attempt = 1; ; attempt++) {
    await staff.fill('input[name=totp]', SECRET ? totp(SECRET) : process.env.MARKX_DEMO_TOTP);
    await staff.getByRole('button', { name: 'Sign in' }).click();
    const refusal = staff.locator('form [role=alert]');
    const outcome = await Promise.race([
      staff.waitForURL(/\/en\/admin\/problems$/).then(() => 'in'),
      refusal.waitFor().then(() => 'refused'),
    ]);
    if (outcome === 'in') break;
    if (attempt >= 2 || !SECRET) throw new Error(`staff sign-in refused: ${await refusal.innerText()}`);
    await staff.waitForTimeout(30_000 - (Date.now() % 30_000) + 1_000);
  }
  signingIn = false;
  console.log('2 staff signed in; queue shows', await staff.locator('main li').count(), 'case(s)');

  // 3. Open the case and decide it: refunded, goods back at the shop.
  await staff.locator('main li', { hasText: order.code }).getByRole('link', { name: 'Open' }).click();
  await staff.waitForURL(/\/en\/admin\/orders\?code=/);
  await staff.getByText('The screen has a crack').waitFor();
  await staff.check('input[value=seller_refunded]');
  await staff.check('input[name=goods_returned]');
  await staff.fill('textarea[name=reason]', 'Photo shows a cracked screen; the shop took it back and returned the cash.');
  await staff.getByRole('button', { name: 'Record the decision' }).click();
  await staff.locator('section span.rounded-full', { hasText: /^Refunded$/ }).waitFor();
  console.log('3 staff decided: part is now', await staff.locator('section span.rounded-full').first().innerText());
  if (process.argv[2]) await staff.screenshot({ path: `${process.argv[2]}/admin-order.png`, fullPage: true });

  // 4. The buyer sees the decision.
  await buyer.reload();
  console.log('4 buyer sees:', await buyer.locator('section span.rounded-full').first().innerText(), '/',
    await buyer.getByText(/^Decision:/).innerText());

  // 5. Search tools and the seller queue.
  await staff.goto(`${BASE}/en/admin/search`);
  await staff.fill('input[name=term]', `mobayl${Date.now() % 100000}`);
  await staff.fill('input[name=expansion]', 'phones');
  await staff.getByRole('button', { name: 'Add' }).click();
  await staff.getByText('→ phones').first().waitFor();
  console.log('5 synonym added; seller queue:', await (async () => {
    await staff.goto(`${BASE}/en/admin/sellers`);
    return staff.locator('main h1 + *').first().innerText();
  })());
  // 6. Isolation: one shop cannot open another's dashboard, through the
  // screen or the API, and a buyer's session never reaches the admin area.
  refusalsExpected = true;
  const piassa = '0911000903';
  const other = await (await browser.newContext()).newPage();
  const asPiassa = await signIn(other, piassa);
  const piassaId = (await asPiassa('GET', '/api/v1/me')).body.sellers[0].seller_id;
  await shop.goto(`${BASE}/en/seller/${piassaId}/orders`);
  console.log('6 Merkato opens Piassa\'s dashboard:', await shop.locator('main p').first().innerText());
  const direct = await asShop('GET', `/api/v1/seller/${piassaId}/orders`);
  console.log('  and calls its API directly:', direct.status, direct.body.error?.code);
  await buyer.goto(`${BASE}/en/admin/problems`);
  console.log('  a buyer opening the admin area lands on', new URL(buyer.url()).pathname);
  const asAdmin = await asBuyer('GET', '/api/v1/admin/orders/problems');
  console.log('  and the admin API answers the buyer', asAdmin.status, asAdmin.body.error?.code);
  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
