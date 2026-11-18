// The npm dependency audit for CI (blueprint Q pipeline; D-084).
//
//   node .github/scripts/npm-audit-gate.mjs apps/web
//
// 1. Production dependencies: any high or critical advisory fails.
// 2. All dependencies, development ones included: a high or critical
//    advisory fails unless .github/security/npm-audit-allowlist.json lists
//    that exact advisory with a review that has not expired. An expired
//    entry fails too, so nothing is tolerated forever.
// Moderate and low advisories are printed, not failed on.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const project = resolve(process.argv[2] ?? '.');
const allowlistPath = join(dirname(fileURLToPath(import.meta.url)), '..', 'security', 'npm-audit-allowlist.json');
const allow = new Map(JSON.parse(readFileSync(allowlistPath, 'utf8')).advisories.map((a) => [a.id, a]));
const today = new Date().toISOString().slice(0, 10);
const SERIOUS = new Set(['high', 'critical']);

function audit(extra) {
  let out;
  try {
    out = execFileSync('npm', ['audit', '--json', ...extra], { cwd: project, encoding: 'utf8', maxBuffer: 64 << 20 });
  } catch (error) {
    out = error.stdout; // npm audit exits 1 when it finds anything
  }
  const report = JSON.parse(out);
  if (report.error) throw new Error(`npm audit failed: ${JSON.stringify(report.error)}`);
  // Each advisory once, keyed by its GHSA id, with the packages it reaches.
  const found = new Map();
  for (const vuln of Object.values(report.vulnerabilities ?? {})) {
    for (const via of vuln.via) {
      if (typeof via !== 'object') continue;
      const id = via.url?.split('/').pop() ?? String(via.source);
      const entry = found.get(id) ?? { id, title: via.title, severity: via.severity, package: via.name, url: via.url, reaches: new Set() };
      for (const node of vuln.nodes ?? []) entry.reaches.add(node);
      found.set(id, entry);
    }
  }
  return [...found.values()];
}

const failures = [];
const show = (a) => `${a.severity.padEnd(8)} ${a.id} ${a.package}: ${a.title} (${a.url})`;

console.log('Production dependencies:');
const prod = audit(['--omit=dev']);
if (!prod.length) console.log('  no known advisories');
for (const a of prod) {
  console.log('  ' + show(a));
  if (SERIOUS.has(a.severity)) failures.push(`production dependency: ${show(a)}`);
}

console.log('All dependencies, development included:');
const all = audit([]);
if (!all.length) console.log('  no known advisories');
for (const a of all) {
  const entry = allow.get(a.id);
  let note = '';
  if (SERIOUS.has(a.severity)) {
    if (!entry) failures.push(`not reviewed: ${show(a)}`);
    else if (entry.expires < today) failures.push(`review expired on ${entry.expires}: ${show(a)}`);
    else note = ` [reviewed ${entry.reviewed}, allowed until ${entry.expires}: development only]`;
  }
  console.log('  ' + show(a) + note);
}
for (const id of allow.keys()) {
  if (!all.some((a) => a.id === id)) console.log(`  note: ${id} is allowed but no longer found; remove it from the allow-list`);
}

if (failures.length) {
  console.error('\nThe dependency audit failed:\n  ' + failures.join('\n  '));
  console.error('Upgrade the package, or review the advisory and record it in .github/security/npm-audit-allowlist.json with its reason and an expiry date.');
  process.exit(1);
}
console.log('\nThe dependency audit passed.');
