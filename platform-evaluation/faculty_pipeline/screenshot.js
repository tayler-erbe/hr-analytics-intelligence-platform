const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const errs = [];
  for (const [name, vp, scheme] of [['desktop',{width:1280,height:900},'light'],['phone',{width:390,height:844},'dark']]) {
    const p = await b.newPage({viewport: vp, colorScheme: scheme});
    p.on('pageerror', e => errs.push(name+': '+e.message));
    p.on('console', m => { if (m.type()==='error') errs.push(name+' console: '+m.text()); });
    await p.goto('file://'+require('path').resolve(__dirname,'../output/faculty_pipeline/faculty_pipeline.html'));
    await p.waitForTimeout(500);
    await p.screenshot({path: process.argv[2]+'/fp_'+name+'.png', fullPage: true});
    const sw = await p.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    console.log(name, 'scrollWidth', sw);
    if (name==='desktop') {
      await p.selectOption('#inst','UIC'); await p.selectOption('#bud','1.30'); await p.selectOption('#inc','2.0'); await p.selectOption('#enr','eng_surge');
      await p.waitForTimeout(300);
      await p.screenshot({path: process.argv[2]+'/fp_uic.png', fullPage: false});
      const k = await p.$eval('#kpis', e => e.innerText); console.log(k.replace(/\n/g,' | '));
    }
  }
  console.log('errors:', JSON.stringify(errs));
  await b.close();
})();
