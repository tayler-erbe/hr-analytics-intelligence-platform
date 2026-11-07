// Screenshot the WAP dashboard: every view, desktop + phone, light + dark; fail on JS errors or horizontal overflow.
//   node wap_prototype/publish_star/screenshot.js      (run from platform-evaluation/)
const path = require('path');
const { chromium } = require('playwright');
(async () => {
  const page_ = path.resolve(__dirname, '..', '..', 'output', 'wap_prototype', 'wap_dashboard.html');
  const outDir = path.resolve(__dirname, '..', '..', 'output', 'wap_prototype', 'screenshots');
  require('fs').mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const errors = [];
  const views = ['v1', 'v2', 'v3', 'v4', 'v5', 'mq', 'dq'];
  for (const [name, vp] of [['desktop', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
    for (const scheme of ['light', 'dark']) {
      const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      page.on('pageerror', e => errors.push(`${name}/${scheme}: ${e.message}`));
      page.on('console', m => { if (m.type() === 'error') errors.push(`${name}/${scheme}: ${m.text()}`); });
      page.on('request', r => { if (!r.url().startsWith('file:')) errors.push(`${name}/${scheme}: network request ${r.url()}`); });
      for (const v of views) {
        await page.goto('file://' + page_ + '#' + v);
        await page.waitForTimeout(200);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        if (overflow > 1) errors.push(`${name}/${scheme}/${v}: horizontal page overflow ${overflow}px`);
        if (scheme === 'light' || v === 'v3') await page.screenshot({ path: path.join(outDir, `${v}_${name}_${scheme}.png`), fullPage: true });
      }
      await ctx.close();
    }
  }
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('screenshots written to', outDir);
})();
