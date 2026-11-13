// Headless check of the viewer at desktop and phone size: loads each clip, plays, scrubs, checks that the videos
// follow the timeline, collects console errors and saves screenshots.
//   PW_CORE=/path/to/node_modules/playwright-core/index.mjs node tests/shots.mjs http://localhost:8765 OUT_DIR [--rebuild]
// Uses Google Chrome when present (H.264 playback), else Playwright's Chromium.
import fs from 'node:fs';
const {chromium} = await import(process.env.PW_CORE || 'playwright-core');
const [base = 'http://localhost:8765', out = '/tmp/drone4d_shots'] = process.argv.slice(2);
const wantRebuild = process.argv.includes('--rebuild');
fs.mkdirSync(out, {recursive: true});
const chrome = process.env.PW_BROWSER || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser = await chromium.launch({executablePath: fs.existsSync(chrome) ? chrome : undefined, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required']});
const sizes = {desktop: {viewport: {width: 1440, height: 900}}, phone: {viewport: {width: 390, height: 844}, deviceScaleFactor: 3, isMobile: true, hasTouch: true}};
const report = {};
let failed = false;
for (const [name, opt] of Object.entries(sizes)) {
  for (const scheme of ['light', 'dark']) {
    if (name === 'phone' && scheme === 'dark' && !process.argv.includes('--all')) continue;
    const ctx = await browser.newContext({...opt, colorScheme: scheme});
    const p = await ctx.newPage();
    const errs = [];
    p.on('console', m => { if (m.type() === 'error') errs.push(m.text()) });
    p.on('pageerror', e => errs.push('pageerror: ' + e.message));
    p.on('response', r => { if (r.status() >= 400) errs.push(`HTTP ${r.status()} ${r.url()}`) });
    await p.goto(base + '/');
    const clips = await p.$$eval('#clips button', bs => bs.map(b => b.dataset.id));
    for (const clip of clips) {
      const tag = `${name}_${scheme}_${clip}`;
      await p.click(`#clips button[data-id="${clip}"]`);
      await p.waitForFunction(() => /slice \d+ · [\d,]+ points/.test(document.getElementById('status').textContent), null, {timeout: 120000});
      await p.waitForTimeout(800);
      // scrub to 40 %, then play for a while
      await p.$eval('#t', el => { el.value = 4000; el.dispatchEvent(new Event('input')) });
      await p.waitForTimeout(700);
      const scrub = await p.evaluate(() => [...document.querySelectorAll('#videos video')].map(v => ({d: v.dataset.drone, t: v.currentTime, ready: v.readyState, err: v.error && v.error.code})));
      await p.click('#play');
      await p.waitForTimeout(1500);
      const play = await p.evaluate(() => ({time: document.getElementById('time').textContent, vids: [...document.querySelectorAll('#videos video')].map(v => ({t: +v.currentTime.toFixed(3), paused: v.paused}))}));
      await p.click('#play');
      await p.waitForTimeout(500);
      const geo = await p.evaluate(() => ({scrollW: document.documentElement.scrollWidth, innerW: innerWidth, scrollH: document.documentElement.scrollHeight, innerH: innerHeight,
        tags: [...document.querySelectorAll('.tag')].filter(t => t.style.display !== 'none').map(t => t.textContent), status: document.getElementById('status').textContent}));
      await p.screenshot({path: `${out}/${tag}.png`});
      report[tag] = {scrub, play, geo};
      if (geo.scrollW > geo.innerW) { failed = true; console.log(`FAIL ${tag}: horizontal scroll ${geo.scrollW} > ${geo.innerW}`) }
      if (wantRebuild && await p.$eval('#rebuildbar', e => getComputedStyle(e).display !== 'none')) {
        for (const m of ['rebuild', 'both']) {
          await p.click(`#rbmode button[data-m="${m}"]`);
          await p.waitForTimeout(1200);
          await p.screenshot({path: `${out}/${tag}_${m}.png`});
        }
        report[tag].rebuild = await p.$eval('#rbinfo', e => e.textContent);
        await p.click('#rbmode button[data-m="release"]');
      }
    }
    report[`${name}_${scheme}_errors`] = errs;
    if (errs.length) { failed = true; console.log(`FAIL ${name} ${scheme}: ${errs.length} errors`) }
    await ctx.close();
  }
}
await browser.close();
fs.writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 1));
console.log(JSON.stringify(report, null, 1));
process.exit(failed ? 1 : 0);
