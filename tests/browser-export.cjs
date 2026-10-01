// Optional browser acceptance check. Install Playwright separately to run it.
// Usage: node tests/browser-export.cjs [playwright module path] [Chrome executable]
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.argv[2] || 'playwright');

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.argv[3] ? {executablePath:process.argv[3]} : {})});
  try {
    const context = await browser.newContext({acceptDownloads:true});
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8765');
    await page.getByRole('button', {name:'Explorar ejemplo →'}).click();
    await page.waitForFunction(() => document.querySelector('#rows-stat').textContent === '240');
    const pending = page.waitForEvent('download');
    await page.getByRole('button', {name:'↓ Guardar proyecto'}).click();
    const download = await pending;
    const destination = path.resolve('artifacts', 'browser-project.json');
    await fs.mkdir(path.dirname(destination), {recursive:true});
    await download.saveAs(destination);
    const project = JSON.parse(await fs.readFile(destination, 'utf8'));
    assert.equal(project.version, 1);
    assert.equal(project.data.rows.length, 240);
    assert.equal(project.data.columns.length, 7);
    const other = await browser.newContext();
    const restored = await other.newPage();
    await restored.goto('http://127.0.0.1:8765');
    await restored.locator('#project-file').setInputFiles(destination);
    await restored.waitForFunction(() => document.querySelector('#rows-stat').textContent === '240');
    console.log('PASS: real browser download and restore, 240 rows and 7 variables.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
