// The resend cooldown on the sign-in page (D-089), end to end against the
// real API and its fake SMS sender: no SMS leaves the machine.
//
//   node e2e/sign-in-cooldown.mjs
//
// The API must run with auth.otp_resend_cooldown_seconds above zero (60 by
// default; the journeys workflow sets it back to 60 for this step). It
// shows: a first code is sent; asking again at once is refused with the
// number of seconds left, in English and in Amharic; nothing more reaches
// the development inbox.
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
// A fresh number each run, so earlier runs' codes do not count.
const PHONE = `0911${String(Math.floor(Math.random() * 1e6)).padStart(6, '0')}`;

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function inbox(page) {
  return page.evaluate(async (p) => (await fetch(`/api/v1/dev/sms-inbox?phone=${p}`)).json(), PHONE);
}

async function askTwice(page, lang) {
  await page.goto(`${BASE}/${lang}/sign-in`);
  await page.fill('input[type=tel]', PHONE);
  await page.click('form:has(input[type=tel]) button[type=submit]');
  await page.waitForSelector('input[name=code]');
  await page.click('form:has(input[name=code]) button[type=button]'); // "Use another number": back to the phone step
  await page.click('form:has(input[type=tel]) button[type=submit]');
  const alert = page.locator('p[role=alert]');
  await alert.waitFor();
  return (await alert.textContent()) ?? '';
}

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 360, height: 800 } })).newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));

  const english = await askTwice(page, 'en');
  const seconds = Number(/in (\d+) seconds/.exec(english)?.[1]);
  expect(seconds > 0 && seconds <= 60, `English message with the wait: ${english}`);
  expect((await inbox(page)).length === 1, 'one code sent, the second refused');

  // The same number in Amharic, still inside the minute: the first request is
  // refused too, so the code step never appears; ask on the phone step only.
  await page.goto(`${BASE}/am/sign-in`);
  await page.fill('input[type=tel]', PHONE);
  await page.click('form:has(input[type=tel]) button[type=submit]');
  const amharic = (await page.locator('p[role=alert]').textContent()) ?? '';
  expect(/ከ\d+ ሰከንድ/.test(amharic), `Amharic message with the wait: ${amharic}`);
  expect((await inbox(page)).length === 1, 'still one code');

  expect(errors.length === 0, `page errors: ${errors.join('; ')}`);
  await browser.close();
  console.log(`sign-in cooldown: refused with ${seconds} s left, in English and Amharic`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
