// Connecting Telegram from the account page (D-093), in a real browser
// against a running API (8000) and web app (3000):
//
//   node e2e/telegram-connection.mjs off [screenshot-folder]
//   MARKX_TELEGRAM_WEBHOOK_SECRET=... MARKX_TELEGRAM_BOT_USERNAME=... \
//     node e2e/telegram-connection.mjs on [screenshot-folder]
//
// "off": the API as configured by default. The section says connecting is
// not available yet and offers no button that would do nothing; the API
// refuses a link.
//
// "on": the API started with Telegram linking switched on, with TEST-ONLY
// values (no bot exists). This script plays Telegram: it calls the API's
// webhook with the secret, as Telegram would after the person pressed Start.
// Nothing is sent to or received from Telegram. A phone-sized person
// connects (the page turns "Connected" by itself), a second account trying
// the same Telegram account is refused, the person disconnects after a
// confirmation, in English and Amharic, and nothing is wider than 360 px.
//
// Each run signs one or two new demo phones in by code.
import { randomInt } from 'node:crypto';
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const API = process.env.MARKX_API_ORIGIN || 'http://127.0.0.1:8000';
const mode = process.argv[2];
const shots = process.argv[3];
if (mode !== 'on' && mode !== 'off') throw new Error('say "on" or "off"');
const SECRET = process.env.MARKX_TELEGRAM_WEBHOOK_SECRET;
const BOT = process.env.MARKX_TELEGRAM_BOT_USERNAME;
if (mode === 'on' && !(SECRET && BOT)) throw new Error('set MARKX_TELEGRAM_WEBHOOK_SECRET and MARKX_TELEGRAM_BOT_USERNAME to the API\'s test-only values');
const digits = (n) => Array.from({ length: n }, () => randomInt(10)).join('');
const TELEGRAM_ID = 800_000_000 + randomInt(100_000_000);
let updateId = randomInt(1_000_000_000);

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
  expect(asked.status === 200, `code for ${phone}: ${asked.status} ${JSON.stringify(asked.body)}`);
  const inbox = (await call('GET', `/api/v1/dev/sms-inbox?phone=${phone}`)).body;
  const verified = await call('POST', '/api/v1/auth/otp/verify', { phone, code: inbox.at(-1).text.match(/\b\d{6}\b/)[0] });
  expect(verified.status === 200, `sign-in ${phone}: ${verified.status}`);
  return call;
}

/** Telegram delivering "/start <payload>" from this Telegram account. */
async function telegramSends(text, { secret = SECRET, from = TELEGRAM_ID } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (secret) headers['X-Telegram-Bot-Api-Secret-Token'] = secret;
  const update = { update_id: ++updateId, message: { message_id: 1, date: Math.floor(Date.now() / 1000), from: { id: from, is_bot: false, first_name: 'Journey' }, chat: { id: from, type: 'private' }, text } };
  const r = await fetch(`${API}/api/v1/telegram/webhook`, { method: 'POST', headers, body: JSON.stringify(update) });
  return { status: r.status, body: await r.json().catch(() => null) };
}

const section = (page) => page.locator('section[aria-labelledby=telegram]');
async function statusIs(page, status, timeout = 15_000) {
  await page.locator(`section[data-telegram-status="${status}"]`).waitFor({ timeout });
}

async function fits(page, label) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide <= 0, `${label} is ${wide}px wider than the screen`);
}

/** Every control in the section is reachable by name and big enough to tap. */
async function accessible(page, label) {
  const controls = section(page).locator('button, a');
  for (let i = 0; i < await controls.count(); i++) {
    const control = controls.nth(i);
    if (!(await control.isVisible())) continue;
    const name = (await control.innerText()).trim();
    expect(name.length > 0, `${label}: a control has no name`);
    const box = await control.boundingBox();
    expect(box && box.height >= 44, `${label}: "${name}" is ${box?.height}px tall, under 44`);
  }
  expect(await section(page).locator('h2#telegram').count() === 1, `${label}: no heading`);
  expect(await section(page).locator('[role=status]').count() === 1, `${label}: no live status region`);
}

async function shot(page, name) {
  if (shots) await page.screenshot({ path: `${shots}/telegram-${name}.png`, fullPage: true });
}

const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  const page = await context.newPage();
  const call = await signInByCode(page, `0915${digits(6)}`);

  if (mode === 'off') {
    for (const [lang, words] of [['en', 'Not available yet'], ['am', 'ገና አልተከፈተም']]) {
      await page.goto(`${BASE}/${lang}/account`);
      await statusIs(page, 'unavailable');
      expect(await section(page).getByText(words, { exact: true }).isVisible(), `${lang}: "${words}" not shown`);
      expect(await section(page).locator('button, a').count() === 0, `${lang}: a control is offered while connecting is off`);
      await accessible(page, `off ${lang}`);
      await fits(page, `/${lang}/account (off)`);
      await shot(page, `off-${lang}`);
    }
    const refused = await call('POST', '/api/v1/me/telegram/link');
    expect(refused.status === 503 && refused.body.error.code === 'telegram_linking_unavailable', `link while off: ${refused.status}`);
    const webhook = await telegramSends('/start x', { secret: 'anything' });
    expect(webhook.status === 404, `the webhook while off answered ${webhook.status}`);
    console.log('off: nothing offered, link refused (503), webhook absent (404), 360 px, en + am');
  } else {
    // 1. Not connected; asking for a link that the API refuses shows why.
    await page.goto(`${BASE}/en/account`);
    await statusIs(page, 'notConnected');
    await accessible(page, 'not connected');
    await page.route('**/api/v1/me/telegram/link', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'telegram_linking_unavailable', message: 'x', request_id: 'r', details: {} } }) }));
    await section(page).getByRole('button', { name: 'Connect Telegram' }).click();
    await section(page).getByRole('alert').getByText('Connecting Telegram is not available yet.').waitFor();
    await statusIs(page, 'notConnected');
    await page.unroute('**/api/v1/me/telegram/link');
    console.log('1 not connected; a refused request is explained, nothing pretends');

    // 2. Connect: the one-time link, the steps, no Telegram id anywhere.
    await section(page).getByRole('button', { name: 'Connect Telegram' }).click();
    await statusIs(page, 'waiting');
    const open = section(page).getByRole('link', { name: 'Open Telegram' });
    const first = await open.getAttribute('href');
    expect(new RegExp(`^https://t\\.me/${BOT}\\?start=[A-Za-z0-9_-]{43}$`).test(first), `link: ${first}`);
    expect((await open.getAttribute('rel')).includes('noreferrer'), 'the link must not send the page address to Telegram');
    expect(await open.getAttribute('target') === '_blank', 'the link opens Telegram beside the page');
    for (const step of ['Tap “Open Telegram”.', 'In Telegram, press Start.']) {
      expect(await section(page).getByText(step).isVisible(), `step missing: ${step}`);
    }
    await accessible(page, 'waiting');
    await fits(page, 'waiting');
    await shot(page, 'waiting-en');
    const asked = await call('GET', '/api/v1/me/telegram');
    expect(asked.body.state === 'pending' && asked.body.link === null, 'the API never shows the link again');
    console.log('2 waiting: one-time t.me link, steps, link never shown again by the API');

    // 3. After a reload the link is gone; a new one replaces it.
    await page.reload();
    await statusIs(page, 'waiting');
    expect(await section(page).getByRole('link', { name: 'Open Telegram' }).count() === 0, 'a reload must not bring the link back');
    await section(page).getByRole('button', { name: 'Get a new link' }).click();
    await section(page).getByRole('link', { name: 'Open Telegram' }).waitFor();
    const second = await section(page).getByRole('link', { name: 'Open Telegram' }).getAttribute('href');
    expect(second !== first, 'a new link must be new');
    const stale = await telegramSends(`/start ${new URL(first).searchParams.get('start')}`);
    expect(stale.status === 200 && /not valid or has expired/.test(stale.body.text), `the replaced link: ${JSON.stringify(stale.body)}`);
    console.log('3 reload hides the link; a new link replaces it; the old one is refused');

    // 4. Telegram is not believed without its secret.
    const token = new URL(second).searchParams.get('start');
    const unsigned = await telegramSends(`/start ${token}`, { secret: null });
    const wrong = await telegramSends(`/start ${token}`, { secret: 'x'.repeat(40) });
    expect(unsigned.status === 401 && wrong.status === 401, `unsigned ${unsigned.status}, wrong secret ${wrong.status}`);
    await statusIs(page, 'waiting');
    console.log('4 webhook without or with a wrong secret: 401, nothing changes');

    // 5. Telegram confirms: the page turns Connected by itself.
    const confirmed = await telegramSends(`/start ${token}`);
    expect(confirmed.status === 200 && confirmed.body.method === 'sendMessage' && /now connected/.test(confirmed.body.text), `confirm: ${JSON.stringify(confirmed.body)}`);
    await statusIs(page, 'connected');
    await section(page).getByRole('status').getByText('Telegram is connected.').waitFor();
    expect(!(await page.content()).includes(String(TELEGRAM_ID)), 'the page must not show the Telegram id');
    await accessible(page, 'connected');
    await fits(page, 'connected');
    await shot(page, 'connected-en');
    const replay = await telegramSends(`/start ${token}`);
    expect(/not valid or has expired/.test(replay.body.text), 'a used link must not work twice');
    console.log('5 Telegram confirms; the page shows Connected without a reload; replay refused');

    // 6. Amharic.
    await page.goto(`${BASE}/am/account`);
    await statusIs(page, 'connected');
    for (const words of ['ተገናኝቷል', 'ቴሌግራምን አቋርጥ', 'የቴሌግራም መልዕክቶች']) {
      expect(await section(page).getByText(words, { exact: true }).first().isVisible(), `am: "${words}" not shown`);
    }
    await fits(page, '/am/account (connected)');
    await shot(page, 'connected-am');
    console.log('6 Amharic: connected, the disconnect button, the title');

    // 7. A second account cannot take the same Telegram account.
    const other = await browser.newContext({ viewport: { width: 360, height: 800 } });
    const otherPage = await other.newPage();
    await signInByCode(otherPage, `0915${digits(6)}`);
    await otherPage.goto(`${BASE}/en/account`);
    await section(otherPage).getByRole('button', { name: 'Connect Telegram' }).click();
    const otherLink = await section(otherPage).getByRole('link', { name: 'Open Telegram' }).getAttribute('href');
    const taken = await telegramSends(`/start ${new URL(otherLink).searchParams.get('start')}`);
    expect(/could not be connected/.test(taken.body.text), `same Telegram, second account: ${JSON.stringify(taken.body)}`);
    await statusIs(otherPage, 'failed');
    expect(await section(otherPage).getByRole('button', { name: 'Try again' }).isVisible(), 'failed offers Try again');
    await fits(otherPage, 'failed');
    await shot(otherPage, 'failed-en');
    await other.close();
    console.log('7 a second account using the same Telegram account: refused, its page says so');

    // 8. Disconnect, after a confirmation.
    await page.goto(`${BASE}/en/account`);
    await section(page).getByRole('button', { name: 'Disconnect Telegram' }).click();
    await section(page).getByRole('group').getByText('Disconnect Telegram?').waitFor();
    await section(page).getByRole('button', { name: 'Keep it connected' }).click();
    await statusIs(page, 'connected');
    await section(page).getByRole('button', { name: 'Disconnect Telegram' }).click();
    await accessible(page, 'confirming');
    await shot(page, 'confirm-en');
    await section(page).getByRole('button', { name: 'Yes, disconnect' }).click();
    await statusIs(page, 'disconnected');
    await section(page).getByRole('status').getByText('Telegram is disconnected.').waitFor();
    const after = await call('GET', '/api/v1/me/telegram');
    expect(after.body.state === 'disconnected', `after disconnect: ${after.body.state}`);
    expect((await call('GET', '/api/v1/me')).status === 200, 'still signed in after disconnecting');
    await fits(page, 'disconnected');
    await shot(page, 'disconnected-en');
    console.log('8 disconnect needs a confirmation; then Disconnected; still signed in');

    // 9. A desktop-sized screen too.
    const desk = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await desk.addCookies(await context.cookies());
    const deskPage = await desk.newPage();
    await deskPage.goto(`${BASE}/en/account`);
    await statusIs(deskPage, 'disconnected');
    await fits(deskPage, 'desktop');
    await shot(deskPage, 'desktop-en');
    await desk.close();
    console.log('9 desktop layout');
  }
  await context.close();
} finally {
  await browser.close();
}
