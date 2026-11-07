// Playwright smoke test: open every view at 390 px and 1280 px, fail on any JS error, console error, network
// request or horizontal page scroll.   node wap_prototype/publish_star/tests/smoke.js <dashboard.html>
const { chromium } = require('playwright');
(async () => {
  const file = process.argv[2];
  const browser = await chromium.launch();
  const errors = [];
  for (const vp of [{ width: 390, height: 844 }, { width: 1280, height: 900 }]) {
    for (const scheme of ['light', 'dark']) {
      const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme });
      const page = await ctx.newPage();
      page.on('pageerror', e => errors.push(`${vp.width}/${scheme}: pageerror ${e.message}`));
      page.on('console', m => { if (m.type() === 'error') errors.push(`${vp.width}/${scheme}: console ${m.text()}`); });
      page.on('request', r => { if (!r.url().startsWith('file:')) errors.push(`${vp.width}/${scheme}: network ${r.url()}`); });
      for (const v of ['v1', 'v2', 'v3', 'v4', 'v5', 'mq', 'dq']) {
        await page.goto('file://' + file + '#' + v);
        await page.waitForTimeout(150);
        const o = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        if (o > 1) errors.push(`${vp.width}/${scheme}/${v}: horizontal overflow ${o}px`);
        const n = await page.evaluate(() => document.querySelectorAll('section.view.active').length);
        if (n !== 1) errors.push(`${vp.width}/${scheme}/${v}: view did not render`);
        if (vp.width === 390 && v === 'v3') {
          // slicer interaction must not throw
          await page.selectOption('#v3t', 'hire').catch(e => errors.push('slicer: ' + e.message));
          await page.waitForTimeout(100);
        }
      }
      await ctx.close();
    }
  }
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('smoke ok');
})();
