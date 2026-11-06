// Playwright check: desktop (light) and phone (dark) screenshots; fails on JS errors and reports horizontal overflow.
//   NODE_PATH=$(npm root -g) node turnover_forecast/screenshot.js output/turnover_forecast
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const outDir = process.argv[2] || 'output/turnover_forecast';
  const b = await chromium.launch();
  const errs = [];
  for (const [name, vp, scheme] of [['desktop', {width: 1280, height: 900}, 'light'], ['phone', {width: 390, height: 844}, 'dark']]) {
    const p = await b.newPage({viewport: vp, colorScheme: scheme});
    p.on('pageerror', e => errs.push(name + ': ' + e.message));
    p.on('console', m => { if (m.type() === 'error') errs.push(name + ' console: ' + m.text()); });
    await p.goto('file://' + path.resolve(__dirname, '../output/turnover_forecast/turnover_forecast.html'));
    await p.waitForTimeout(600);
    await p.screenshot({path: path.join(outDir, 'screenshot_' + name + '.png'), fullPage: true});
    const sw = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    console.log(name, 'scrollWidth/innerWidth', sw);
    if (name === 'desktop') {
      const box = await p.$eval('#fc svg', e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; });
      await p.mouse.move(box[0] + box[2] * 0.92, box[1] + box[3] * 0.5);
      await p.waitForTimeout(200);
      console.log('tooltip:', (await p.$eval('#fc .tip', e => e.innerText)).replace(/\n/g, ' | '));
      await p.screenshot({path: path.join(outDir, 'screenshot_forecast_hover.png'), clip: {x: 0, y: box[1] - 80, width: 1280, height: box[3] + 160}});
      console.log('kpis:', (await p.$eval('#kpis', e => e.innerText)).replace(/\n/g, ' | '));
    }
  }
  console.log('errors:', JSON.stringify(errs));
  await b.close();
  if (errs.length) process.exit(1);
})();
