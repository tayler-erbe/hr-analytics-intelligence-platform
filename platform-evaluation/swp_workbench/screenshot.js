// Playwright check + screenshots for output/swp_workbench/swp_workbench.html.
// Usage (from platform-evaluation/): node swp_workbench/screenshot.js "$PWD/output/swp_workbench/swp_workbench.html" "$PWD/output/swp_workbench/screenshots"
// Prints console errors, non-file network requests, section counts, horizontal overflow and an export round-trip.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
async function retry(fn, page) { for (let i = 0; i < 4; i++) { try { return await fn(); } catch (e) { if (i === 3) throw e; await page.waitForTimeout(400); } } }
(async () => {
  const file = process.argv[2], outDir = process.argv[3];
  const url = 'file://' + file;
  const browser = await chromium.launch();
  const report = {errors: [], requests: [], checks: {}};
  for (const [name, vp, scheme] of [['desktop_light', {width: 1280, height: 900}, 'light'], ['phone_dark', {width: 390, height: 844}, 'dark']]) {
    const ctx = await browser.newContext({viewport: vp, colorScheme: scheme, acceptDownloads: true});
    const page = await ctx.newPage();
    page.on('pageerror', e => report.errors.push(name + ': ' + e.message));
    page.on('console', m => { if (m.type() === 'error') report.errors.push(name + ' console: ' + m.text()); });
    page.on('request', r => { if (!r.url().startsWith('file:') && !r.url().startsWith('blob:') && !r.url().startsWith('data:')) report.requests.push(r.url()); });
    await page.goto(url);
    await page.waitForSelector('#t_learning');
    report.checks[name + '_sections'] = await page.$$eval('section.tool', s => s.length);
    report.checks[name + '_hscroll'] = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (name === 'desktop_light') {
      await page.selectOption('#unit', 'U11');
      report.checks.u11_heading = await page.textContent('#unitDesc');
      const before = await page.textContent('#gapTable');
      await page.fill('input[data-tf="OAS"]', '50');
      await page.dispatchEvent('input[data-tf="OAS"]', 'input');
      report.checks.gap_changed = before !== await page.textContent('#gapTable');
      await page.fill('#f_bench_vulnerable', 'Senior BFO approvals depend on two lines; cross-train level 3.');
      await page.dispatchEvent('#f_bench_vulnerable', 'input');
      await page.fill('#f_knowledge_critical_knowledge', 'contact jane.doe@illinois.edu');
      await page.dispatchEvent('#f_knowledge_critical_knowledge', 'input');
      report.checks.pii_warning = await page.textContent('#w_knowledge_critical_knowledge');
      await page.fill('#f_knowledge_critical_knowledge', 'Year-end close steps; grant reconciliation.');
      await page.dispatchEvent('#f_knowledge_critical_knowledge', 'input');
      const [dj] = await Promise.all([page.waitForEvent('download'), page.click('#xjson')]);
      const pj = path.join(outDir, dj.suggestedFilename()); await dj.saveAs(pj);
      const [dc] = await Promise.all([page.waitForEvent('download'), page.click('#xcsv')]);
      const pc = path.join(outDir, dc.suggestedFilename()); await dc.saveAs(pc);
      report.checks.export_json = JSON.parse(fs.readFileSync(pj, 'utf8')).notes;
      report.checks.export_csv = fs.readFileSync(pc, 'utf8');
      await page.selectOption('#unit', 'ALL');
      await retry(() => page.screenshot({path: path.join(outDir, 'swp_workbench_desktop_top.png')}), page);
      await page.locator('#t_bench').scrollIntoViewIfNeeded();
      await retry(() => page.locator('#t_bench').screenshot({path: path.join(outDir, 'swp_workbench_bench_ALL.png')}), page);
      await page.selectOption('#unit', 'U11');
      await retry(() => page.locator('#t_capability').screenshot({path: path.join(outDir, 'swp_workbench_capability_U11.png')}), page);
      await retry(() => page.locator('#t_knowledge').screenshot({path: path.join(outDir, 'swp_workbench_knowledge_U11.png')}), page);
    } else {
      await page.selectOption('#unit', 'U15');
      await retry(() => page.screenshot({path: path.join(outDir, 'swp_workbench_phone_dark_top.png')}), page);
      await retry(() => page.locator('#t_bench').screenshot({path: path.join(outDir, 'swp_workbench_phone_dark_bench_U15.png')}), page);
      report.checks.phone_hscroll_U15 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    }
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(report, null, 1));
})();
