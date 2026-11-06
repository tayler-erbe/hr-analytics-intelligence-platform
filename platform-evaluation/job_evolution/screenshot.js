// Screenshot the offline explorer at desktop and phone width, light and dark, and
// fail on console errors or horizontal page overflow.
// Usage: node job_evolution/screenshot.js
const path = require('path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const PAGE = 'file://' + path.join(ROOT, 'output/job_evolution/job_evolution_explorer.html');
const OUT = path.join(ROOT, 'output/job_evolution/screenshots');
(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const shots = [
    { name: 'desktop_light_watchlist', w: 1280, h: 900, scheme: 'light', tab: 'watch', full: true },
    { name: 'desktop_dark_timeline', w: 1280, h: 900, scheme: 'dark', tab: 'occ', full: true },
    { name: 'desktop_light_model', w: 1280, h: 900, scheme: 'light', tab: 'model', full: true },
    { name: 'desktop_dark_tech', w: 1280, h: 900, scheme: 'dark', tab: 'tech', full: true },
    { name: 'phone_light_watchlist', w: 390, h: 844, scheme: 'light', tab: 'watch', full: false },
    { name: 'phone_dark_timeline', w: 390, h: 844, scheme: 'dark', tab: 'occ', full: true },
  ];
  const report = [];
  for (const s of shots) {
    const ctx = await browser.newContext({ viewport: { width: s.w, height: s.h }, colorScheme: s.scheme });
    const page = await ctx.newPage();
    page.on('console', m => { if (m.type() === 'error') errors.push(`${s.name}: ${m.text()}`); });
    page.on('pageerror', e => errors.push(`${s.name}: ${e.message}`));
    page.on('request', r => { if (!r.url().startsWith('file:') && !r.url().startsWith('data:')) errors.push(`${s.name}: network request ${r.url()}`); });
    await page.goto(PAGE);
    await page.click(`nav.tabs button[data-tab="${s.tab}"]`);
    if (s.tab === 'watch') await page.click('#famtable tr.click');
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    report.push({ shot: s.name, horizontal_overflow_px: overflow });
    if (overflow > 1) errors.push(`${s.name}: horizontal overflow ${overflow}px`);
    await page.screenshot({ path: path.join(OUT, s.name + '.png'), fullPage: s.full });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify({ report, errors }, null, 1));
  process.exit(errors.length ? 1 : 0);
})();
