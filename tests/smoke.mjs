// Page smoke test: loads index.html against the committed data, opens every tab and fails on any
// page error or empty tab. One manager is renamed to an HTML payload to check that names are escaped.
// Run with: npm run test:page   (needs `npx playwright install chromium` once)
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const TYPES = { '.html': 'text/html', '.css': 'text/css', '.json': 'application/json', '.js': 'text/javascript' };
const PAYLOAD = '<img src=x onerror="window.__xss=(window.__xss||0)+1">';

// Rename the first manager in the first league everywhere it appears
function withPayload(json) {
  const data = JSON.parse(json);
  const rows = data[Object.keys(data)[0]];
  let inRosters = false, victim = null;
  for (const r of rows) {
    const c0 = String(r[0] || '').trim();
    if (c0.startsWith('---')) { inRosters = c0.includes('ROSTERS'); continue; }
    if (inRosters && c0 && c0 !== 'Team / Manager') { victim = c0; break; }
  }
  if (!victim) return json;
  const enc = s => JSON.stringify(s).slice(1, -1);
  return json.split(enc(victim)).join(enc(`${PAYLOAD} (${victim})`));
}

const server = createServer((req, res) => {
  const path = decodeURIComponent(req.url.split('?')[0]);
  const file = join(ROOT, path === '/' ? 'index.html' : path);
  if (!file.startsWith(ROOT) || !existsSync(file)) { res.writeHead(404); return res.end(); }
  let body = readFileSync(file);
  if (path === '/sleeper_leagues_master.json') body = withPayload(body.toString());
  res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
  res.end(body);
}).listen(0);
const base = `http://localhost:${server.address().port}/`;

const failures = [];
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  page.on('pageerror', e => failures.push(`page error: ${e.message}`));
  await page.route(/^https?:\/\/(?!localhost)/, r => r.abort()); // no live APIs, CDNs or workers
  await page.goto(base);
  await page.waitForFunction(() => !document.getElementById('app-container').classList.contains('hidden'), null, { timeout: 30000 });
  const tabs = await page.evaluate(() => [...document.querySelectorAll('[id^="tab-"]')].map(e => e.id.slice(4)));
  for (const tab of tabs) {
    await page.evaluate(t => switchTab(t), tab);
    await page.waitForTimeout(200);
    const len = await page.evaluate(t => document.getElementById(`tab-${t}`).innerText.trim().length, tab);
    if (len < 50) failures.push(`tab "${tab}" is empty`);
  }
  // Projected rookie draft order: one row per team in round 1, and a tank watch while the season is on
  const draftOrder = await page.evaluate(() => { switchTab('picks'); return document.querySelectorAll('#draft-order-list > div').length; });
  if (draftOrder < 8) failures.push(`projected draft order shows ${draftOrder} picks`);
  // Trade Partners pair modal shows a grade for every trade, like the Trade Log
  await page.evaluate(() => { switchTab('synergy'); openTradeModal(0); });
  const modal = await page.evaluate(() => {
    const deals = document.querySelectorAll('#modal-body > div');
    return { deals: deals.length, graded: [...deals].filter(d => /trade grade/i.test(d.innerText)).length };
  });
  if (!modal.deals || modal.graded !== modal.deals) failures.push(`trade partner modal graded ${modal.graded} of ${modal.deals} trades`);
  await page.evaluate(() => closeTradeModal());
  // The Gazette still shows (as plain text) when the Markdown scripts from the CDN don't load
  const gazette = await page.evaluate(async () => {
    switchTab('review');
    window.fetchGazette = async () => [{ week: 3, text: '**Headline**\n\nBody text' }];
    const sel = document.querySelector('#tab-review select');
    await loadGazette(sel ? sel.value : '', '2026');
    return (document.getElementById('review-gazette') || {}).innerText || '';
  });
  if (!/Headline/.test(gazette)) failures.push('Gazette did not render without the Markdown scripts');
  // Podcast show notes: a section per league plus the cross-league one, SFB16 left out, Gazette lead added
  const notes = await page.evaluate(async () => {
    window.fetchGazette = async () => [{ week: Number(document.getElementById('notes-week')?.value || 0), text: '# Big Week Headline\n\nBody' }];
    openShowNotes();
    await new Promise(r => setTimeout(r, 300));
    const text = showNotesText();
    const offseason = podcastLeagues().map(offseasonShowNotes).flat().length;
    closeShowNotes();
    return { sections: showNotesStore.length, text, offseason };
  });
  if (notes.sections < 2) failures.push(`show notes has ${notes.sections} sections`);
  if (/sfb16|mario kart/i.test(notes.text)) failures.push('show notes include SFB16');
  if (!/Big Week Headline/.test(notes.text)) failures.push('show notes are missing the Gazette headline');
  if (!notes.offseason) failures.push('offseason show notes are empty');
  // The home-screen manifest and its icons exist
  const manifest = await page.evaluate(async () => {
    const r = await fetch('manifest.json');
    if (!r.ok) return 'manifest.json missing';
    const m = await r.json();
    for (const i of m.icons || []) if (!(await fetch(i.src)).ok) return `icon missing: ${i.src}`;
    return '';
  });
  if (manifest) failures.push(manifest);
  const xss = await page.evaluate(() => window.__xss || 0);
  if (xss) failures.push(`unescaped team name ran script ${xss} time(s)`);
  console.log(`opened ${tabs.length} tabs`);
} finally {
  await browser.close();
  server.close();
}
if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
console.log('page smoke test passed');
