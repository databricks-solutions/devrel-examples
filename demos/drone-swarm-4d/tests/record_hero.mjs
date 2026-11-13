// Record the hero clip from the App: clip1, the 4D view alone, a slow orbit round the person while time plays.
// Frames are stepped deterministically (?hero=1 exposes window.drone4d.step), so the result is smooth however slow
// the headless renderer is. Writes tests/out/hero/hero.mp4 (H.264) and hero.gif.
//   PW_CORE=.../playwright-core/index.mjs node tests/record_hero.mjs [BASE_URL] [SECONDS] [FPS]
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PW_CORE || 'playwright-core');
const [base = 'http://localhost:8765', seconds = '9', fps = '30'] = process.argv.slice(2);
const clip = process.env.HERO_CLIP || 'clip1_three_drones';
const out = new URL('./out/hero/', import.meta.url).pathname, frames = out + 'frames/';
fs.rmSync(frames, {recursive: true, force: true});
fs.mkdirSync(frames, {recursive: true});
const n = Math.round(+seconds * +fps), turn = +seconds * 1.05;   // a little over one turn in the clip
const chrome = process.env.PW_BROWSER || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser = await chromium.launch({executablePath: fs.existsSync(chrome) ? chrome : undefined, headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
const page = await browser.newPage({viewport: {width: 1280, height: 720}});
page.on('pageerror', e => console.log('pageerror', e.message));
await page.goto(`${base}/?clip=${clip}&hero=1&fov=${process.env.HERO_FOV || 28}&zoom=${process.env.HERO_ZOOM || 1.15}&orbit=${(60 / turn).toFixed(3)}`);
await page.waitForFunction(() => window.drone4d && window.drone4d.ready(), null, {timeout: 600000, polling: 500});
await page.evaluate(() => { window.drone4d.resetView(); for (let i = 0; i < 30; i++) window.drone4d.step(0); window.drone4d.play() });
for (let i = 0; i < n; i++) {
  await page.evaluate(dt => window.drone4d.step(dt), 1 / +fps);
  await page.screenshot({path: `${frames}${String(i).padStart(4, '0')}.png`});
}
await browser.close();
const ff = (...a) => execFileSync('ffmpeg', ['-loglevel', 'error', '-y', ...a], {stdio: 'inherit'});
ff('-framerate', fps, '-i', `${frames}%04d.png`, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart', `${out}hero.mp4`);
ff('-i', `${out}hero.mp4`, '-vf', 'fps=15,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a', `${out}hero.gif`);
for (const f of ['hero.mp4', 'hero.gif']) console.log(out + f, (fs.statSync(out + f).size / 1e6).toFixed(1), 'MB');
