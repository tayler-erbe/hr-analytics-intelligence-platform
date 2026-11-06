// Screenshot the offline dashboard (desktop light, phone dark) and fail on page errors.
// Run from platform-evaluation/:  node trend_nowcast/screenshot.js
const path = require('path');
const { chromium } = require('playwright');
(async () => {
  const out = path.resolve(__dirname, '..', 'output', 'trend_nowcast');
  const url = 'file://' + path.join(out, 'trend_nowcast.html');
  const browser = await chromium.launch();
  const errors = [];
  const shots = [
    { name: 'trend_nowcast.png', viewport: { width: 1280, height: 900 }, scheme: 'light' },
    { name: 'trend_nowcast_phone_dark.png', viewport: { width: 390, height: 844 }, scheme: 'dark' },
  ];
  for (const s of shots) {
    const ctx = await browser.newContext({ viewport: s.viewport, colorScheme: s.scheme, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(`${s.name}: ${e.message}`));
    page.on('console', m => { if (m.type() === 'error') errors.push(`${s.name}: ${m.text()}`); });
    await page.goto(url);
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) errors.push(`${s.name}: horizontal overflow ${overflow}px`);
    try {
      await page.screenshot({ path: path.join(out, s.name), fullPage: true });
    } catch (e) {
      // very tall pages can exceed the headless capture limit: retry once, then fall back to the first 8000 px
      console.warn(`${s.name}: full-page capture failed (${e.message.split('\n')[0]}); retrying`);
      await page.waitForTimeout(500);
      try { await page.screenshot({ path: path.join(out, s.name), fullPage: true }); }
      catch (e2) {
        const h = Math.min(8000, await page.evaluate(() => document.documentElement.scrollHeight));
        await page.setViewportSize({ width: s.viewport.width, height: h });
        await page.screenshot({ path: path.join(out, s.name) });
        console.warn(`${s.name}: saved the top ${h}px only`);
      }
    }
    console.log('wrote', s.name);
    await ctx.close();
  }
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('screenshots written to', out);
})();
