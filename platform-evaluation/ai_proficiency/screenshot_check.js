// Playwright smoke test for output/ai_proficiency/rubric_toolkit.html.
// Usage (from platform-evaluation/ai_proficiency/): node screenshot_check.js [outDir]
// Checks: no console errors, no network requests beyond the file itself, no
// horizontal page scroll at 375px, every tab renders, the scoring form saves a
// row and the CSV export downloads locally. Writes PNG screenshots to outDir.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const page_url = 'file://' + path.resolve(__dirname, '..', 'output', 'ai_proficiency', 'rubric_toolkit.html');
const outDir = process.argv[2] || path.resolve(__dirname, '..', 'output', 'ai_proficiency', 'screenshots');
fs.mkdirSync(outDir, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const failures = [];
  for (const [name, viewport, scheme] of [
    ['phone-light', { width: 375, height: 800 }, 'light'],
    ['phone-dark', { width: 375, height: 800 }, 'dark'],
    ['desktop-light', { width: 1280, height: 900 }, 'light'],
  ]) {
    const ctx = await browser.newContext({ viewport, colorScheme: scheme, acceptDownloads: true });
    const page = await ctx.newPage();
    const errors = [], requests = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));
    page.on('request', r => { if (!r.url().startsWith('file://') && !r.url().startsWith('blob:') && !r.url().startsWith('data:')) requests.push(r.url()); });
    await page.goto(page_url);
    for (const tab of ['rubric', 'tasks', 'score', 'report', 'about']) {
      await page.click(`nav [data-tab="${tab}"]`);
      await page.waitForTimeout(150);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 1) failures.push(`${name}/${tab}: horizontal overflow ${overflow}px`);
      if (tab === 'rubric' || tab === 'report' || (tab === 'score' && name !== 'phone-dark')) {
        await page.screenshot({ path: path.join(outDir, `${name}-${tab}.png`), fullPage: tab !== 'report' || name.startsWith('desktop') });
      }
    }
    // scoring form round trip
    await page.click('nav [data-tab="score"]');
    await page.fill('#fRater', 'R2');
    await page.fill('#fCand', 'jane.doe@illinois.edu');
    for (const d of ['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8']) await page.check(`#r-${d}-3`);
    await page.click('#scoreForm button[type=submit]');
    const rejected = await page.textContent('#formMsg');
    if (!/pseudonymous/.test(rejected)) failures.push(`${name}: email-like candidate code was not rejected`);
    await page.fill('#fCand', 'C014');
    await page.click('#scoreForm button[type=submit]');
    const nRows = await page.textContent('#nRows');
    if (nRows !== '1') failures.push(`${name}: expected 1 saved row, got ${nRows}`);
    const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#exportLong')]);
    const csvPath = path.join(outDir, `${name}-export.csv`);
    await dl.saveAs(csvPath);
    const lines = fs.readFileSync(csvPath, 'utf8').trim().split(/\r?\n/);
    if (lines.length !== 9 || !lines[0].startsWith('phase,session,artifact_id')) failures.push(`${name}: CSV export malformed (${lines.length} lines)`);
    fs.unlinkSync(csvPath);
    if (name === 'phone-light') await page.screenshot({ path: path.join(outDir, `${name}-score-saved.png`), fullPage: false });
    // charts present
    await page.click('nav [data-tab="report"]');
    const circles = await page.locator('#driftChart circle').count();
    if (circles < 30) failures.push(`${name}: drift chart has ${circles} circles`);
    if (errors.length) failures.push(`${name}: console errors: ${errors.join(' | ')}`);
    if (requests.length) failures.push(`${name}: network requests: ${requests.join(', ')}`);
    await ctx.close();
  }
  await browser.close();
  if (failures.length) { console.error('FAIL\n' + failures.join('\n')); process.exit(1); }
  console.log('OK: no console errors, no network requests, no horizontal overflow, form + CSV export work. Screenshots in ' + outDir);
})();
