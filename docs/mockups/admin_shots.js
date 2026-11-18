// Screenshots of the admin page for the README, with made-up settings and a fake API.
// Run from the repo root after make_mockups.py:  node docs/mockups/admin_shots.js
// (needs Playwright: npm i -g playwright, or NODE_PATH pointing at a global install)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const OUT = path.join(ROOT, 'docs', 'images');
const html = fs.readFileSync(path.join(ROOT, 'aws_lambda', 'admin.html'), 'utf8');
const preview = fs.readFileSync(path.join(OUT, 'frame-morning-raw.png'));

const person = (name, letter, color, kind, grade, groups = []) =>
  ({ name, letter, color, kind, grade, groups, words: [name.toLowerCase()] });
const cfg = {
  version: 1, school_year: 2026,
  people: [person('Nora', 'N', 'YELLOW', 'barn', 6, ['Sild']), person('Emil', 'E', 'GREEN', 'barn', 4),
           person('Oskar', 'O', 'BLUE', 'barn', 0), person('Kari', 'K', 'RED', 'voksen', 0),
           person('Lars', 'L', 'BLACK', 'voksen', 0)],
  rules: [{ word: 'middag:', icon: 'food', tag: '', remove: true },
          { word: 'svømming', icon: 'waves', tag: '', remove: false },
          { word: 'korps', icon: 'music', tag: 'Nora', remove: false },
          { word: 'håndball', icon: 'volleyball', tag: 'Oskar', remove: false }],
  feeds: [{ name: 'Herrelandslaget (fotball)', url: 'https://example.com/landslaget.ics', tags: ['Lars'], icon: 'soccer', on: true }],
  spond: { on: true, groups: [
    { id: 'G1', name: 'Håndball G12', tags: ['Oskar'], icon: 'volleyball', on: true, only_accepted: false },
    { id: 'G2', name: 'Skolekorps', tags: ['Nora'], icon: 'music', on: true, only_accepted: true },
    { id: 'G3', name: 'Foreldregruppe 4A', tags: [], icon: '', on: false, only_accepted: false }] },
  view: { options: ['collapse', 'month_column', 'upcoming', 'tomorrow', 'evening', 'advice'], evening_hour: 17, days: 14 },
  ai: { model: 'claude-sonnet-5-5' },
};
const now = Date.parse('2026-11-17T05:47:00Z') / 1000;
const status = {
  meta: { rendered_at: '2026-11-17T05:47:00+00:00', battery: 87, event_count: 34, weather_days: 14,
          trigger: 'serve-fresh', errors: [] },
  feeds: { at: now - 600, result: {
    'f1': { name: 'example.com', created: 0, updated: 1, deleted: 0, skipped: 0 },
    'spond-G1': { name: 'Spond: Håndball G12', found: 9, created: 2, updated: 0, deleted: 1, skipped: 0 },
    'spond-G2': { name: 'Spond: Skolekorps', found: 4, created: 0, updated: 0, deleted: 0, skipped: 0 } } },
  letters: [{ at: now - 86400, message: 'La til 5 hendelser for Emil, uke 47' },
            { at: now - 3 * 86400, message: 'La til 6 hendelser for Nora, Emil, fra dokumentet' }],
};

(async () => {
  const browser = await chromium.launch();
  // SCHEME=dark node docs/mockups/admin_shots.js /tmp/admin-dark.png  to check dark mode
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2,
                                         isMobile: true, hasTouch: true, locale: 'nb-NO', timezoneId: 'Europe/Oslo',
                                         colorScheme: process.env.SCHEME === 'dark' ? 'dark' : 'light' });
  const page = await ctx.newPage();
  await page.clock.setFixedTime(new Date((now + 180) * 1000));   // "now" for the status checks
  await page.route('https://admin.example/**', async (route) => {
    const url = new URL(route.request().url());
    const json = (o) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(o) });
    if (url.pathname === '/admin') return route.fulfill({ contentType: 'text/html', body: html });
    if (url.pathname === '/api/config') return json({ config: cfg, stored: true });
    if (url.pathname === '/api/status') return json(status);
    if (url.pathname === '/api/preview') return route.fulfill({ contentType: 'image/png', body: preview });
    return route.fulfill({ status: 404, body: '{}' });
  });
  await page.goto('https://admin.example/admin#key=demo');
  await page.waitForTimeout(800);
  const shots = [];
  for (const tab of ['status', 'familie', 'abonnement', 'visning']) {
    await page.click(`nav.tabs button[data-t="${tab}"]`);
    await page.waitForTimeout(400);
    shots.push(await page.screenshot());
  }
  // the four tabs side by side in one image
  const sheet = await (await browser.newContext({ viewport: { width: 1600, height: 884 } })).newPage();
  await sheet.setContent(`<body style="margin:0;background:#fff;display:flex;gap:4px;padding:10px">${shots.map((b) =>
    `<img style="width:390px" src="data:image/png;base64,${b.toString('base64')}">`).join('')}</body>`);
  await sheet.screenshot({ path: process.argv[2] || path.join(OUT, 'admin.png') });
  console.log('wrote admin.png');
  await browser.close();
})();
