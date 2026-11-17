// The buyer's whole journey in a real browser, against a running API (port
// 8000) and web app (port 3000) filled by scripts/seed_demo.py (DEMO data).
//
//   node e2e/buyer-journey.mjs [screenshot-folder]
//
// Needs the playwright package and its Chromium. Sign-in codes are read from
// the API's development SMS inbox, so this works only against MARKX_ENV=local.
// Each run uses up sign-in codes: the API allows five per phone an hour.
import { createRequire } from 'node:module';

// Resolved like a CommonJS module, so a globally installed Playwright works too.
const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
async function code(page, phone) {
  const inbox = await page.evaluate(async (p) => (await fetch(`/api/v1/dev/sms-inbox?phone=${p}`)).json(), phone);
  const text = inbox[inbox.length - 1].text;
  return text.match(/\b\d{6}\b/)[0];
}
(async () => {
  const browser = await chromium.launch();
  const buyer = await browser.newPage({ viewport: { width: 360, height: 800 } });
  const errors = [];
  buyer.on('console', (m) => { if (m.type() === 'error' && !/_rsc=|404 \(Not Found\)/.test(m.text())) errors.push(m.text().slice(0, 120)); });
  // 1. Sign in with a code.
  await buyer.goto(`${BASE}/en/sign-in?next=/en/cart`);
  await buyer.fill('input[type=tel]', '0911000950');
  await buyer.getByRole('button', { name: 'Send code' }).click();
  await buyer.getByText('We sent a code').waitFor();
  await buyer.fill('input[name=code]', await code(buyer, '0911000950'));
  await buyer.getByRole('button', { name: 'Sign in', exact: true }).click();
  await buyer.waitForURL((url) => url.pathname === '/en/cart');
  console.log('1 signed in, on', new URL(buyer.url()).pathname);
  const cancelled = await buyer.evaluate(async () => {
    const csrf = decodeURIComponent(document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')).split('=')[1]);
    const orders = await (await fetch('/api/v1/me/orders')).json();
    let n = 0;
    for (const o of orders) for (const p of o.seller_orders) if (p.can_cancel) {
      const r = await fetch(`/api/v1/me/orders/${o.id}/seller-orders/${p.id}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: '{}' });
      if (r.ok) n++;
    }
    return n;
  });
  console.log('  cancelled leftover open parts:', cancelled);
  // 2. Add the best offer for the Tecno to the cart.
  await buyer.goto(`${BASE}/en/p/tecno-spark-20?zone=bole`);
  await buyer.getByRole('button', { name: 'Add to cart' }).first().click();
  await buyer.getByText('Added to your cart').waitFor();
  await buyer.goto(`${BASE}/en/cart`);
  await buyer.getByRole('link', { name: 'Continue to checkout' }).waitFor();
  console.log('2 cart:', await buyer.locator('section h2').first().innerText());
  // 3. Checkout: saved address, default delivery, cash, review, place.
  await buyer.getByRole('link', { name: 'Continue to checkout' }).click();
  await buyer.waitForURL(/\/en\/checkout$/);
  await buyer.getByRole('button', { name: 'Review' }).click();
  await buyer.getByText('Grand total').waitFor();
  const total = await buyer.locator('section:has-text("Grand total") p:has-text("Grand total") .price').innerText();
  await buyer.getByRole('button', { name: 'Place order' }).click();
  await buyer.waitForTimeout(3000);
  const alert = await buyer.locator('[role=alert]').allInnerTexts();
  if (alert.length) console.log('  checkout says:', alert);
  await buyer.waitForURL(/\/en\/orders\/[0-9a-f-]{36}$/);
  const store = await buyer.locator('section h2').first().innerText();
  console.log('3 order placed, total', total, 'from', store, 'status:', await buyer.locator('section span.rounded-full').first().innerText());
  const shopPhone = { 'Merkato Mobile': '0911000901', 'Bole Phone House': '0911000902', 'Piassa Electronics': '0911000903' }[store];
  // 4. The shop (a second browser) confirms, packs and dispatches through the API.
  const shop = await (await browser.newContext()).newPage();
  await shop.goto(`${BASE}/en/sign-in`);
  const call = (method, path, body) => shop.evaluate(async ([m, p, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const r = await fetch(p, { method: m, headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json() };
  }, [method, path, body]);
  await call('POST', '/api/v1/auth/otp/request', { phone: shopPhone, language: 'en' });
  await call('POST', '/api/v1/auth/otp/verify', { phone: shopPhone, code: await code(shop, shopPhone) });
  const me = await call('GET', '/api/v1/me');
  const sellerId = me.body.sellers[0].seller_id;
  const parts = await call('GET', `/api/v1/seller/${sellerId}/orders?status=placed`);
  const part = parts.body[0];
  for (const step of ['confirm', 'ready', 'dispatch']) {
    const r = await call('POST', `/api/v1/seller/${sellerId}/orders/${part.id}/${step}`, step === 'dispatch' ? { rider_name: 'Demo Rider' } : {});
    if (r.status !== 200) throw new Error(step + ' ' + r.status + JSON.stringify(r.body));
  }
  // 5. The buyer sees the code; the shop enters it at the door.
  await buyer.reload();
  const handover = (await buyer.locator('p.price.text-4xl').innerText()).trim();
  console.log('5 buyer sees status', await buyer.locator('section span.rounded-full').first().innerText(), 'and a', handover.length, 'digit code');
  const h = await call('POST', `/api/v1/seller/${sellerId}/orders/${part.id}/handover`, { code: handover });
  console.log('  shop enters the code:', h.status, h.body.status);
  // 6. The buyer confirms the goods are right.
  await buyer.reload();
  await buyer.getByRole('button', { name: 'The goods are right' }).click();
  await buyer.getByText('Completed').first().waitFor();
  console.log('6 final status:', await buyer.locator('section span.rounded-full').first().innerText());
  await buyer.screenshot({ path: (process.argv[2] || '.') + '/order-done.png', fullPage: true });
  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
