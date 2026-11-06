// Screenshots of the offline demo (desktop light, desktop dark abstention, phone).
// Usage: node policy_assistant/screenshot.js [output/policy_assistant/index.html]
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const file = path.resolve(process.argv[2] || "output/policy_assistant/index.html");
  const outDir = path.dirname(file);
  const browser = await chromium.launch();
  const errors = [];
  const shots = [
    { name: "screenshot_desktop_light.png", vp: { width: 1200, height: 1000 }, scheme: "light",
      q: "When is the deadline to choose benefits as a new employee?" },
    { name: "screenshot_desktop_dark_abstain.png", vp: { width: 1200, height: 800 }, scheme: "dark",
      q: "Should we fire the employee with the lowest rating?" },
    { name: "screenshot_phone_dark.png", vp: { width: 390, height: 844 }, scheme: "dark",
      q: "Who is eligible for the Faculty/Staff Emergency Fund?" },
  ];
  for (const s of shots) {
    const ctx = await browser.newContext({ viewport: s.vp, colorScheme: s.scheme, offline: true });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(s.name + ": " + e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(s.name + ": " + m.text()); });
    await page.goto("file://" + file);
    await page.fill("#q", s.q);
    await page.click("button.go");
    await page.waitForSelector("#out .card");
    const status = await page.textContent("#out .badge");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    console.log(JSON.stringify({ shot: s.name, question: s.q, status, horizontal_overflow: overflow }));
    await page.screenshot({ path: path.join(outDir, s.name), fullPage: s.vp.width < 500 ? false : false });
    await ctx.close();
  }
  await browser.close();
  if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
})();
