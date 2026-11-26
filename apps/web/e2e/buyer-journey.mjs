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
  // The price-history chart (C-21, D-106): drawn on the server, with its table.
  await buyer.getByRole('heading', { name: 'Price history' }).waitFor();
  const chart = buyer.locator('section[aria-labelledby=price-history] svg[role=img]').first();
  if (!/Now ETB [\d,]+ · lowest ETB [\d,]+ · highest ETB [\d,]+/.test(await chart.getAttribute('aria-label'))) throw new Error('the price chart has no summary');
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
  // C-27 (D-110): the notice before ordering, right above "Place order".
  const notice = buyer.getByRole('region', { name: 'Before you place your order' });
  await notice.waitFor();
  const points = await notice.locator('li').allInnerTexts();
  if (points.length !== 4 || !points[0].startsWith('You are buying from ') || !/within \d+ hours/.test(points[3])) {
    throw new Error(`the notice before ordering is not right: ${JSON.stringify(points)}`);
  }
  console.log('  the notice before ordering:', points.length, 'points, starting', JSON.stringify(points[0]));
  await buyer.getByRole('button', { name: 'Place order' }).click();
  await buyer.waitForTimeout(3000);
  const alert = await buyer.locator('[role=alert]').allInnerTexts();
  if (alert.length) console.log('  checkout says:', alert);
  await buyer.waitForURL(/\/en\/orders\/[0-9a-f-]{36}$/);
  const store = await buyer.locator('section h2').first().innerText();
  console.log('3 order placed, total', total, 'from', store, 'status:', await buyer.locator('section span.rounded-full').first().innerText());
  const shopPhone = { 'Merkato Mobile': '0911000901', 'Bole Phone House': '0911000902', 'Piassa Electronics': '0911000903' }[store];
  // 4. The shop works the order in its own dashboard, in a second browser.
  const shop = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  shop.on('console', (m) => { if (m.type() === 'error' && !/_rsc=|404 \(Not Found\)|409 \(Conflict\)/.test(m.text())) errors.push('shop: ' + m.text().slice(0, 120)); });
  await shop.goto(`${BASE}/en/sign-in?next=/en/seller`);
  await shop.fill('input[type=tel]', shopPhone);
  await shop.getByRole('button', { name: 'Send code' }).click();
  await shop.getByText('We sent a code').waitFor();
  await shop.fill('input[name=code]', await code(shop, shopPhone));
  await shop.getByRole('button', { name: 'Sign in', exact: true }).click();
  await shop.waitForURL(/\/en\/seller\/[0-9a-f-]{36}\/orders/);
  console.log('4 shop dashboard opens on', new URL(shop.url()).pathname.replace(/[0-9a-f-]{36}/, '{seller}'));
  await shop.getByRole('link', { name: /Order MX-/ }).first().click();
  await shop.getByRole('button', { name: 'Accept the order' }).click();
  await shop.getByText('Confirmed by the shop').first().waitFor();
  // Accepted: the buyer is on the shop's customer list (S-11, D-106), with
  // what the order page shows, and the order links back.
  const orderPage = shop.url();
  await shop.goto(orderPage.replace(/\/orders\/.*/, '/customers'));
  await shop.getByRole('heading', { name: 'Your customers' }).waitFor();
  const customer = shop.locator('main li', { hasText: 'Demo Buyer' }).first();
  await customer.waitFor();
  console.log('  shop: the buyer is on its customer list:', (await customer.locator('p').first().innerText()).trim());
  await shop.goto(orderPage);
  await shop.getByRole('button', { name: 'Mark as packed' }).click();
  const next = shop.getByRole('button', { name: /Send with a rider|Enter the buyer's code/ });
  await next.first().waitFor();
  if ((await next.first().innerText()).startsWith('Send')) {
    await next.first().click();
    await shop.fill('input[name=name]', 'Demo Rider');
    await shop.locator('form button[type=submit]').click();
    await shop.getByText('On the way').first().waitFor();
    console.log('  shop: accepted, packed, sent with a rider');
  } else {
    console.log('  shop: accepted, packed; the buyer collects at the shop');
  }
  // 5. The buyer sees the code; the shop enters it at the door, wrong first.
  await buyer.reload();
  const handover = (await buyer.locator('p.price.text-4xl').innerText()).trim();
  console.log('5 buyer sees status', await buyer.locator('section span.rounded-full').first().innerText(), 'and a', handover.length, 'digit code');
  await shop.getByRole('button', { name: "Enter the buyer's code" }).click();
  const wrong = handover === '000000' ? '111111' : '000000';
  await shop.fill('input[name=code]', wrong);
  await shop.locator('form button[type=submit]').click();
  console.log('  wrong code:', await shop.locator('p[role=alert]').innerText());
  await shop.fill('input[name=code]', handover);
  await shop.locator('form button[type=submit]').click();
  await shop.getByText('Delivered').first().waitFor();
  console.log('  shop enters the right code: Delivered');
  await shop.goto(shop.url().replace(/\/orders\/.*/, '/offers'));
  await shop.getByRole('button', { name: 'All my prices and stock are still right' }).click();
  console.log('  offers page:', await shop.getByRole('status').innerText());
  // 6. The buyer confirms the goods are right.
  await buyer.reload();
  await buyer.getByRole('button', { name: 'The goods are right' }).click();
  await buyer.getByText('Completed').first().waitFor();
  console.log('6 final status:', await buyer.locator('section span.rounded-full').first().innerText());
  await buyer.screenshot({ path: (process.argv[2] || '.') + '/order-done.png', fullPage: true });
  // 7. Order again in one tap (C-19, D-106): the same item, at today's price, in the cart.
  const orderUrl = buyer.url();
  await buyer.getByRole('button', { name: 'Order again' }).click();
  // Straight to the cart, or first a note of what changed with a link to it.
  const goToCart = buyer.getByRole('link', { name: 'Go to the cart' });
  for (let i = 0; i < 150 && new URL(buyer.url()).pathname !== '/en/cart'; i++) {
    const noted = await goToCart.count().catch(() => 0);
    if (noted) {
      console.log('  order again says first:', (await buyer.getByRole('status').first().innerText()).replace(/\s+/g, ' '));
      await goToCart.click();
      break;
    }
    await buyer.waitForTimeout(200);
  }
  await buyer.waitForURL((url) => url.pathname === '/en/cart');
  await buyer.getByRole('link', { name: 'Continue to checkout' }).waitFor();
  console.log('7 ordered again from', new URL(orderUrl).pathname.replace(/[0-9a-f-]{36}/, '{order}'), '- the cart holds:', await buyer.locator('section h2').first().innerText());
  // Emptied again, so the journeys after this one start with an empty cart.
  const emptied = await buyer.evaluate(async () => {
    const csrf = decodeURIComponent(document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')).split('=')[1]);
    return (await fetch('/api/v1/cart', { method: 'DELETE', headers: { 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf } })).status;
  });
  if (emptied !== 200) throw new Error(`emptying the cart answered ${emptied}`);
  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
