// The Turnstile widget on the sign-in page (D-085), in a real browser, with
// Cloudflare replaced by a stand-in: every request to challenges.cloudflare.com
// is answered here, so nothing reaches Cloudflare and no key is needed.
//
//   node e2e/turnstile-widget.mjs
//
// The web app (on the site's own origin, or the API's anti-forgery check
// refuses the request) must be started with MARKX_TURNSTILE_SITE_KEY set (any value,
// e.g. "test-only-site-key"); the API may use its development check. It shows:
// sending is refused until the check is solved; the token reaches the API as
// bot_token with the sign_in action; a fresh token is used for every attempt;
// the page's security policy lets the widget's script and frame load.
import { createRequire } from 'node:module';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.MARKX_WEB_ORIGIN || 'http://localhost:3000';
const SITE_KEY = process.env.MARKX_TURNSTILE_SITE_KEY || 'test-only-site-key';
// A fresh number each run: the API allows five codes per number an hour.
const PHONE = `0911${String(Math.floor(Math.random() * 1e6)).padStart(6, '0')}`;

const FAKE_API = `
  (() => {
    let issued = 0;
    const state = (window.__turnstile = { renders: 0, resets: 0, removes: 0, options: null });
    const solve = () => setTimeout(() => state.options.callback('test-only-token-' + ++issued), 1500);
    window.turnstile = {
      render(element, options) {
        state.renders++;
        state.options = options;
        const frame = document.createElement('iframe');
        frame.src = 'https://challenges.cloudflare.com/cdn-cgi/challenge-platform/stand-in';
        frame.title = 'Turnstile stand-in';
        element.appendChild(frame);
        solve();
        return 'widget-' + state.renders;
      },
      reset() { state.resets++; solve(); },
      remove() { state.removes++; },
    };
  })();
`;

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  let toCloudflare = 0;
  await context.route('https://challenges.cloudflare.com/**', (route) => {
    toCloudflare++;
    const url = route.request().url();
    if (url.includes('/turnstile/v0/api.js')) {
      return route.fulfill({ contentType: 'text/javascript', body: FAKE_API });
    }
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><p>stand-in</p>' });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error' && !/_rsc=/.test(m.text())) errors.push(m.text().slice(0, 160)); });
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 160)));
  const sent = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/v1/auth/otp/request')) sent.push(r.postDataJSON()); });

  await page.goto(`${BASE}/en/sign-in`);
  await page.locator('iframe[title="Turnstile stand-in"]').waitFor();
  const options = await page.evaluate(() => ({ sitekey: window.__turnstile.options.sitekey, action: window.__turnstile.options.action }));
  expect(options.sitekey === SITE_KEY, `the widget got site key ${options.sitekey}`);
  expect(options.action === 'sign_in', `the widget's action is ${options.action}`);
  console.log('1 the widget loads under the page\'s security policy, with the site key and the sign_in action');

  // Before the check is solved, nothing is sent.
  await page.fill('input[type=tel]', PHONE);
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('Please complete the check above').waitFor();
  expect(sent.length === 0, 'a code was requested before the check was solved');
  console.log('2 before the check is solved, sending is refused in words and nothing is sent');

  // Solved: the token goes to the API with the phone number.
  await page.waitForFunction(() => window.__turnstile.renders === 1);
  await page.waitForTimeout(1700);
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('We sent a code').waitFor();
  expect(sent.length === 1 && sent[0].bot_token === 'test-only-token-1', `sent ${JSON.stringify(sent)}`);
  console.log('3 solved: the API received bot_token', sent[0].bot_token);

  // Back to the phone step: a new widget, a new token; the old one is never reused.
  await page.getByRole('button', { name: 'Use another number' }).click();
  await page.locator('iframe[title="Turnstile stand-in"]').waitFor();
  await page.waitForTimeout(1700);
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('We sent a code').waitFor();
  expect(sent.length === 2 && sent[1].bot_token && sent[1].bot_token !== sent[0].bot_token, `sent ${JSON.stringify(sent)}`);
  const state = await page.evaluate(() => window.__turnstile);
  console.log(`4 a second attempt used a fresh token (${sent[1].bot_token}); renders ${state.renders}, resets ${state.resets}`);

  // Refused by the API (the development check refuses the token "bot"): the
  // refusal is shown in words, the widget is reset, and a fresh token works.
  await page.getByRole('button', { name: 'Use another number' }).click();
  await page.locator('iframe[title="Turnstile stand-in"]').waitFor();
  await page.waitForTimeout(1700);
  await page.evaluate(() => window.__turnstile.options.callback('bot'));
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('We could not confirm you are a person').waitFor();
  expect(sent.at(-1).bot_token === 'bot', 'the refused token was not the one sent');
  const resets = await page.evaluate(() => window.__turnstile.resets);
  expect(resets >= 1, 'the widget was not reset after a refusal');
  await page.waitForTimeout(1700);
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.getByText('We sent a code').waitFor();
  expect(sent.at(-1).bot_token.startsWith('test-only-token-'), `sent ${JSON.stringify(sent.at(-1))}`);
  console.log(`5 a refused token is reported in words, the widget is reset (${resets}), and a fresh token works`);

  expect(toCloudflare >= 2, 'the script and the frame were not requested');
  console.log('  requests to challenges.cloudflare.com, all answered by the stand-in:', toCloudflare);
  await browser.close();
  // Step 5's refusal is the one 403 the browser is expected to log.
  const refusal = errors.filter((e) => e.includes('status of 403'));
  expect(refusal.length === 1, `expected one 403 (step 5), saw ${refusal.length}`);
  errors.splice(0, errors.length, ...errors.filter((e) => !e.includes('status of 403')));
  console.log(errors.length ? `console errors: ${errors.join(' | ')}` : 'console errors: none');
  if (errors.length) process.exit(1);
})().catch((error) => {
  console.error('FAILED', error.message);
  process.exit(1);
});
