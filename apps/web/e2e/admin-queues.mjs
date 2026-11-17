// The admin queues in a real browser (D-070), against a running API (8000) and
// web app (3000) filled by scripts/seed_demo.py (DEMO data).
//
//   MARKX_DEMO_TOTP_SECRET=SECRET node e2e/admin-queues.mjs [screenshot-folder]
//
// SECRET is the demo staff authenticator secret seed_demo.py printed; the
// script computes the current code itself. A super administrator invites and
// withdraws, approves and turns down proposals, takes a listing down and lifts
// it, and reads it all in the audit trail, in English and Amharic. Then a
// catalogue curator is created and must see only its own queues.
import { createHmac } from 'node:crypto';
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

async function staffSignIn(page, phone, password, secret, landing) {
  await page.goto(`${BASE}/en/admin`);
  await page.waitForURL(/\/en\/admin\/sign-in$/);
  await page.fill('input[name=phone]', phone);
  await page.fill('input[name=password]', password);
  await page.fill('input[name=totp]', totp(secret));
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(landing);
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

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const watch = (page, who) => page.on('console', (m) => {
    if (m.type() === 'error' && !/_rsc=/.test(m.text())) errors.push(`${who}: ${m.text().slice(0, 140)}`);
  });
  const run = Date.now() % 1_000_000;
  const phone = (offset) => `0911${String((run + offset) % 1_000_000).padStart(6, '0')}`;

  // 1. The super administrator signs in and lands on the first queue: problems.
  const staff = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(staff, 'staff');
  await staffSignIn(staff, '0911000900', process.env.MARKX_DEMO_STAFF_PASSWORD || 'demo-only-staff-password-1', SECRET, /\/en\/admin\/problems$/);
  const items = await menu(staff);
  expect(items.join('|') === 'Problems|Orders desk|Seller applications|Invitations|Product proposals|Listing takedowns|Search|Audit trail', `menu: ${items}`);
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
  const shop = await (await browser.newContext()).newPage();
  watch(shop, 'shop');
  await shop.goto(`${BASE}/en/sign-in`);
  const asShop = caller(shop);
  await asShop('POST', '/api/v1/auth/otp/request', { phone: '0911000901', language: 'en' });
  const inbox = (await asShop('GET', '/api/v1/dev/sms-inbox?phone=0911000901')).body;
  const verified = await asShop('POST', '/api/v1/auth/otp/verify', { phone: '0911000901', code: inbox.at(-1).text.match(/\b\d{6}\b/)[0] });
  expect(verified.status === 200, `shop sign-in ${verified.status}`);
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

  // 4. Takedowns: find a product's offers, take one down, see it held, lift it.
  await staff.goto(`${BASE}/en/admin/listings?product=xiaomi-redmi-13c`);
  const live = staff.locator('main section').first().locator('li').first();
  const store = (await live.locator('p').first().innerText()).split(' · ')[0];
  await live.locator('input[name=reason]').fill('Reported as a counterfeit; checking the invoice.');
  await live.getByRole('button', { name: 'Take down' }).click();
  const heldRow = staff.locator('main section').nth(1).locator('li', { hasText: store });
  await heldRow.getByText('Reason: Reported as a counterfeit; checking the invoice.').waitFor();
  console.log('4 taken down:', store, '-', await heldRow.locator('p').first().innerText());
  await heldRow.locator('input[name=reason]').fill('Invoice checked: genuine stock.');
  await heldRow.getByRole('button', { name: 'Lift the takedown' }).click();
  await staff.getByText('No listing is taken down.').waitFor();
  console.log('  hold lifted; the queue is empty again');

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

  // 6. No new page is wider than a 360px phone.
  const cookies = await staff.context().cookies();
  for (const path of ['/en/admin/invitations', '/en/admin/catalog', '/en/admin/listings?product=xiaomi-redmi-13c', '/en/admin/audit', '/am/admin/audit']) {
    await noOverflow(browser, cookies, path);
  }
  console.log('6 the four new pages fit a 360px screen');

  // 7. A catalogue curator sees only its own queues, and is told so elsewhere.
  const curatorPhone = phone(2);
  const created = await asStaff('POST', '/api/v1/admin/staff', {
    phone: curatorPhone, name: 'Demo Curator', role: 'catalogue', password: 'demo-only-curator-password-1',
  });
  expect(created.status === 201, `create curator ${created.status} ${JSON.stringify(created.body)}`);
  const curator = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(curator, 'curator');
  await staffSignIn(curator, curatorPhone, 'demo-only-curator-password-1', created.body.totp_secret, /\/en\/admin\/catalog$/);
  const own = await menu(curator);
  expect(own.join('|') === 'Product proposals|Listing takedowns|Search', `curator menu: ${own}`);
  await curator.getByText('Role: Catalogue curator').waitFor();
  await curator.goto(`${BASE}/en/admin/audit`);
  await curator.getByText('Your role may not open this page.').waitFor();
  await curator.goto(`${BASE}/en/admin/invitations`);
  await curator.getByText('Your role may not open this page.').waitFor();
  console.log('7 curator: lands on proposals; menu', own.join(', '), '; audit and invitations refused in words');

  await browser.close();
  console.log('console errors:', errors.length ? errors.join(' | ') : 'none');
  if (errors.length) process.exit(1);
})().catch((error) => { console.error(error); process.exit(1); });
