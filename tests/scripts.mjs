// Script load-order check (no browser needed): the site is plain classic scripts, so order matters.
//  - config.js is the first local script (constants every other script may use)
//  - utils.js comes next, then every tabs/*.js file, then app.js last
//  - every tabs/*.js file on disk is referenced in index.html (and every reference exists)
// Run with: npm run test:scripts   (also runs first in npm run test:page)
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(ROOT, 'index.html'), 'utf8');
const failures = [];

// Local (non-CDN) script tags in document order, without ?v= cache-busting queries
const scripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"[^>]*>/g)]
  .map(m => m[1])
  .filter(src => !/^(https?:)?\/\//.test(src))
  .map(src => src.split('?')[0]);

const idx = f => scripts.indexOf(f);
const tabFiles = readdirSync(join(ROOT, 'tabs')).filter(f => f.endsWith('.js')).map(f => `tabs/${f}`);

if (scripts[0] !== 'config.js') failures.push(`config.js must be the first local script (found: ${scripts[0]})`);
if (idx('utils.js') !== 1) failures.push('utils.js must be the second local script, right after config.js');
if (scripts[scripts.length - 1] !== 'app.js') failures.push(`app.js must be the last local script (found: ${scripts[scripts.length - 1]})`);
for (const f of tabFiles) {
  if (idx(f) === -1) failures.push(`${f} exists but is not loaded by index.html`);
  else if (idx(f) < idx('utils.js') || idx(f) > idx('app.js')) failures.push(`${f} must load after utils.js and before app.js`);
}
for (const s of scripts) {
  if (!existsSync(join(ROOT, s))) failures.push(`index.html loads ${s}, which does not exist`);
}
const dupes = scripts.filter((s, i) => scripts.indexOf(s) !== i);
if (dupes.length) failures.push(`loaded more than once: ${[...new Set(dupes)].join(', ')}`);

if (failures.length) {
  console.error('script load-order check FAILED:\n - ' + failures.join('\n - '));
  process.exit(1);
}
console.log(`script load-order check passed (${scripts.length} scripts: ${scripts.join(', ')})`);
