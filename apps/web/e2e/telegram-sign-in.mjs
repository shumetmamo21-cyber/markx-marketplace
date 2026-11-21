// Signing in with Telegram and placing an order (D-101, decision SI-1), in a
// real browser against a running API (8000) and web app (3000) filled by
// scripts/seed_demo.py (DEMO data):
//
//   MARKX_TELEGRAM_WEBHOOK_SECRET=... MARKX_TELEGRAM_BOT_USERNAME=... \
//     node e2e/telegram-sign-in.mjs [screenshot-folder]
//
// The API is started as a server where everyone signs in with Telegram has
// it: SMS switched off (MARKX_SMS_PROVIDER=off) and the bot configured with
// TEST-ONLY values (no bot exists). This script plays Telegram, as
// telegram-connection.mjs does: it calls the API's webhook with the secret,
// as Telegram would after the person pressed Start and then "Share my phone
// number". Nothing is sent to or received from Telegram.
//
// A new person, phone-sized: the page offers Telegram only (no SMS form);
// they tap "Sign in with Telegram", open the link, the bot asks for their
// number with Telegram's own button, they share it, and the page signs them
// in by itself. They then add the Tecno to the cart, add an address and
// place an order. Then a person whose Telegram has a foreign number is
// refused in words, in English and Amharic. axe checks each page.
import { randomInt } from 'node:crypto';
import { createRequire } from 'node:module';

import { checkAccessibility } from './a11y.mjs';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const API = process.env.MARKX_API_ORIGIN || 'http://127.0.0.1:8000';
const SECRET = process.env.MARKX_TELEGRAM_WEBHOOK_SECRET;
const BOT = process.env.MARKX_TELEGRAM_BOT_USERNAME;
const shots = process.argv[2];
if (!(SECRET && BOT)) throw new Error("set MARKX_TELEGRAM_WEBHOOK_SECRET and MARKX_TELEGRAM_BOT_USERNAME to the API's test-only values");
const digits = (n) => Array.from({ length: n }, () => randomInt(10)).join('');
let updateId = randomInt(1_000_000_000);

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

/** Telegram delivering one message from this Telegram account to the bot. */
async function telegramSends(from, message) {
  const update = { update_id: ++updateId, message: { message_id: 1, date: Math.floor(Date.now() / 1000), from: { id: from, is_bot: false, first_name: 'Journey' }, chat: { id: from, type: 'private' }, ...message } };
  const r = await fetch(`${API}/api/v1/telegram/webhook`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': SECRET }, body: JSON.stringify(update) });
  expect(r.status === 200, `webhook answered ${r.status}`);
  return r.json();
}

async function fits(page, label) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide <= 0, `${label} is ${wide}px wider than the screen`);
}

async function shot(page, name) {
  if (shots) await page.screenshot({ path: `${shots}/telegram-sign-in-${name}.png`, fullPage: true });
}

/** The person taps the button and opens Telegram: returns the start payload. */
async function startAndOpen(page, label, telegramId) {
  await page.getByRole('button', { name: label }).click();
  const open = page.locator('section[data-telegram-sign-in=waiting] a');
  await open.waitFor();
  const href = await open.getAttribute('href');
  const match = new RegExp(`^https://t\\.me/${BOT}\\?start=(si-[A-Za-z0-9_-]{43})$`).exec(href);
  expect(match, `link: ${href}`);
  expect((await open.getAttribute('rel')).includes('noreferrer'), 'the link must not send the page address to Telegram');
  const reply = await telegramSends(telegramId, { text: `/start ${match[1]}` });
  expect(reply.reply_markup?.keyboard?.[0]?.[0]?.request_contact === true, `the bot did not offer the share-my-number button: ${JSON.stringify(reply)}`);
  return reply;
}

const browser = await chromium.launch();
const errors = [];
try {
  // 1. A new person, on a phone. Telegram only: SMS is off on this server.
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error' && !/_rsc=|404 \(Not Found\)/.test(m.text())) errors.push(m.text().slice(0, 120)); });
  const methods = await (await fetch(`${API}/api/v1/auth/methods`)).json();
  expect(methods.telegram === true && methods.sms === false && methods.staff_phone_password === false, `methods: ${JSON.stringify(methods)}`);
  await page.goto(`${BASE}/en/sign-in?next=/en/cart`);
  await page.getByRole('button', { name: 'Sign in with Telegram' }).waitFor();
  expect(await page.locator('input[type=tel]').count() === 0, 'an SMS form is offered while SMS is off');
  await checkAccessibility(page, 'sign-in, Telegram only (en)');
  await fits(page, '/en/sign-in');
  await shot(page, 'start-en');
  console.log('1 sign-in page: Telegram only, no SMS form, 360 px');

  // 2. Open Telegram; the bot asks for the number with Telegram's button.
  const telegramId = 800_000_000 + randomInt(100_000_000);
  const phone = `2519${digits(8)}`;
  await startAndOpen(page, 'Sign in with Telegram', telegramId);
  for (const step of ['Tap “Open Telegram”.', 'In Telegram, press Start.']) {
    expect(await page.getByText(step).isVisible(), `step missing: ${step}`);
  }
  await page.getByText('Telegram is open. Share your phone number there').waitFor({ timeout: 15_000 });
  await checkAccessibility(page, 'sign-in, waiting for Telegram (en)');
  await shot(page, 'waiting-en');
  console.log('2 Telegram opened; the page says to share the number');

  // 3. They share their own number; the page signs them in by itself.
  const shared = await telegramSends(telegramId, { contact: { phone_number: phone, first_name: 'Journey', user_id: telegramId } });
  expect(/signed in/.test(shared.text) && shared.reply_markup?.remove_keyboard === true, `bot: ${JSON.stringify(shared)}`);
  await page.waitForURL((url) => url.pathname === '/en/cart', { timeout: 20_000 });
  const me = await page.evaluate(async () => (await fetch('/api/v1/me')).json());
  expect(me.phone === `+${phone}` && me.session_kind === 'customer', `me: ${JSON.stringify(me)}`);
  console.log('3 signed in by Telegram, phone confirmed:', me.phone.slice(0, 5) + '••••' + me.phone.slice(-4));

  // 4. Add the Tecno, add an address, place the order.
  await page.goto(`${BASE}/en/p/tecno-spark-20?zone=bole`);
  await page.getByRole('button', { name: 'Add to cart' }).first().click();
  await page.getByText('Added to your cart').waitFor();
  await page.goto(`${BASE}/en/cart`);
  await page.getByRole('link', { name: 'Continue to checkout' }).click();
  await page.waitForURL(/\/en\/checkout$/);
  // A new person has no saved address: the form is open already.
  await page.locator('input[name=recipient]').waitFor();
  await page.fill('input[name=recipient]', 'Journey Buyer');
  await page.fill('input[name=phone]', `0${phone.slice(3)}`);
  await page.selectOption('select[name=area]', { label: 'Bole Medhanialem' });
  await page.fill('input[name=landmark]', 'Behind the Medhanialem church gate');
  await page.getByRole('button', { name: 'Save address' }).click();
  await page.getByRole('button', { name: 'Review' }).click();
  await page.getByText('Grand total').waitFor();
  await checkAccessibility(page, 'checkout review (en)');
  await page.getByRole('button', { name: 'Place order' }).click();
  await page.waitForURL(/\/en\/orders\/[0-9a-f-]{36}$/, { timeout: 20_000 });
  const status = await page.locator('section span.rounded-full').first().innerText();
  await shot(page, 'order-en');
  console.log('4 order placed after a Telegram sign-in; status:', status);

  // 5. Someone whose Telegram has a foreign number is refused, in words.
  for (const [lang, button, words] of [
    ['en', 'Sign in with Telegram', 'MarkX needs an Ethiopian mobile number'],
    ['am', 'በቴሌግራም ግባ', 'ማርክኤክስ የኢትዮጵያ ሞባይል ቁጥር'],
  ]) {
    const other = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
    await other.goto(`${BASE}/${lang}/sign-in`);
    const foreigner = 900_000_000 + randomInt(90_000_000);
    await startAndOpen(other, button, foreigner);
    await telegramSends(foreigner, { contact: { phone_number: '14155550100', first_name: 'Visitor', user_id: foreigner } });
    await other.getByRole('alert').getByText(words).waitFor({ timeout: 15_000 });
    expect(new URL(other.url()).pathname === `/${lang}/sign-in`, 'a refused person must stay signed out');
    expect((await (await other.request.get(`${BASE}/api/v1/me`)).status()) === 401, 'refused, yet signed in');
    await checkAccessibility(other, `sign-in, refused (${lang})`);
    await fits(other, `/${lang}/sign-in refused`);
    await shot(other, `refused-${lang}`);
    await other.context().close();
  }
  console.log('5 a foreign number is refused in English and Amharic; still signed out');

  // 6. The staff page asks for Telegram too; no way around it with SMS off.
  const staff = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  await staff.goto(`${BASE}/en/admin/sign-in`);
  await staff.getByRole('button', { name: 'Sign in with Telegram' }).waitFor();
  expect(await staff.locator('input[type=tel]').count() === 0, 'the staff page offers phone and password while SMS is off');
  await checkAccessibility(staff, 'staff sign-in, Telegram first (en)');
  console.log('6 staff sign-in page: Telegram first, no phone-and-password form');

  console.log('console errors:', errors.length ? errors : 'none');
  if (errors.length) process.exitCode = 1;
} finally {
  await browser.close();
}
