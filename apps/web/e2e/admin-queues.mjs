// The admin queues in a real browser (D-070), against a running API (8000) and
// web app (3000) filled by scripts/seed_demo.py (DEMO data).
//
//   MARKX_DEMO_TOTP_SECRET=SECRET node e2e/admin-queues.mjs [screenshot-folder]
//
// SECRET is the demo staff authenticator secret seed_demo.py printed; the
// script computes the current code itself. A super administrator invites and
// withdraws, approves and turns down proposals, takes a listing down and lifts
// it, reads it all in the audit trail in English and Amharic, sees a packed
// rider order on the dispatch board, reads the dashboard and operations,
// publishes a held review, dismisses a report, changes a setting and puts it
// back, creates, re-roles and switches off a staff account, downloads an
// export, and uploads, sees rendered and takes down a picture.
// Then a catalogue curator is created and must see only its own queues.
import { spawnSync } from 'node:child_process';
import { createHmac } from 'node:crypto';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SECRET = process.env.MARKX_DEMO_TOTP_SECRET;
if (!SECRET) throw new Error('set MARKX_DEMO_TOTP_SECRET to the demo staff authenticator secret');
const shots = process.argv[2];

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

function caller(page) {
  return (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const r = await fetch(p, { method: m, headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json() };
  }, [method, path, body]);
}

async function signInByCode(page, phone) {
  await page.goto(`${BASE}/en/sign-in`);
  const call = caller(page);
  await call('POST', '/api/v1/auth/otp/request', { phone, language: 'en' });
  const inbox = (await call('GET', `/api/v1/dev/sms-inbox?phone=${phone}`)).body;
  const verified = await call('POST', '/api/v1/auth/otp/verify', { phone, code: inbox.at(-1).text.match(/\b\d{6}\b/)[0] });
  expect(verified.status === 200, `sign-in ${phone}: ${verified.status}`);
  return call;
}

// True while staff sign in: a code already used in this 30-second step (by an
// earlier run) is refused once as a replay, and the next code is tried.
let signingIn = false;

async function staffSignIn(page, phone, password, secret, landing) {
  await page.goto(`${BASE}/en/admin`);
  await page.waitForURL(/\/en\/admin\/sign-in$/);
  await page.fill('input[name=phone]', phone);
  await page.fill('input[name=password]', password);
  signingIn = true;
  for (let attempt = 1; ; attempt++) {
    await page.fill('input[name=totp]', totp(secret));
    await page.getByRole('button', { name: 'Sign in' }).click();
    // The form's own refusal, not Next.js's route announcer (also an alert).
    const refusal = page.locator('form [role=alert]');
    const outcome = await Promise.race([
      page.waitForURL(landing).then(() => 'in'),
      refusal.waitFor().then(() => 'refused'),
    ]);
    if (outcome === 'in') break;
    expect(attempt < 2, `staff sign-in refused: ${await refusal.innerText()}`);
    await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 1_000);
  }
  signingIn = false;
}

async function menu(page) {
  return page.locator('aside nav a').allInnerTexts();
}

async function noOverflow(browser, cookies, path) {
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  await context.addCookies(cookies);
  const page = await context.newPage();
  await page.goto(`${BASE}${path}`);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  await context.close();
  if (wide > 0) throw new Error(`${path} is ${wide}px wider than a 360px screen`);
}

// A 120 x 90 PNG for the picture upload.
const PICTURE_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAHgAAABaCAIAAAD8YgW4AAAA4UlEQVR4nO3QQRHAIADAMEDIdCIRWVOx8liioNf57DP43rod8BdGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjL6p6AhINcwbMAAAAAElFTkSuQmCC';

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  // Only during the one deliberate refusal (step 12): the browser logs every
  // non-2xx response, even one the page handles and shows in words.
  let refusalExpected = false;
  const watch = (page, who) => page.on('console', (m) => {
    if (m.type() !== 'error' || /_rsc=/.test(m.text())) return;
    if (refusalExpected && /status of 422/.test(m.text())) return;
    if (signingIn && /status of 401/.test(m.text())) return;
    errors.push(`${who}: ${m.text().slice(0, 140)}`);
  });
  const run = Date.now() % 1_000_000;
  const phone = (offset) => `0911${String((run + offset) % 1_000_000).padStart(6, '0')}`;
  // Each demo phone signs in once per run and the session is reused: the API
  // allows five sign-in codes per phone per hour (auth.otp_per_phone_per_hour).
  const sessions = new Map();
  async function sessionFor(phoneNumber) {
    if (!sessions.has(phoneNumber)) {
      const page = await (await browser.newContext()).newPage();
      watch(page, phoneNumber);
      sessions.set(phoneNumber, { page, call: await signInByCode(page, phoneNumber) });
    }
    return sessions.get(phoneNumber);
  }
  /** The demo shop's signed-in API caller, by its link name. */
  async function sellerFor(storeSlug) {
    for (const sellerPhone of ['0911000901', '0911000902', '0911000903']) {
      const { call } = await sessionFor(sellerPhone);
      const membership = (await call('GET', '/api/v1/me')).body.sellers.find((m) => m.store_slug === storeSlug);
      if (membership) return { call, sellerId: membership.seller_id };
    }
    throw new Error(`no demo seller owns ${storeSlug}`);
  }

  // 1. The super administrator signs in and lands on the first queue: problems.
  const staff = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(staff, 'staff');
  await staffSignIn(staff, '0911000900', process.env.MARKX_DEMO_STAFF_PASSWORD || 'demo-only-staff-password-1', SECRET, /\/en\/admin\/problems$/);
  const items = await menu(staff);
  expect(items.join('|') === 'Problems|Orders desk|Dispatch board|Dashboard|Seller applications|Invitations|Product proposals|Products|Catalogue setup|Listing takedowns|Pictures|Reviews|Reports|Search|Audit trail|Exports|Operations|Delivery zones|Settings|Staff accounts', `menu: ${items}`);
  await staff.getByText('Role: Super administrator').waitFor();
  console.log('1 super administrator: lands on problems; menu', items.length, 'queues; role in words');
  const asStaff = caller(staff);

  // 2. Invitations: invite a number, then withdraw it.
  const invited = phone(1);
  await staff.goto(`${BASE}/en/admin/invitations`);
  await staff.fill('input[name=phone]', invited);
  await staff.fill('input[name=note]', 'Met at Merkato, phone shop');
  await staff.getByRole('button', { name: 'Send the invitation' }).click();
  const row = staff.locator('main li', { hasText: `+251${invited.slice(1)}` });
  await row.getByText(/^Expires /).waitFor();
  await row.getByRole('button', { name: 'Withdraw' }).click();
  await row.getByText(/^Withdrawn /).waitFor();
  console.log('2 invitation sent and withdrawn:', await row.locator('p').nth(1).innerText());

  // 3. Proposals: a shop proposes two products; staff approve one, turn one down.
  const asShop = (await sessionFor('0911000901')).call;
  const sellerId = (await asShop('GET', '/api/v1/me')).body.sellers[0].seller_id;
  const phones = (await asShop('GET', '/api/v1/catalog/categories')).body.flatMap((c) => [c, ...(c.children || [])]).find((c) => c.slug === 'phones');
  const proposal = (name) => asShop('POST', `/api/v1/seller/${sellerId}/product-proposals`, {
    category_id: phones.id, model: `DEMO-${name}`, name_am: `ማሳያ ${name}`, name_en: `DEMO ${name} ${run}`,
    specs: { screen_inches: 6.5 }, variants: [{ attribute_values: { storage: '128gb', colour: 'black' } }],
  });
  for (const name of ['Keep', 'Drop']) {
    const made = await proposal(name);
    expect(made.status === 201, `proposal ${made.status} ${JSON.stringify(made.body)}`);
  }
  await staff.goto(`${BASE}/en/admin/catalog`);
  // A card by its title: once one proposal is approved, its name also appears
  // in the other card's "duplicate of" list, so text anywhere in a card is not enough.
  const card = (name) => staff.locator('main li').filter({ has: staff.locator('p.font-bold', { hasText: name }) });
  const keep = card(`DEMO Keep ${run}`);
  const drop = card(`DEMO Drop ${run}`);
  await keep.getByText('Proposed by a seller', { exact: false }).waitFor();
  await keep.getByRole('button', { name: 'Approve and publish' }).click();
  await keep.waitFor({ state: 'detached' });
  await drop.locator('input[name=note]').fill('We already list this phone under its full name.');
  await drop.getByRole('button', { name: 'Turn it down' }).click();
  await drop.waitFor({ state: 'detached' });
  const statuses = (await asStaff('GET', '/api/v1/admin/catalog/products?limit=200&lang=en')).body
    .filter((p) => p.name.endsWith(` ${run}`)).map((p) => `${p.name.split(' ')[1]}=${p.status}`).sort();
  expect(statuses.join(',') === 'Drop=archived,Keep=approved', `proposal statuses ${statuses}`);
  console.log('3 proposals decided:', statuses.join(', '));

  // 4. Takedowns: find a product's offers, take one down, see it held, lift it;
  // lifting publishes nothing (D-032), so the shop then lists it again.
  const target = (await asStaff('GET', '/api/v1/catalog/products/xiaomi-redmi-13c/offers')).body.offers[0];
  expect(target, 'a live demo offer to take down');
  await staff.goto(`${BASE}/en/admin/listings?product=xiaomi-redmi-13c`);
  // The very offer the shop relists below: the page's order need not be the API's ranking.
  const live = staff.locator('main section').first().locator('li', { hasText: target.store_name }).first();
  const store = target.store_name;
  await live.locator('input[name=reason]').fill('Reported as a counterfeit; checking the invoice.');
  await live.getByRole('button', { name: 'Take down' }).click();
  const heldRow = staff.locator('main section').nth(1).locator('li', { hasText: store });
  await heldRow.getByText('Reason: Reported as a counterfeit; checking the invoice.').waitFor();
  console.log('4 taken down:', store, '-', await heldRow.locator('p').first().innerText());
  await heldRow.locator('input[name=reason]').fill('Invoice checked: genuine stock.');
  await heldRow.getByRole('button', { name: 'Lift the takedown' }).click();
  await staff.getByText('No listing is taken down.').waitFor();
  const owner = await sellerFor(target.store_slug);
  const removed = (await owner.call('GET', `/api/v1/seller/${owner.sellerId}/offers?status=removed&lang=en`)).body.find((o) => o.id === target.id);
  expect(removed, 'the lifted offer is still removed until the shop lists it again');
  const relisted = await owner.call('POST', `/api/v1/seller/${owner.sellerId}/offers?lang=en`, {
    variant_id: removed.variant_id, condition: removed.condition, price_santim: removed.price_santim,
    quantity: Math.max(removed.on_hand, 5), warranty_months: removed.warranty_months,
    delivers_by_seller_rider: removed.delivers_by_seller_rider, delivers_by_partner_courier: removed.delivers_by_partner_courier,
    offers_shop_collection: removed.offers_shop_collection,
  });
  expect(relisted.status === 201 && relisted.body.id === target.id, `relist ${relisted.status} ${JSON.stringify(relisted.body)}`);
  const back = (await asStaff('GET', '/api/v1/catalog/products/xiaomi-redmi-13c/offers')).body.offers.some((o) => o.id === target.id);
  expect(back, 'the relisted offer is not back on the product page');
  console.log('  hold lifted; the queue is empty again; the shop relisted it and buyers see it again');

  // 5. The audit trail shows all of it, in English and in Amharic.
  await staff.goto(`${BASE}/en/admin/audit?action=offer.`);
  await staff.getByText('offer.staff_remove', { exact: false }).first().waitFor();
  await staff.getByText('offer.staff_restore', { exact: false }).first().waitFor();
  await staff.goto(`${BASE}/en/admin/audit?action=seller_invitation.`);
  await staff.getByText('seller_invitation.revoke', { exact: false }).first().waitFor();
  const entries = await staff.locator('main ol li').count();
  await staff.goto(`${BASE}/am/admin/audit?action=offer.`);
  await staff.getByRole('heading', { name: 'የኦዲት መዝገብ' }).waitFor();
  console.log('5 audit trail: takedown, lift and invitation entries found;', entries, 'invitation entries; Amharic heading shown');
  if (shots) await staff.screenshot({ path: `${shots}/admin-audit.png`, fullPage: true });

  // 6. The dispatch board: a rider order, packed by the shop, waits to leave.
  const asBuyer = (await sessionFor('0911000950')).call;
  for (const o of (await asBuyer('GET', '/api/v1/me/orders')).body) {
    for (const part of o.seller_orders) if (part.can_cancel) await asBuyer('POST', `/api/v1/me/orders/${o.id}/seller-orders/${part.id}/cancel`, {});
  }
  // Each run sells one unit, so look across the demo catalogue for stock.
  let riderOffer = null;
  for (const slug of ['xiaomi-redmi-13c', 'infinix-hot-40i', 'tecno-spark-20', 'samsung-galaxy-a16', 'apple-iphone-13']) {
    riderOffer = (await asBuyer('GET', `/api/v1/catalog/products/${slug}/offers`)).body.offers
      .find((o) => o.in_stock && o.delivers_by_seller_rider);
    if (riderOffer) break;
  }
  expect(riderOffer, 'a demo offer in stock and delivered by the shop\'s rider');
  await asBuyer('DELETE', '/api/v1/cart');
  await asBuyer('PUT', `/api/v1/cart/items/${riderOffer.id}`, { quantity: 1 });
  const address = (await asBuyer('GET', '/api/v1/me/addresses')).body[0];
  const deliveries = [{ store_slug: riderOffer.store_slug, method: 'seller_rider' }];
  const quote = await asBuyer('POST', '/api/v1/checkout/quote', { address_id: address.id, deliveries });
  expect(quote.status === 200, `quote ${quote.status} ${JSON.stringify(quote.body)}`);
  const placed = await asBuyer('POST', '/api/v1/checkout', {
    address_id: address.id, deliveries, payment_method: 'cash',
    expected_total_santim: quote.body.grand_total_santim, idempotency_key: `adminqueues${run}`,
  });
  expect(placed.status === 201, `checkout ${placed.status} ${JSON.stringify(placed.body)}`);
  const part = placed.body.seller_orders[0];
  const packer = await sellerFor(riderOffer.store_slug);
  const asPacker = packer.call;
  const packerSellerId = packer.sellerId;
  for (const step of ['confirm', 'ready']) {
    const moved = await asPacker('POST', `/api/v1/seller/${packerSellerId}/orders/${part.id}/${step}`, {});
    expect(moved.status === 200, `${step} ${moved.status} ${JSON.stringify(moved.body)}`);
  }
  await staff.goto(`${BASE}/en/admin/dispatch`);
  const waiting = staff.locator('main li', { hasText: placed.body.code });
  await waiting.getByText("The shop's rider", { exact: false }).waitFor();
  await waiting.getByRole('link', { name: 'Open in the orders desk' }).click();
  await staff.waitForURL(/\/en\/admin\/orders\?code=/);
  await staff.getByText(placed.body.code).first().waitFor();
  console.log('6 dispatch board: rider order', placed.body.code, 'from', riderOffer.store_slug, 'waits to leave; opens in the orders desk');

  // 7. The dashboard and the operations page show the API's figures.
  await staff.goto(`${BASE}/en/admin/dashboard?days=30`);
  await staff.getByRole('heading', { name: 'How the marketplace is doing' }).waitFor();
  const tiles = await staff.locator('main dl > div').count();
  const orders = await staff.locator('main dl > div', { hasText: /^Orders/ }).locator('dd').innerText();
  expect(tiles === 13, `dashboard tiles: ${tiles}`);
  await staff.goto(`${BASE}/en/admin/ops`);
  await staff.getByRole('heading', { name: 'Scheduled jobs' }).waitFor();
  const jobs = await staff.locator('main section', { hasText: 'Scheduled jobs' }).locator('li').count();
  expect(jobs > 0, 'no scheduled job listed');
  console.log('7 dashboard: 13 figures, orders in 30 days =', orders, '; operations: ', jobs, 'scheduled jobs listed');

  // 8. Reviews: the order is delivered and received; the buyer's review has a
  // phone number in it, so the API holds it for staff, who publish it.
  const sellerOrder = `/api/v1/seller/${packerSellerId}/orders/${part.id}`;
  const sent = await asPacker('POST', `${sellerOrder}/dispatch`, { rider_name: 'Demo Rider' });
  expect(sent.status === 200, `dispatch ${sent.status} ${JSON.stringify(sent.body)}`);
  const mine = (await asBuyer('GET', `/api/v1/me/orders/${placed.body.id}`)).body.seller_orders[0];
  const handed = await asPacker('POST', `${sellerOrder}/handover`, { code: mine.handover_code });
  expect(handed.status === 200, `handover ${handed.status} ${JSON.stringify(handed.body)}`);
  const received = await asBuyer('POST', `/api/v1/me/orders/${placed.body.id}/seller-orders/${part.id}/confirm-received`, {});
  expect(received.status === 200, `received ${received.status} ${JSON.stringify(received.body)}`);
  const itemId = mine.items[0].id;
  const reviewText = `Good phone, call me on 0911222333 for more (${run})`;
  // Repeated runs write many reviews from the one demo buyer; the daily limit
  // (reviews.per_buyer_per_day) is not what this step is about, so staff lift
  // it for this one review and put it back.
  const limitKey = 'reviews.per_buyer_per_day';
  const limit = (await asStaff('GET', '/api/v1/admin/settings')).body.find((x) => x.key === limitKey).value;
  expect((await asStaff('PUT', `/api/v1/admin/settings/${limitKey}`, { value: 100 })).status === 200, 'lift the daily review limit');
  const reviewed = await asBuyer('POST', `/api/v1/me/orders/${placed.body.id}/items/${itemId}/review`, { product_rating: 4, seller_rating: 5, body: reviewText });
  expect((await asStaff('PUT', `/api/v1/admin/settings/${limitKey}`, { value: limit })).status === 200, 'restore the daily review limit');
  expect(reviewed.status === 201 || reviewed.status === 200, `review ${reviewed.status} ${JSON.stringify(reviewed.body)}`);
  await staff.goto(`${BASE}/en/admin/reviews`);
  const held = staff.locator('main li', { hasText: `(${run})` });
  await held.getByText('Held: contains a phone number or a link').waitFor();
  await held.locator('input[name=reason]').fill('A shop phone number in a review is allowed here.');
  await held.getByRole('button', { name: 'Record the decision' }).click();
  await held.waitFor({ state: 'detached' });
  await staff.goto(`${BASE}/en/admin/reviews?status=published`);
  await staff.locator('main li', { hasText: `(${run})` }).getByText('Last decision: A shop phone number in a review is allowed here.').waitFor();
  console.log('8 review held for its phone number, published by staff; now under "Published"');

  // 9. Reports: the buyer reports the shop; staff dismiss it with a note.
  const reported = await asBuyer('POST', '/api/v1/reports', { target_type: 'store', store_slug: riderOffer.store_slug, reason: 'spam', note: `Too many messages (${run})` });
  expect(reported.status === 201 || reported.status === 200, `report ${reported.status} ${JSON.stringify(reported.body)}`);
  await staff.goto(`${BASE}/en/admin/reports?target_type=store`);
  const flag = staff.locator('main li', { hasText: `Too many messages (${run})` });
  await flag.getByText('A shop · Reason: Spam').waitFor();
  await flag.locator('input[name=note]').fill('No messages found from this shop.');
  await flag.getByRole('button', { name: 'Close the report' }).click();
  await flag.waitFor({ state: 'detached' });
  await staff.goto(`${BASE}/en/admin/reports?status=dismissed&target_type=store`);
  await staff.locator('main li', { hasText: `Too many messages (${run})` }).getByText(/: No messages found from this shop\.$/).waitFor();
  console.log('9 shop reported by the buyer; dismissed by staff with a note; now under "Dismissed"');

  // 10. Settings: change a limit, see it marked, find it in the audit trail, put it back.
  const key = 'search.suggestions_per_ip_per_minute';
  const before = (await asStaff('GET', '/api/v1/admin/settings')).body.find((x) => x.key === key);
  expect(before && before.may_change, `${key} is not changeable by the super administrator`);
  await staff.goto(`${BASE}/en/admin/settings`);
  const settingRow = (k) => staff.locator('main li').filter({ has: staff.locator('code', { hasText: k }) });
  await settingRow(key).locator('input[name=value]').fill(String(before.value + 1));
  await settingRow(key).getByRole('button', { name: 'Save' }).click();
  await settingRow(key).getByText('Done').waitFor();
  const changed = (await asStaff('GET', '/api/v1/admin/settings')).body.find((x) => x.key === key);
  expect(changed.value === before.value + 1, `setting is ${changed.value}`);
  await staff.goto(`${BASE}/en/admin/audit?action=setting.`);
  await staff.getByText(key, { exact: false }).first().waitFor();
  await staff.goto(`${BASE}/en/admin/settings`);
  await settingRow(key).locator('input[name=value]').fill(String(before.value));
  await settingRow(key).getByRole('button', { name: 'Save' }).click();
  await settingRow(key).getByText('Done').waitFor();
  const restored = (await asStaff('GET', '/api/v1/admin/settings')).body.find((x) => x.key === key);
  expect(restored.value === before.value, `setting not restored: ${restored.value}`);
  console.log(`10 setting ${key}: ${before.value} -> ${changed.value} -> ${restored.value}; the change is in the audit trail`);

  // 11. Staff accounts: create one through the form, sign in with the secret it
  // showed, change the role (the session ends), switch the account off.
  const newPhone = phone(3);
  await staff.goto(`${BASE}/en/admin/staff`);
  await staff.fill('input[name=name]', `Demo Support ${run}`);
  await staff.fill('input[name=phone]', newPhone);
  await staff.selectOption('select[name=role]', 'support');
  await staff.fill('input[name=password]', 'demo-only-support-password-1');
  await staff.getByRole('button', { name: 'Create the account' }).click();
  const shown = staff.getByRole('status').filter({ hasText: 'shown once' });
  await shown.waitFor();
  const newSecret = (await shown.locator('code').first().innerText()).trim();
  expect(/^[A-Z2-7]{16,}$/.test(newSecret), 'the shown secret is not a base-32 secret');
  const helper = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(helper, 'support');
  await staffSignIn(helper, newPhone, 'demo-only-support-password-1', newSecret, /\/en\/admin\/problems$/);
  const supportMenu = await menu(helper);
  expect(supportMenu.join('|') === 'Problems|Orders desk|Dashboard|Reviews|Reports|Operations', `support menu: ${supportMenu}`);
  const member = staff.locator('main li', { hasText: `Demo Support ${run}` });
  await staff.reload();
  await member.locator('select[name=role]').selectOption('finance');
  await member.getByRole('button', { name: 'Change the role' }).click();
  await member.getByText('Finance', { exact: false }).first().waitFor();
  await helper.goto(`${BASE}/en/admin/orders`);
  await helper.waitForURL(/\/en\/admin\/sign-in$/);
  await member.locator('input[name=reason]').fill('Left the support team.');
  await member.getByRole('button', { name: 'Switch off' }).click();
  await member.getByText('Switched off').waitFor();
  console.log('11 staff account created through the form; its shown secret signed it in (support menu: 6 screens);',
    'a new role ended its session; switched off');

  // 12. Exports: a file for this month downloads; an impossible period is
  // refused by the API, in words.
  await staff.goto(`${BASE}/en/admin/exports`);
  const feesRow = staff.locator('main li', { hasText: 'Fees charged on completed shop orders' });
  const [download] = await Promise.all([staff.waitForEvent('download'), feesRow.getByRole('button', { name: 'Download' }).click()]);
  const fileName = download.suggestedFilename();
  expect(/^markx-fees-\d{4}-\d{2}-01-to-\d{4}-\d{2}-\d{2}\.csv$/.test(fileName), `export file name ${fileName}`);
  const firstLine = (await (await download.createReadStream()).toArray()).map(String).join('').split('\n')[0].replace(/^\uFEFF/, '');
  await staff.goto(`${BASE}/en/admin/exports?first_day=2026-11-10&last_day=2026-11-01`);
  refusalExpected = true;
  await staff.locator('main li', { hasText: 'Every ledger entry' }).getByRole('button', { name: 'Download' }).click();
  await staff.getByText('Choose a last day on or after the first day.').waitFor();
  refusalExpected = false;
  console.log('12 export downloaded:', fileName, '(columns:', firstLine.split(',').length, '); a reversed period is refused in words');

  // 13. Pictures: upload through the form, the worker renders it, it is shown,
  // then staff take it down with a reason.
  const picturePath = join(mkdtempSync(join(tmpdir(), 'markx-e2e-')), 'demo-picture.png');
  writeFileSync(picturePath, Buffer.from(PICTURE_PNG, 'base64'));
  await staff.goto(`${BASE}/en/admin/pictures?product=xiaomi-redmi-13c`);
  const countBefore = await staff.locator('main ul > li').count();
  await staff.setInputFiles('input[name=file]', picturePath);
  await staff.getByRole('button', { name: 'Upload' }).click();
  await staff.locator('main form').filter({ has: staff.locator('input[name=file]') }).getByText('Done').waitFor();
  await staff.locator('main ul > li').nth(countBefore).waitFor();
  const newest = staff.locator('main ul > li', { hasText: 'Being prepared' }).last();
  await newest.waitFor();
  // The worker renders it (on a laptop it runs only when started; here, one
  // pass, which handles every due message however long the queue, D-082; its
  // report is kept in case the picture does not show).
  const worker = spawnSync('uv', ['run', 'python', '-m', 'markx.worker', '--once'], { cwd: new URL('../../api/', import.meta.url), encoding: 'utf8' });
  const workerReport = `exit ${worker.status}; ${`${worker.stdout}${worker.stderr}`.split('\n').filter((l) => l.includes('"level"')).map((l) => l.slice(0, 600)).join(' | ')}`;
  await staff.reload();
  const shownPicture = staff.locator('main ul > li', { hasText: 'Shown to buyers' }).last();
  if (worker.status !== 0 || !(await shownPicture.locator('img').count())) console.log('  worker pass:', workerReport);
  expect(worker.status === 0, 'the worker pass failed');
  expect(await shownPicture.locator('img').count(), 'one worker pass did not render the picture');
  const loaded = await shownPicture.locator('img').evaluate((img) => img.complete && img.naturalWidth > 0);
  expect(loaded, 'the rendered thumbnail did not load');
  await shownPicture.locator('input[name=reason]').fill('A test picture, not the real phone.');
  await shownPicture.getByRole('button', { name: 'Take the picture down' }).click();
  await staff.getByText('Taken down: A test picture, not the real phone.').last().waitFor();
  console.log('13 picture uploaded, rendered by the worker, shown with its thumbnail, taken down with a reason');

  // 14. No new page is wider than a 360px phone.
  const cookies = await staff.context().cookies();
  for (const path of ['/en/admin/invitations', '/en/admin/catalog', '/en/admin/listings?product=xiaomi-redmi-13c', '/en/admin/audit', '/am/admin/audit', '/en/admin/dispatch', '/en/admin/dashboard', '/am/admin/dashboard', '/en/admin/ops', '/en/admin/reviews?status=published', '/en/admin/reports?status=dismissed', '/am/admin/reports?status=dismissed', '/en/admin/settings', '/am/admin/settings', '/en/admin/staff', '/en/admin/exports', '/am/admin/exports', '/en/admin/pictures?product=xiaomi-redmi-13c']) {
    await noOverflow(browser, cookies, path);
  }
  console.log('14 every new admin page fits a 360px screen');

  // 15. A catalogue curator sees only its own queues, and is told so elsewhere.
  const curatorPhone = phone(2);
  const created = await asStaff('POST', '/api/v1/admin/staff', {
    phone: curatorPhone, name: 'Demo Curator', role: 'catalogue', password: 'demo-only-curator-password-1',
  });
  expect(created.status === 201, `create curator ${created.status} ${JSON.stringify(created.body)}`);
  const curator = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(curator, 'curator');
  await staffSignIn(curator, curatorPhone, 'demo-only-curator-password-1', created.body.totp_secret, /\/en\/admin\/catalog$/);
  const own = await menu(curator);
  expect(own.join('|') === 'Product proposals|Products|Catalogue setup|Listing takedowns|Pictures|Reviews|Reports|Search', `curator menu: ${own}`);
  await curator.getByText('Role: Catalogue curator').waitFor();
  await curator.goto(`${BASE}/en/admin/audit`);
  await curator.getByText('Your role may not open this page.').waitFor();
  await curator.goto(`${BASE}/en/admin/invitations`);
  await curator.getByText('Your role may not open this page.').waitFor();
  for (const path of ['settings', 'staff', 'exports', 'dashboard', 'dispatch']) {
    await curator.goto(`${BASE}/en/admin/${path}`);
    await curator.getByText('Your role may not open this page.').waitFor();
  }
  console.log('15 curator: lands on proposals; menu', own.join(', '), '; audit, invitations, settings, staff, exports, dashboard and dispatch refused in words');

  await browser.close();
  console.log('console errors:', errors.length ? errors.join(' | ') : 'none');
  if (errors.length) process.exit(1);
})().catch((error) => { console.error(error); process.exit(1); });
