// The screens added after the seller dashboard, in a real browser against a
// running API (8000) and web app (3000) filled by scripts/seed_demo.py (DEMO
// data):
//
//   MARKX_DEMO_TOTP_SECRET=SECRET node e2e/setup-and-account.mjs [screenshot-folder]
//
// Staff set up a delivery zone (an area, a fee, an area switched off and on),
// the catalogue (a category, a choice attribute linked to it as the detail
// that tells versions apart, a brand, a word not allowed and removed again),
// create a product with two versions, add a third version, an alternative
// name and new text. A new demo shop is opened through the API; staff set its
// level, suspend and reinstate it and record a re-check on its page. The shop
// pins its location (shown as a map link on its page), suggests a product,
// lists a Tecno, declines the buyer's order for it, and the buyer sees the
// next-best offer from another shop. The buyer uses the account page (name,
// an address added and removed, messages marked read, a data request), the
// category page and the search suggestions, and signs out everywhere. The
// shop then closes for good. Staff tidy up: the test category is switched
// off, the zone too, and the products are archived. Every new page fits 360
// pixels in both languages.
//
// Each run signs the demo buyer and one new demo phone in by code once.
import { createHmac, randomInt } from 'node:crypto';
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SECRET = process.env.MARKX_DEMO_TOTP_SECRET;
if (!SECRET) throw new Error('set MARKX_DEMO_TOTP_SECRET to the demo staff authenticator secret');
const shots = process.argv[2];
const BUYER = '0911000950';
const digits = (n) => Array.from({ length: n }, () => randomInt(10)).join('');
const RUN = digits(6);
const SHOP_PHONE = `0914${digits(6)}`;
const TIN = `8${digits(9)}`;
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAHgAAABaCAIAAAD8YgW4AAAA4UlEQVR4nO3QQRHAIADAMEDIdCIRWVOx8liioNf57DP43rod8BdGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjL6p6AhINcwbMAAAAAElFTkSuQmCC', 'base64').toString('base64');

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

/** A multipart upload from the page (a document photo). */
function uploader(page) {
  return (path, fields, base64) => page.evaluate(async ([p, f, b]) => {
    const csrf = decodeURIComponent((document.cookie.split('; ').find((c) => c.startsWith('markx_csrf=')) || '=').split('=')[1]);
    const form = new FormData();
    for (const [k, v] of Object.entries(f)) form.append(k, v);
    form.append('file', new Blob([Uint8Array.from(atob(b), (c) => c.charCodeAt(0))], { type: 'image/png' }), 'doc.png');
    const r = await fetch(p, { method: 'POST', body: form, headers: { 'X-MarkX-Client': 'web', 'X-CSRF-Token': csrf } });
    return r.status;
  }, [path, fields, base64]);
}

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

/** The form's own answer: a status line, or the API's refusal. */
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

  // 1. Staff: a delivery zone with an area and a fee.
  const staffContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const staff = await staffContext.newPage();
  watch(staff, 'staff');
  const asStaff = await staffSignIn(staff);
  // What an interrupted earlier run left switched on is this journey's own
  // (e2e_ zones, e2e-gadgets- categories): switch it off first.
  for (const z of (await asStaff('GET', '/api/v1/admin/delivery/zones')).body) {
    if (z.code.startsWith('e2e_') && z.is_active) await asStaff('PATCH', `/api/v1/admin/delivery/zones/${z.id}`, { is_active: false });
  }
  const tree = (await asStaff('GET', '/api/v1/admin/catalog/categories?lang=en')).body;
  const everyCategory = (nodes) => nodes.flatMap((n) => [n, ...everyCategory(n.children)]);
  for (const c of everyCategory(tree)) {
    if (c.slug.startsWith('e2e-gadgets-') && c.is_active) await asStaff('PATCH', `/api/v1/admin/catalog/categories/${c.id}`, { is_active: false });
  }
  await staff.goto(`${BASE}/en/admin/delivery`);
  const zoneCode = `e2e_${RUN}`;
  const newZone = staff.locator('form', { has: staff.getByRole('button', { name: 'Add a zone' }) });
  await newZone.getByLabel('Code (small letters, numbers, _)').fill(zoneCode);
  await newZone.getByLabel('Name in Amharic').fill(`ሙከራ ${RUN}`);
  await newZone.getByLabel('Name in English').fill(`Test zone ${RUN}`);
  await newZone.getByRole('button', { name: 'Add a zone' }).click();
  expect((await answer(newZone)).ok, 'the zone was refused');
  await staff.reload();
  const zone = staff.locator('main section', { hasText: `(${zoneCode})` });
  const areaForm = zone.locator('form', { has: staff.getByRole('button', { name: 'Add an area' }) });
  await areaForm.getByLabel('Name in Amharic').fill('ሙከራ ሰፈር');
  await areaForm.getByLabel('Name in English').fill('Test area');
  await areaForm.getByRole('button', { name: 'Add an area' }).click();
  expect((await answer(areaForm)).ok, 'the area was refused');
  const riderForm = zone.locator('form', { has: staff.getByRole('button', { name: 'Save the fee' }) }).first();
  await riderForm.getByLabel('Fee in birr').fill('150');
  await riderForm.getByLabel('Promised within (hours)').fill('24');
  await riderForm.getByRole('button', { name: 'Save the fee' }).click();
  expect((await answer(riderForm)).ok, 'the fee was refused');
  await staff.reload();
  expect((await zone.innerText()).includes('ETB 150, within 24 hours'), 'the fee is not shown');
  await zone.getByRole('button', { name: 'Switch off' }).click();
  await zone.getByRole('button', { name: 'Switch on' }).waitFor();
  await zone.getByRole('button', { name: 'Switch on' }).click();
  await zone.getByRole('button', { name: 'Switch off' }).waitFor();
  console.log('1 staff: zone, area and fee set up; the area switched off and on');

  // 2. Staff: a category, a choice attribute that tells versions apart, a brand, a word not allowed.
  await staff.goto(`${BASE}/en/admin/setup`);
  const catSlug = `e2e-gadgets-${RUN}`;
  const newCat = staff.locator('form', { has: staff.getByRole('button', { name: 'Add a category' }) });
  await newCat.locator('select[name=parent_id]').selectOption({ label: 'Electronics' });
  await newCat.getByLabel('Link name (small letters, numbers, dashes)').fill(catSlug);
  await newCat.getByLabel('Name in Amharic').fill(`መሳሪያዎች ${RUN}`);
  await newCat.getByLabel('Name in English').fill(`Gadgets ${RUN}`);
  await newCat.getByRole('button', { name: 'Add a category' }).click();
  expect((await answer(newCat)).ok, 'the category was refused');
  const attrCode = `finish_${RUN}`;
  const newAttr = staff.locator('form', { has: staff.getByRole('button', { name: 'Add an attribute' }) });
  await newAttr.getByLabel('Code (small letters, numbers, _)').fill(attrCode);
  await newAttr.locator('select[name=data_type]').selectOption('option');
  await newAttr.getByLabel('Name in Amharic').fill('ቀለም');
  await newAttr.getByLabel('Name in English').fill(`Finish ${RUN}`);
  for (const [i, code, am, en] of [[0, 'matte', 'ደብዛዛ', 'Matte'], [1, 'gloss', 'አንጸባራቂ', 'Gloss']]) {
    await newAttr.getByLabel(`Option code ${i + 1}`).fill(code);
    await newAttr.getByLabel(`Label in Amharic ${i + 1}`).fill(am);
    await newAttr.getByLabel(`Label in English ${i + 1}`).fill(en);
  }
  await newAttr.getByRole('button', { name: 'Add an attribute' }).click();
  expect((await answer(newAttr)).ok, 'the attribute was refused');
  await staff.reload();
  const attrItem = staff.locator('section[aria-labelledby=attributes] li', { hasText: `(${attrCode}` });
  await attrItem.locator('summary').click();
  const optionForm = attrItem.locator('form');
  await optionForm.getByLabel('Option code').fill('satin');
  await optionForm.getByLabel('Label in Amharic').fill('ሳቲን');
  await optionForm.getByLabel('Label in English').fill('Satin');
  await optionForm.getByRole('button', { name: 'Add an option' }).click();
  expect((await answer(optionForm)).ok, 'the option was refused');
  await staff.reload();
  const link = staff.locator('form', { has: staff.getByRole('button', { name: 'Save', exact: true }) }).last();
  await link.locator('select[name=category_id]').selectOption({ label: `— Gadgets ${RUN}` });
  await link.locator('select[name=attribute_id]').selectOption({ label: `Finish ${RUN} (${attrCode})` });
  await link.getByLabel('Every product must have it').check();
  await link.getByLabel('It tells versions apart (like storage or colour)').check();
  await link.getByRole('button', { name: 'Save', exact: true }).click();
  expect((await answer(link)).ok, 'the attribute link was refused');
  const brandForm = staff.locator('form', { has: staff.getByRole('button', { name: 'Add a brand' }) });
  await brandForm.getByLabel('Brand name').fill(`Demo Brand ${RUN}`);
  await brandForm.getByRole('button', { name: 'Add a brand' }).click();
  expect((await answer(brandForm)).ok, 'the brand was refused');
  const termForm = staff.locator('form', { has: staff.getByRole('button', { name: 'Add a word' }) });
  await termForm.getByLabel('Word or phrase').fill(`forbidden-${RUN}`);
  await termForm.getByRole('button', { name: 'Add a word' }).click();
  expect((await answer(termForm)).ok, 'the word was refused');
  await staff.reload();
  const termRow = staff.locator('section[aria-labelledby=terms] li', { hasText: `forbidden-${RUN}` });
  await termRow.getByRole('button', { name: 'Remove' }).click();
  await termRow.waitFor({ state: 'detached' });
  console.log('2 staff: category, attribute with three options linked as the version detail, brand, a word added and removed');

  // 3. Staff: a product with two versions, then a third, a name buyers search for, new text.
  await staff.goto(`${BASE}/en/admin/products/new?category=${catSlug}`);
  await staff.getByLabel('Name in Amharic').fill(`ሙከራ መሳሪያ ${RUN}`);
  await staff.getByLabel('Name in English').fill(`Test Gadget ${RUN}`);
  await staff.locator('select[name=brand_id]').selectOption({ label: `Demo Brand ${RUN}` });
  await staff.locator(`select[name=variant_0_${attrCode}]`).selectOption('matte');
  await staff.getByRole('button', { name: 'Another version' }).click();
  await staff.locator(`select[name=variant_1_${attrCode}]`).selectOption('gloss');
  await staff.getByLabel('Publish at once (otherwise a draft)').check();
  await staff.getByRole('button', { name: 'Create the product' }).click();
  await staff.waitForURL(/\/en\/admin\/products\/[0-9a-f-]{36}$/);
  const productId = staff.url().split('/').at(-1);
  const versions = staff.locator('section[aria-labelledby=variants] li');
  expect((await versions.count()) === 2, 'the product does not have two versions');
  await staff.locator(`section[aria-labelledby=variants] select[name=${attrCode}]`).selectOption('satin');
  await staff.getByRole('button', { name: 'Add a version' }).click();
  await versions.nth(2).waitFor();
  const aliasForm = staff.locator('section[aria-labelledby=aliases] form').last();
  await aliasForm.getByLabel('Name').fill(`gadget${RUN}`);
  await aliasForm.getByRole('button', { name: 'Add a name' }).click();
  await staff.locator('section[aria-labelledby=aliases] li', { hasText: `gadget${RUN}` }).waitFor();
  const textForm = staff.locator('section[aria-labelledby=text] form');
  await textForm.getByLabel('Description in English').fill('A demo product made by the browser journey.');
  await textForm.getByRole('button', { name: 'Save the text' }).click();
  expect((await answer(textForm)).ok, 'the text was refused');
  const slug = (await asStaff('GET', `/api/v1/admin/catalog/products/${productId}?lang=en`)).body.slug;
  const shown = await (await staff.goto(`${BASE}/en/p/${slug}`)).status();
  expect(shown === 200, `the published product page answered ${shown}`);
  console.log('3 staff: product published with two versions, a third added, a search name and its text; its page is live');

  // 4. A new demo shop, opened through the API (the seller journey drives those screens).
  const shopContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const shop = await shopContext.newPage();
  watch(shop, 'shop');
  expect((await asStaff('POST', '/api/v1/admin/sellers/invitations', { phone: SHOP_PHONE })).status === 201, 'invite');
  const asShop = await signInByCode(shop, SHOP_PHONE);
  const applied = await asShop('POST', '/api/v1/seller/applications', {
    kind: 'business', legal_name: 'Demo Account Journey PLC', trade_name: 'Demo Pin Shop', tin: TIN,
    licence_number: `AA/14/2/${TIN.slice(-6)}/2019`, contact_phone: SHOP_PHONE, shop_address: 'Piassa, demo lane (demo)',
    store_slug: `demo-pin-${RUN}`,
  });
  expect(applied.status === 201, `apply: ${applied.status} ${JSON.stringify(applied.body)}`);
  const sellerId = applied.body.id;
  const upload = uploader(shop);
  for (const docType of ['owner_id', 'business_licence', 'tin_certificate', 'shop_photo']) {
    expect((await upload(`/api/v1/seller/${sellerId}/documents`, { doc_type: docType }, PNG)) === 201, `upload ${docType}`);
  }
  await asShop('PUT', `/api/v1/seller/${sellerId}/payout-account`, { kind: 'bank', provider_name: 'Demo Bank', account_name: 'Demo Account Journey PLC', account_number: `2000${TIN}` });
  // The location is a legal detail: it is set before the application is sent,
  // after which the legal details are locked (application_locked).
  await shop.goto(`${BASE}/en/seller/${sellerId}/legal`);
  await shop.getByLabel('Latitude').fill('9.0352');
  await shop.getByLabel('Longitude').fill('38.7524');
  await shop.getByRole('button', { name: 'Save', exact: true }).click();
  expect((await answer(shop)).ok, 'the location was refused');
  expect((await asShop('POST', `/api/v1/seller/${sellerId}/submit`)).status === 200, 'submit');
  for (const document of (await asStaff('GET', `/api/v1/admin/sellers/${sellerId}`)).body.documents) {
    await asStaff('POST', `/api/v1/admin/sellers/${sellerId}/documents/${document.id}/review`, { decision: 'accepted' });
  }
  const approved = await asStaff('POST', `/api/v1/admin/sellers/${sellerId}/approve`, { verification_level: 2, shop_visited: true, payout_account_name_matches: true });
  expect(approved.status === 200, `approve ${approved.status}`);
  console.log('4 a new demo shop is open (through the API; its location pinned on the legal details screen before it was sent)');

  // 5. Staff on the shop's page: level, suspend, reinstate, re-check.
  await staff.goto(`${BASE}/en/admin/sellers/${sellerId}`);
  const standing = staff.locator('section[aria-labelledby=standing]');
  const levelForm = standing.locator('form', { has: staff.getByRole('button', { name: 'Set the level' }) });
  await levelForm.getByLabel('Level 1: documents checked').check();
  await levelForm.getByLabel('Written reason (both sides see the outcome)').fill('Demo: lowered for the journey');
  await levelForm.getByRole('button', { name: 'Set the level' }).click();
  await standing.getByText('Verification level 1').waitFor();
  const suspendForm = standing.locator('form', { has: staff.getByRole('button', { name: 'Suspend' }) });
  await suspendForm.getByLabel('Written reason (both sides see the outcome)').fill('Demo: suspended for the journey');
  await suspendForm.getByRole('button', { name: 'Suspend' }).click();
  const reinstateForm = standing.locator('form', { has: staff.getByRole('button', { name: 'Reinstate' }) });
  await reinstateForm.waitFor();
  expect((await staff.locator('main header').innerText()).includes('Suspended'), 'the header does not say suspended');
  await reinstateForm.getByLabel('Written reason (both sides see the outcome)').fill('Demo: reinstated');
  await reinstateForm.getByRole('button', { name: 'Reinstate' }).click();
  await standing.locator('form', { has: staff.getByRole('button', { name: 'Suspend' }) }).waitFor();
  const backTo2 = standing.locator('form', { has: staff.getByRole('button', { name: 'Set the level' }) });
  await backTo2.getByLabel('Level 2: documents checked and shop visited').check();
  await backTo2.getByLabel('Written reason (both sides see the outcome)').fill('Demo: back to level 2');
  await backTo2.getByRole('button', { name: 'Set the level' }).click();
  await standing.getByText('Verification level 2').waitFor();
  const recheck = standing.locator('form', { has: staff.getByRole('button', { name: 'Record the re-check' }) });
  await recheck.getByLabel('What was checked').fill('Demo: licence seen');
  await recheck.getByRole('button', { name: 'Record the re-check' }).click();
  expect((await answer(recheck)).ok, 'the re-check was refused');
  console.log('5 staff: level lowered and raised, shop suspended and reinstated, re-check recorded');
  if (shots) await staff.screenshot({ path: `${shots}/staff-standing.png`, fullPage: true });

  // 6. The location pinned in the application: the public page links to a map.
  await shop.goto(`${BASE}/en/s/demo-pin-${RUN}`);
  const map = await shop.getByRole('link', { name: 'Directions on a map' }).getAttribute('href');
  expect(map.includes('mlat=9.0352') && map.includes('mlon=38.7524'), `map link ${map}`);
  console.log('6 the shop pinned its location; its page links to a map');

  // 7. The shop suggests a product in the new category.
  await shop.goto(`${BASE}/en/seller/${sellerId}/offers/new`);
  await shop.getByRole('link', { name: 'Not in the catalogue? Suggest it' }).click();
  await shop.locator('select[name=category]').selectOption(catSlug);
  await shop.getByRole('button', { name: 'Continue' }).click();
  await shop.getByLabel('Name in Amharic').fill(`የሱቅ ጥቆማ ${RUN}`);
  await shop.getByLabel('Name in English').fill(`Shop Suggestion ${RUN}`);
  await shop.locator(`select[name=variant_0_${attrCode}]`).selectOption('gloss');
  await shop.getByRole('button', { name: 'Send to MarkX for review' }).click();
  expect((await answer(shop)).text.includes('MarkX checks it'), 'the suggestion was not sent');
  const pending = (await asStaff('GET', '/api/v1/admin/catalog/products?status=pending_review&limit=200&lang=en')).body;
  const suggestion = pending.find((p) => p.name === `Shop Suggestion ${RUN}`);
  expect(suggestion && suggestion.proposed_by_seller_id === sellerId, 'staff do not see the suggestion');
  console.log('7 the shop suggested a product; staff see it waiting for review');

  // 8. The shop lists a Tecno; the buyer orders it; the shop declines; the buyer sees the next-best offer.
  const tecno = (await asShop('GET', '/api/v1/catalog/products/tecno-spark-20?lang=en')).body;
  const listed = await asShop('POST', `/api/v1/seller/${sellerId}/offers?lang=en`, {
    variant_id: tecno.variants[0].id, condition: 'new', price_santim: 1_299_900, quantity: 1, warranty_months: 0,
    delivers_by_seller_rider: false, delivers_by_partner_courier: false, offers_shop_collection: true, low_stock_threshold: 0,
  });
  expect(listed.status === 201, `list: ${listed.status} ${JSON.stringify(listed.body)}`);
  const buyerContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const buyer = await buyerContext.newPage();
  watch(buyer, 'buyer');
  const asBuyer = await signInByCode(buyer, BUYER);
  for (const order of (await asBuyer('GET', '/api/v1/me/orders')).body) {
    for (const part of order.seller_orders) if (part.can_cancel) await asBuyer('POST', `/api/v1/me/orders/${order.id}/seller-orders/${part.id}/cancel`, {});
  }
  await asBuyer('DELETE', '/api/v1/cart');
  await asBuyer('PUT', `/api/v1/cart/items/${listed.body.id}`, { quantity: 1 });
  const address = (await asBuyer('GET', '/api/v1/me/addresses')).body[0];
  const deliveries = [{ store_slug: `demo-pin-${RUN}`, method: 'shop_collection' }];
  const quote = await asBuyer('POST', '/api/v1/checkout/quote', { address_id: address.id, deliveries });
  const placed = await asBuyer('POST', '/api/v1/checkout', { address_id: address.id, deliveries, payment_method: 'cash', expected_total_santim: quote.body.grand_total_santim, idempotency_key: `e2e-${RUN}-${Date.now()}` });
  expect(placed.status === 201, `checkout: ${placed.status} ${JSON.stringify(placed.body)}`);
  const part = placed.body.seller_orders[0].id;
  expect((await asShop('POST', `/api/v1/seller/${sellerId}/orders/${part}/decline`, { reason: 'Demo: sold at the counter' })).status === 200, 'decline');
  await buyer.goto(`${BASE}/en/orders/${placed.body.id}`);
  const next = buyer.locator('div', { has: buyer.getByRole('heading', { name: 'Another shop has it' }) }).last();
  await next.waitFor();
  const offered = await next.innerText();
  expect(!offered.includes('Demo Pin Shop'), 'the declining shop is offered again');
  await next.getByRole('button', { name: 'Add to cart' }).first().click();
  await buyer.getByRole('status').filter({ hasText: 'Added to your cart' }).waitFor();
  console.log('8 the shop declined; the buyer sees the next-best offer from', offered.split('\n').find((l) => l.includes('Level') || /Mobile|Electronics|House/.test(l)) ?? 'another shop', 'and adds it to the cart');

  // 9. The buyer's account page.
  await buyer.goto(`${BASE}/en/account`);
  const profile = buyer.locator('section[aria-labelledby=profile]');
  await profile.getByLabel('Your name (shops see it on your orders)').fill('Demo Buyer');
  await profile.getByRole('button', { name: 'Save' }).click();
  expect((await answer(profile)).ok, 'the profile was refused');
  await buyer.getByText('Add an address').click();
  const addressForm = buyer.locator('section[aria-labelledby=addresses] form').last();
  await addressForm.locator('input[name=recipient]').fill(`Demo Office ${RUN}`);
  await addressForm.locator('input[name=phone]').fill(BUYER);
  await addressForm.locator('select[name=area]').selectOption({ index: 1 });
  await addressForm.locator('input[name=landmark]').fill('Next to the demo bank');
  await addressForm.getByRole('button').click();
  const added = buyer.locator('section[aria-labelledby=addresses] li', { hasText: `Demo Office ${RUN}` });
  await added.waitFor();
  await added.getByRole('button', { name: 'Remove this address' }).click();
  await added.waitFor({ state: 'detached' });
  const messages = buyer.locator('section[aria-labelledby=messages] li');
  expect((await messages.count()) > 0, 'no messages on the account page');
  console.log('9 account: name saved, an address added and removed; latest message:', (await messages.first().innerText()).split('\n')[0]);
  const markRead = buyer.getByRole('button', { name: 'Mark all as read' });
  if (await markRead.count()) {
    await markRead.click();
    await markRead.waitFor({ state: 'detached' });
  }
  const privacy = buyer.locator('section[aria-labelledby=privacy]');
  await privacy.getByLabel('A copy of my data').check();
  await privacy.getByRole('button', { name: 'Send request' }).click();
  expect((await answer(privacy)).text.includes('MarkX will answer'), 'the data request was not sent');
  await buyer.reload();
  expect((await buyer.locator('section[aria-labelledby=privacy] li').first().innerText()).includes('A copy of my data'), 'the request is not listed');
  console.log('  messages marked read; a data request sent and listed');
  if (shots) await buyer.screenshot({ path: `${shots}/account.png`, fullPage: true });

  // 10. The category page and the search suggestions.
  await buyer.goto(`${BASE}/en/c/phones`);
  expect((await buyer.locator('main a[href^="/en/p/"]').count()) > 0, 'the category page shows no products');
  await buyer.getByRole('search').getByLabel('Search products').fill('tec');
  const suggestion0 = buyer.locator('#q-suggestions a').first();
  await suggestion0.waitFor();
  expect((await suggestion0.innerText()).includes('Tecno'), 'no Tecno suggestion');
  await suggestion0.click();
  await buyer.waitForURL(/\/en\/p\/tecno-spark-20/);
  console.log('10 the category page lists products; typing "tec" suggests the Tecno and opens it');

  // 11. Every new page at 360 pixels, in both languages, while everyone is still signed in.
  const buyerCookies = await buyerContext.cookies();
  const shopCookies = await shopContext.cookies();
  const staffCookies = await staffContext.cookies();
  for (const lang of ['en', 'am']) {
    for (const path of [`/${lang}/account`, `/${lang}/orders/${placed.body.id}`, `/${lang}/c/phones`, `/${lang}/c/${catSlug}`]) await noOverflow(browser, buyerCookies, path);
    for (const path of [`/${lang}/seller/${sellerId}`, `/${lang}/seller/${sellerId}/legal`, `/${lang}/seller/${sellerId}/offers/propose?category=${catSlug}`, `/${lang}/s/demo-pin-${RUN}`]) await noOverflow(browser, shopCookies, path);
    for (const path of [`/${lang}/admin/delivery`, `/${lang}/admin/setup`, `/${lang}/admin/products`, `/${lang}/admin/products/${productId}`, `/${lang}/admin/products/new?category=${catSlug}`, `/${lang}/admin/sellers/${sellerId}`]) await noOverflow(browser, staffCookies, path);
  }
  console.log('11 every new page fits 360 px in both languages');

  // 12. The shop closes for good; the buyer signs out everywhere.
  await asShop('DELETE', `/api/v1/seller/${sellerId}/offers/${listed.body.id}`);
  await shop.goto(`${BASE}/en/seller/${sellerId}`);
  await shop.getByText('Close the shop', { exact: true }).click();
  await shop.getByLabel('I understand this cannot be undone').check();
  await shop.getByRole('button', { name: 'Close the shop for good' }).click();
  await shop.waitForURL(`${BASE}/en`);
  const gone = await (await shop.goto(`${BASE}/en/s/demo-pin-${RUN}`)).status();
  expect(gone === 404, `the closed shop's page answered ${gone}`);
  await buyer.goto(`${BASE}/en/account`);
  await buyer.getByRole('button', { name: 'Sign out on every device' }).click();
  await buyer.waitForURL(`${BASE}/en`);
  expect((await buyerContext.request.get(`${BASE}/api/v1/me`)).status() === 401, 'the buyer is still signed in');
  console.log('12 the shop closed for good (its page is gone); the buyer signed out everywhere');

  // 13. Staff tidy the demo data: the test category and zone off, the products archived.
  const categories = (await asStaff('GET', '/api/v1/admin/catalog/categories?lang=en')).body;
  const flat = (nodes) => nodes.flatMap((n) => [n, ...flat(n.children)]);
  const testCategory = flat(categories).find((c) => c.slug === catSlug);
  expect((await asStaff('PATCH', `/api/v1/admin/catalog/categories/${testCategory.id}`, { is_active: false })).status === 200, 'switch the category off');
  const testZone = (await asStaff('GET', '/api/v1/admin/delivery/zones')).body.find((z) => z.code === zoneCode);
  expect((await asStaff('PATCH', `/api/v1/admin/delivery/zones/${testZone.id}`, { is_active: false })).status === 200, 'switch the zone off');
  for (const id of [productId, suggestion.id]) {
    const archived = await asStaff('POST', `/api/v1/admin/catalog/products/${id}/archive`, { note: 'Demo product from the browser journey' });
    expect(archived.status === 200, `archive ${archived.status} ${JSON.stringify(archived.body)}`);
  }
  console.log('13 demo data tidied: category and zone switched off, both products archived');

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(async (e) => {
  console.error('FAILED', e.message);
  if (shots && browser) {
    let n = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) await page.screenshot({ path: `${shots}/failure-${++n}.png`, fullPage: true }).catch(() => {});
  }
  process.exit(1);
});
