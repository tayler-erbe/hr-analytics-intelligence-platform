// Usage (from platform-evaluation/): NODE_PATH=$(npm root -g) node ipeds_models/screenshot.js <out_dir>
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const out = process.argv[2] || '.';
  const b = await chromium.launch();
  const errs = [];
  for (const [name, vp, scheme] of [['desktop', {width: 1280, height: 900}, 'light'], ['phone', {width: 390, height: 844}, 'dark']]) {
    const p = await b.newPage({viewport: vp, colorScheme: scheme});
    p.on('pageerror', e => errs.push(name + ': ' + e.message));
    p.on('console', m => { if (m.type() === 'error') errs.push(name + ' console: ' + m.text()); });
    p.on('request', r => { if (!r.url().startsWith('file:')) errs.push(name + ' network: ' + r.url()); });
    await p.goto('file://' + path.resolve(__dirname, '../output/ipeds_models/ipeds_models.html'));
    await p.waitForTimeout(400);
    await p.screenshot({path: path.join(out, 'ipeds_models_' + name + '.png'), fullPage: true});
    const sw = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    console.log(name, 'scrollWidth/innerWidth', sw);
    if (name === 'desktop') {
      await p.selectOption('#uCampus', '145600'); await p.selectOption('#uTask', 'newhire');
      await p.waitForTimeout(200);
      const el = await p.$('#uChart'); await el.screenshot({path: path.join(out, 'ipeds_models_uic_newhire.png')});
      console.log('UIC note:', await p.$eval('#uNote', e => e.innerText));
    }
  }
  console.log('errors:', JSON.stringify(errs));
  await b.close();
})();
