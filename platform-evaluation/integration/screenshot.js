// Screenshot the integration explorer: desktop + phone, light + dark.
//   node integration/screenshot.js      (run from platform-evaluation/)
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const page_ = path.resolve(__dirname, '..', 'output', 'integration', 'integration_explorer.html');
  const outDir = path.resolve(__dirname, '..', 'output', 'integration', 'screenshots');
  require('fs').mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const errors = [];
  for (const [name, vp] of [['desktop', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
    for (const scheme of ['light', 'dark']) {
      const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme, deviceScaleFactor: name === 'phone' ? 2 : 1 });
      const page = await ctx.newPage();
      page.on('pageerror', e => errors.push(`${name}/${scheme}: ${e.message}`));
      page.on('console', m => { if (m.type() === 'error') errors.push(`${name}/${scheme}: ${m.text()}`); });
      await page.goto('file://' + page_);
      await page.waitForTimeout(300);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 1) errors.push(`${name}/${scheme}: horizontal page overflow ${overflow}px`);
      await page.screenshot({ path: path.join(outDir, `explorer_${name}_${scheme}.png`), fullPage: true });
      await ctx.close();
    }
  }
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('screenshots written to', outDir);
})();
