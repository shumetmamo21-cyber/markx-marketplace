// The seller dashboard from the first day, in a real browser against a
// running API (8000) and web app (3000) filled by scripts/seed_demo.py (DEMO
// data):
//
//   MARKX_DEMO_TOTP_SECRET=SECRET node e2e/seller-dashboard.mjs [screenshot-folder]
//
// SECRET is the demo staff authenticator secret seed_demo.py printed. Staff
// invite a new demo phone; that person applies on /seller, uploads the four
// documents a business needs, adds a payout account, corrects the legal
// details and sends the application; staff accept the documents and approve
// the shop through the API (the admin screens have their own journey). The
// owner then edits the store settings and sees them on the public page, adds
// a manager and removes them again (and is told in words that other roles are
// not offered yet), publishes an offer from the catalogue, and reads the
// performance page. Every seller page is checked at 360 pixels in both
// languages.
//
// Each run creates one approved demo shop ("Demo Journey Phones") with a
// random phone and tax number and signs that phone in once; its offer is
// removed again at the end, so the demo shops' best offers stay as they were.
import { createHmac, randomInt } from 'node:crypto';
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SECRET = process.env.MARKX_DEMO_TOTP_SECRET;
if (!SECRET) throw new Error('set MARKX_DEMO_TOTP_SECRET to the demo staff authenticator secret');
const shots = process.argv[2];
const digits = (n) => Array.from({ length: n }, () => randomInt(10)).join('');
const PHONE = `0912${digits(6)}`;
const HELPER = `0913${digits(6)}`;
const TIN = `9${digits(9)}`;
const SLUG = `demo-shop-${digits(6)}`;
// A 120 x 90 PNG: a "photo" of each document.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAHgAAABaCAIAAAD8YgW4AAAA4UlEQVR4nO3QQRHAIADAMEDIdCIRWVOx8liioNf57DP43rod8BdGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjL6p6AhINcwbMAAAAAElFTkSuQmCC', 'base64');

// True while staff sign in: a code already used in this 30-second step is
// refused once (replay protection) and the next code is tried.
let signingIn = false;

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

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
    const r = await fetch(p, { method: m, cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf }, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, [method, path, body]);
}

/** Staff sign in; a code typed at the end of its 30 seconds is retried once. */
async function staffSignIn(page) {
  await page.goto(`${BASE}/en/admin`);
  await page.waitForURL(/\/en\/admin\/sign-in$/);
  await page.fill('input[name=phone]', '0911000900');
  await page.fill('input[name=password]', 'demo-only-staff-password-1');
  signingIn = true;
  for (let attempt = 1; ; attempt++) {
    await page.fill('input[name=totp]', totp(SECRET));
    await page.getByRole('button', { name: 'Sign in' }).click();
    const refusal = page.locator('form [role=alert]');
    const outcome = await Promise.race([
      page.waitForURL(/\/en\/admin\/(?!sign-in)/, { waitUntil: 'commit' }).then(() => 'in'),
      refusal.waitFor().then(() => 'refused'),
    ]);
    if (outcome === 'in') {
      signingIn = false;
      return caller(page);
    }
    expect(attempt < 2, `staff sign-in refused: ${await refusal.innerText()}`);
    await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 1_000);
  }
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

/** Wait for the form's own answer: a status line, or the API's refusal. */
async function answer(scope) {
  const said = scope.locator('[role=status], form [role=alert]').first();
  await said.waitFor();
  return { ok: (await said.getAttribute('role')) === 'status', text: await said.innerText() };
}

let browser;

(async () => {
  browser = await chromium.launch();
  const errors = [];
  let refusalExpected = false;
  const watch = (page, who) => page.on('console', (m) => {
    if (m.type() !== 'error' || /_rsc=|404 \(Not Found\)/.test(m.text())) return;
    if (signingIn && /401 \(Unauthorized\)/.test(m.text())) return;
    if (refusalExpected && /(409|422) \(/.test(m.text())) return;
    errors.push(`${who}: ${m.text().slice(0, 140)}`);
  });

  // 1. Staff invite a new phone.
  const staff = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  watch(staff, 'staff');
  const asStaff = await staffSignIn(staff);
  const invited = await asStaff('POST', '/api/v1/admin/sellers/invitations', { phone: PHONE });
  expect(invited.status === 201, `invite: ${invited.status} ${JSON.stringify(invited.body)}`);
  console.log('1 staff invited a new demo phone');

  // 2. The invited person applies on /seller and lands on the overview.
  const ownerContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const owner = await ownerContext.newPage();
  watch(owner, 'owner');
  const asOwner = await signInByCode(owner, PHONE);
  await owner.goto(`${BASE}/en/seller`);
  await owner.getByRole('heading', { name: 'Open a shop on MarkX' }).waitFor();
  await owner.getByLabel('Legal name, as on the licence').fill('Demo Journey Trading PLC');
  await owner.getByLabel('Shop name buyers will see').fill('Demo Journey Phones');
  await owner.getByLabel('Tax number (TIN, 10 digits)').fill(TIN);
  await owner.getByLabel('Business licence number').fill(`AA/14/2/${TIN.slice(-6)}/2019`);
  await owner.getByLabel('Shop phone').fill(PHONE);
  await owner.getByLabel('Shop address').fill('Merkato, demo street, shop 9 (demo)');
  await owner.getByLabel('Web address for your shop (optional)').fill(SLUG);
  await owner.getByRole('button', { name: 'Start my application' }).click();
  await owner.waitForURL(/\/en\/seller\/[0-9a-f-]{36}$/);
  const sellerId = owner.url().split('/').at(-1);
  const base = `/en/seller/${sellerId}`;
  await owner.getByRole('heading', { name: 'Before you can send your application' }).waitFor();
  const missing = await owner.locator('section[aria-labelledby=missing] li').allInnerTexts();
  expect(missing.length === 5, `expected four documents and a payout account missing, got ${JSON.stringify(missing)}`);
  console.log('2 applied; the overview lists what is missing:', missing.join('; '));

  // 3. The four documents a business needs.
  await owner.goto(`${BASE}${base}/documents`);
  for (const type of ['owner_id', 'business_licence', 'tin_certificate', 'shop_photo']) {
    await owner.locator('select[name=doc_type]').selectOption(type);
    await owner.getByLabel('Photo of the document').setInputFiles({ name: `${type}.png`, mimeType: 'image/png', buffer: PNG });
    await owner.getByRole('button', { name: 'Upload document' }).click();
    const said = await answer(owner);
    expect(said.ok, `upload ${type}: ${said.text}`);
    await owner.reload();
  }
  expect(await owner.locator('main li').count() === 4, 'the four documents are not listed');
  // The link opens in a new tab (without an opener): watch the whole context.
  const shown = ownerContext.waitForEvent('response', (r) => r.url().includes('/api/v1/documents/') && r.url().includes('/content?'));
  await owner.locator('main li').first().getByRole('button', { name: 'Open' }).click();
  const content = await shown;
  expect(content.status() === 200 && (await content.headerValue('content-type'))?.startsWith('image/'), `the document link answered ${content.status()}`);
  for (const tab of ownerContext.pages()) if (tab !== owner) await tab.close();
  console.log('3 four documents uploaded; one opens behind its signed link');

  // 4. The payout account.
  await owner.goto(`${BASE}${base}/payout`);
  await owner.getByLabel('Bank or wallet').fill('Demo Bank');
  await owner.getByLabel('Name on the account').fill('Demo Journey Trading PLC');
  await owner.getByLabel('Account number').fill(`1000${TIN}`);
  await owner.getByRole('button', { name: 'Save payout account' }).click();
  expect((await answer(owner)).ok, 'the payout account was refused');
  await owner.reload();
  expect((await owner.locator('main li').first().innerText()).includes(`Ending in ${TIN.slice(-4)}`), 'the account is not listed by its last four digits');
  console.log('4 payout account saved; shown by its last four digits only');

  // 5. Correct the legal details, then send the application.
  await owner.goto(`${BASE}${base}/legal`);
  await owner.getByLabel('Shop address').fill('Merkato, demo street, shop 10 (demo)');
  await owner.getByRole('button', { name: 'Save', exact: true }).click();
  expect((await answer(owner)).ok, 'the legal details were refused');
  await owner.goto(`${BASE}${base}`);
  expect(await owner.locator('section[aria-labelledby=missing]').count() === 0, 'something is still missing');
  await owner.getByRole('button', { name: 'Send my application for review' }).click();
  // Once sent, the page no longer offers the button: its header says so instead.
  await owner.locator('main header', { hasText: 'Waiting for review' }).waitFor();
  expect((await owner.locator('main header').innerText()).includes('Sent for review on'), 'the overview does not say when it was sent');
  console.log('5 legal details corrected; application sent; the overview says it waits for review');
  if (shots) await owner.screenshot({ path: `${shots}/seller-overview.png`, fullPage: true });

  // 6. Staff accept the documents and approve the shop.
  const detail = (await asStaff('GET', `/api/v1/admin/sellers/${sellerId}`)).body;
  for (const document of detail.documents) {
    const reviewed = await asStaff('POST', `/api/v1/admin/sellers/${sellerId}/documents/${document.id}/review`, { decision: 'accepted' });
    expect(reviewed.status === 200, `accept a document: ${reviewed.status}`);
  }
  const approved = await asStaff('POST', `/api/v1/admin/sellers/${sellerId}/approve`, { verification_level: 2, shop_visited: true, payout_account_name_matches: true });
  expect(approved.status === 200, `approve: ${approved.status} ${JSON.stringify(approved.body)}`);
  await owner.goto(`${BASE}${base}`);
  expect((await owner.locator('main header').innerText()).includes('Approved'), 'the overview does not say approved');
  console.log('6 staff accepted the documents and approved the shop');

  // 7. Store settings, seen on the public page.
  await owner.goto(`${BASE}${base}/store`);
  await owner.getByLabel('About the shop').fill('Demo shop made by the seller dashboard journey.');
  await owner.getByLabel('Opening hours').fill('Mon to Sat, 8:30 to 19:00');
  await owner.getByLabel('Areas you deliver to, one per line').fill('Merkato\nPiassa');
  await owner.getByRole('button', { name: 'Save', exact: true }).click();
  expect((await answer(owner)).ok, 'the store settings were refused');
  await owner.goto(`${BASE}/en/s/${SLUG}`);
  const page = await owner.locator('main').innerText();
  expect(page.includes('Mon to Sat, 8:30 to 19:00') && page.includes('Merkato, Piassa'), 'the public page does not show the new settings');
  console.log('7 store settings saved and shown on the public shop page');
  // The shop's own logo (S-03, D-106), on the public page.
  await owner.goto(`${BASE}${base}/store`);
  await owner.getByLabel('Logo (JPEG, PNG or WebP)').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG });
  await owner.getByRole('button', { name: 'Upload logo' }).click();
  await owner.getByText("Your logo is on your shop's page.").waitFor();
  await owner.goto(`${BASE}/en/s/${SLUG}`);
  const logo = owner.locator('main img[alt$=" logo"]').first();
  await logo.waitFor();
  expect(await logo.evaluate((img) => img.complete && img.naturalWidth > 0), 'the logo does not load on the public page');
  console.log('  the shop uploaded its logo; it shows on the public page');

  // 8. The team: a manager added and removed; another role refused in words.
  await owner.goto(`${BASE}${base}/team`);
  await owner.getByLabel('Phone number').fill(HELPER);
  await owner.locator('select[name=role]').selectOption('orders');
  refusalExpected = true;
  await owner.getByRole('button', { name: 'Add to the team' }).click();
  const refused = await answer(owner);
  refusalExpected = false;
  expect(!refused.ok, 'an orders role was accepted');
  console.log('8 another role is refused:', refused.text);
  await owner.locator('select[name=role]').selectOption('manager');
  await owner.getByRole('button', { name: 'Add to the team' }).click();
  expect((await answer(owner)).ok, 'the manager was refused');
  await owner.reload();
  const helperRow = owner.locator('main li', { hasText: `+251${HELPER.slice(1)}` });
  await helperRow.waitFor();
  expect((await helperRow.innerText()).includes('Manager'), 'the new member is not a manager');
  expect(await owner.locator('main li', { hasText: 'You' }).getByRole('button').count() === 0, 'the owner is offered a remove button');
  await helperRow.getByRole('button', { name: 'Remove from the team' }).click();
  await helperRow.waitFor({ state: 'detached' });
  await owner.reload();
  expect(await owner.locator('main li', { hasText: `+251${HELPER.slice(1)}` }).count() === 0, 'the manager was not removed');
  console.log('  a manager added and removed; the owner cannot be removed');

  // 9. An offer from the catalogue.
  await owner.goto(`${BASE}${base}/offers`);
  await owner.getByRole('link', { name: 'Add an offer' }).click();
  await owner.getByLabel('Product name or model').fill('tecno');
  await owner.getByRole('button', { name: 'Search' }).click();
  await owner.getByRole('link', { name: 'Sell this' }).first().click();
  await owner.waitForURL(/product=/);
  expect(await owner.getByLabel('Warn me when stock is at or below').inputValue() !== '', 'the API default for the low-stock warning is not filled in');
  await owner.getByLabel('Price in birr').fill('12350');
  await owner.getByLabel('How many you have').fill('1');
  await owner.getByRole('button', { name: 'Publish the offer' }).click();
  await owner.waitForURL(/\/offers$/);
  const listed = await owner.locator('main li').first().innerText();
  expect(/Tecno/i.test(listed), `the new offer is not on the offers screen: ${listed}`);
  console.log('9 an offer published from the catalogue; it is on the offers screen');
  // Withdrawn again, so the demo shops keep the best offers the buyer journey expects.
  for (const listing of (await asOwner('GET', `/api/v1/seller/${sellerId}/offers?lang=en`)).body ?? []) {
    const removed = await asOwner('DELETE', `/api/v1/seller/${sellerId}/offers/${listing.id}`);
    expect(removed.status === 200, `remove the journey's offer: ${removed.status}`);
  }
  console.log('  the journey\'s offer is removed again');

  // 10. Performance.
  await owner.goto(`${BASE}${base}/performance?days=7`);
  const tiles = await owner.locator('main dl > div').count();
  expect(tiles >= 15, `the performance page shows ${tiles} figures`);
  console.log(`10 performance: ${tiles} figures for 7 days; weekly:`, await owner.locator('section[aria-labelledby=weekly] p, section[aria-labelledby=weekly] li').first().innerText());

  // 11. Both languages, 360 pixels.
  const cookies = await ownerContext.cookies();
  for (const lang of ['en', 'am']) {
    for (const path of ['', '/documents', '/payout', '/legal', '/store', '/team', '/offers', '/offers/new', '/performance', '/reviews', '/customers']) {
      await noOverflow(browser, cookies, `/${lang}/seller/${sellerId}${path}`);
    }
  }
  await owner.goto(`${BASE}/am/seller/${sellerId}`);
  expect((await owner.locator('h2#screens').innerText()) === 'ለሱቅዎ የሚያስፈልገው ሁሉ', 'the Amharic overview has no screens heading');
  console.log('11 every seller page fits 360 px in both languages');

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(async (e) => {
  console.error('FAILED', e.message);
  // What every open page looked like when the step failed.
  if (shots && browser) {
    let n = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) await page.screenshot({ path: `${shots}/failure-${++n}.png`, fullPage: true }).catch(() => {});
  }
  process.exit(1);
});
