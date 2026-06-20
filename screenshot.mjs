// screenshot.mjs — quick visual capture for alles.
//   node screenshot.mjs http://docs.localhost:8890/            → temporary screenshots/screenshot-N.png
//   node screenshot.mjs http://docs.localhost:8890/ outline    → temporary screenshots/screenshot-N-outline.png
// uses puppeteer-core (installed in the prepared temp dir) driving the Playwright Chromium that's
// already on this box. fresh profile each run so a stale service worker can't serve old assets.
import { createRequire } from 'module';
import { existsSync, mkdirSync, readdirSync, mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { glob } from 'fs/promises';

const require = createRequire('C:/Users/jxh/AppData/Local/Temp/puppeteer-test/');
const puppeteer = require('puppeteer-core');

// find the Chromium that Playwright installed (version dir varies)
async function findChrome() {
  for await (const p of glob('C:/Users/jxh/AppData/Local/ms-playwright/chromium*/chrome-win64/chrome.exe')) return p;
  throw new Error('no Chromium found — run a Playwright test once to install it');
}

const url = process.argv[2];
const label = process.argv[3] ? '-' + process.argv[3].replace(/[^a-z0-9_-]/gi, '') : '';
if (!url) { console.error('usage: node screenshot.mjs <url> [label]'); process.exit(1); }

const OUT = join(process.cwd(), 'temporary screenshots');
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });
// next free index
let n = 1;
const used = new Set(readdirSync(OUT).map(f => { const m = f.match(/^screenshot-(\d+)/); return m ? +m[1] : 0; }));
while (used.has(n)) n++;
const file = join(OUT, `screenshot-${n}${label}.png`);

const browser = await puppeteer.launch({
  executablePath: await findChrome(),
  headless: 'new',
  userDataDir: mkdtempSync(join(tmpdir(), 'alles-shot-')),
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-color-profile=srgb'],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.setCacheEnabled(false);
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  // the SPA boots + polls async; give it time to paint, never wait for networkidle (system view polls forever)
  await new Promise(r => setTimeout(r, 3000));
  await page.screenshot({ path: file });
  console.log('saved', file);
} finally {
  await browser.close();
}
