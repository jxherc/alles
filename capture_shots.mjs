// capture_shots.mjs — regenerate the README screenshots from a running demo instance.
//   node capture_shots.mjs            (expects the app on :8799 with demo data seeded)
// writes straight into docs/screenshots/ at 1920x1230 to match the existing set.
import { createRequire } from 'module';
import { glob } from 'fs/promises';
import { mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const require = createRequire('C:/Users/jxh/AppData/Local/Temp/puppeteer-test/');
const puppeteer = require('puppeteer-core');
async function findChrome() {
  for await (const p of glob('C:/Users/jxh/AppData/Local/ms-playwright/chromium*/chrome-win64/chrome.exe')) return p;
  throw new Error('no Chromium');
}
const P = 8799;
const OUT = 'docs/screenshots';
const THEME = process.env.SHOT_THEME || 'dark';   // 'dark' | 'light' | '' (leave whatever the server saved)
const wait = ms => new Promise(r => setTimeout(r, ms));

// force a theme for the shot without persisting it (DOM-only). runs AFTER boot+server-reconcile so it
// sticks. uses the app's own applyAppearance with the dark/light preset palette.
async function applyTheme(page, mode) {
  if (!mode) return;
  await page.evaluate(async (m) => {
    const mod = await import('/static/js/theme.js');
    const base = m === 'light' ? mod.PRESETS.light : mod.PRESETS.dark;
    const cur = mod.getAppearance ? mod.getAppearance() : {};
    mod.applyAppearance({ ...cur, preset: m, colors: { ...base.colors } });
  }, mode).catch(e => console.error('theme switch failed:', e.message));
}

// [file, url, optional async (page)=>{} for interaction before the shot]
const SHOTS = [
  ['home',     `http://localhost:${P}/`],
  ['aide',     `http://aide.localhost:${P}/`],
  ['activity', `http://activity.localhost:${P}/`],
  ['docs',     `http://docs.localhost:${P}/`],
  ['calendar', `http://calendar.localhost:${P}/`],
  ['tasks',    `http://tasks.localhost:${P}/`],
  ['journal',  `http://journal.localhost:${P}/`],
  ['subs',     `http://subs.localhost:${P}/`],
  ['money',    `http://money.localhost:${P}/`],
  ['days',     `http://days.localhost:${P}/`],
  ['system',   `http://system.localhost:${P}/`],
  ['contacts', `http://contacts.localhost:${P}/`],
  ['files',    `http://files.localhost:${P}/`],
  // detail: open the model picker modal (brand colours, image models, newest-only toggle)
  ['models', `http://aide.localhost:${P}/`, async (page) => {
    await page.click('#model-btn').catch(() => {});
    await wait(900);
  }],
];

const browser = await puppeteer.launch({
  executablePath: await findChrome(),
  headless: 'new',
  userDataDir: mkdtempSync(join(tmpdir(), 'alles-shot-')),
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-color-profile=srgb'],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1230, deviceScaleFactor: 1 });
  await page.setCacheEnabled(false);
  for (const [name, url, fn] of SHOTS) {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await wait(3200);                       // SPA boots + paints (never networkidle — system polls)
    await applyTheme(page, THEME);          // force the chosen theme (default dark) before the shot
    await wait(400);
    if (fn) await fn(page);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    console.log('saved', name);
  }
} finally {
  await browser.close();
}
