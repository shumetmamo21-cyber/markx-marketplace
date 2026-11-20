// The automatic accessibility check of the browser journeys (D-100): axe-core
// (a development dependency, pinned in package-lock.json) runs in the page
// against the WCAG 2.1 A and AA rules. Any violation fails the journey, with
// the rule, how serious it is and the element, so it can be fixed.
//
//   import { checkAccessibility } from './a11y.mjs';
//   await checkAccessibility(page, 'cart (en)');
import { createRequire } from 'node:module';

const AXE = createRequire(import.meta.url).resolve('axe-core/axe.min.js');
const RULES = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

export async function checkAccessibility(page, label) {
  // The site's CSP allows inline scripts (D-084), so axe can be added as one.
  if (!(await page.evaluate(() => 'axe' in window))) await page.addScriptTag({ path: AXE });
  const { violations } = await page.evaluate((tags) => window.axe.run(document, { runOnly: { type: 'tag', values: tags } }), RULES);
  if (violations.length) {
    const found = violations.map((v) => `${v.id} [${v.impact}] x${v.nodes.length}: ${v.help} (${v.nodes[0].target.join(' ')})`);
    throw new Error(`accessibility, ${label}:\n  ${found.join('\n  ')}`);
  }
  console.log(`  accessibility (axe, WCAG 2.1 A and AA): ${label}: no violations`);
}
