// Run with Playwright on NODE_PATH and PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH if needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const shell = fs.readFileSync(path.join(root, 'industry-shell.js'), 'utf8');
const extract = (text, name) => {
  const match = text.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    const context = await browser.newContext({ bypassCSP: true, viewport: { width: 1440, height: 1000 } });
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
    await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ''));
    for (const name of ['styles.css', 'industry.css', 'modern-workspace.css']) {
      await page.addStyleTag({ content: fs.readFileSync(path.join(root, name), 'utf8') });
    }
    await page.addScriptTag({ content: `
      let calls = [], toasts = [], exportResult = { status: 'success', path: 'C:/Transfer/ACIES-data.zip' };
      let importResult = { status: 'cancelled' }, holdTransfer = false, releaseTransfer;
      let saveOk = true, releaseWrite, rawWrites = 0;
      const toast = message => toasts.push(message);
      const flushPageSave = async () => saveOk;
      const flushPendingProjectSave = async () => saveOk;
      const noop = { flush() {} };
      const debouncedSaveUserSettings = noop, debouncedSaveActivityHistory = noop,
        debouncedSaveChecklists = noop, debouncedSaveLightingSchedule = noop, debouncedSaveTitle24 = noop;
      window.pywebview = { api: {
        save_tasks: async () => { rawWrites++; await new Promise(resolve => releaseWrite = resolve); return { status: 'success' }; },
        export_app_data: async () => { calls.push('export'); if (holdTransfer) await new Promise(resolve => releaseTransfer = resolve); return exportResult; },
        import_app_data: async () => { calls.push('import'); return importResult; }
      } };
      ${extract(source, 'el')}
      ${extract(shell, 'installModernWorkspaceDialogs')}
      ${source.slice(source.indexOf('let dataTransferBusy = false;'), source.indexOf('function createId('))}
      initializeDataTransferWriteTracking();
      installModernWorkspaceDialogs();
      document.getElementById('appLoader').remove();
      document.getElementById('settingsDlg').showModal();
      [...document.querySelectorAll('.settings-navigation button')].find(button => button.textContent === 'Maintenance').click();
      document.getElementById('settings_exportDataBtn').onclick = () => runDataTransfer('export');
      document.getElementById('settings_importDataBtn').onclick = () => runDataTransfer('import');
    ` });
    const exportButton = page.getByRole('button', { name: 'Export data', exact: true });
    const importButton = page.getByRole('button', { name: 'Import data', exact: true });
    assert.equal(await exportButton.isVisible(), true);
    assert.equal(await importButton.isVisible(), true);
    assert.equal(await page.locator('#headerGoogleAuthBtn').count(), 0);
    assert.equal(await page.locator('#headerDisciplineSwitcher').count(), 1);
    if (process.env.DATA_TRANSFER_SCREENSHOT) await page.screenshot({ path: process.env.DATA_TRANSFER_SCREENSHOT });

    await exportButton.click();
    await page.waitForFunction(() => !dataTransferBusy);
    assert.match(await page.locator('#settings_dataTransferStatus').innerText(), /Export saved: C:\/Transfer/);
    assert.equal(await importButton.isEnabled(), true);

    await importButton.click();
    await page.waitForFunction(() => !dataTransferBusy);
    assert.match(await page.locator('#settings_dataTransferStatus').innerText(), /cancelled/);
    assert.equal(await page.locator('#dataTransferBusyDlg').evaluate(node => node.open), false);

    await page.evaluate(() => { exportResult = { status: 'error', message: 'Disk is full' }; });
    await exportButton.click();
    await page.waitForFunction(() => !dataTransferBusy);
    assert.equal(await page.locator('#settings_dataTransferStatus').innerText(), 'Disk is full');
    assert.equal(await exportButton.isEnabled(), true);

    await page.evaluate(() => { calls = []; saveOk = false; });
    await exportButton.click();
    await page.waitForFunction(() => !dataTransferBusy);
    assert.deepEqual(await page.evaluate(() => calls), [], 'a failed note save must stop the snapshot');

    await page.evaluate(() => {
      saveOk = true; holdTransfer = true;
      exportResult = { status: 'success', path: 'C:/Transfer/data.zip' };
      void window.pywebview.api.save_tasks([]);
      void runDataTransfer('export');
    });
    await page.waitForFunction(() => typeof releaseWrite === 'function');
    assert.deepEqual(await page.evaluate(() => calls), [], 'export waits for the already-running write');
    await page.evaluate(() => releaseWrite());
    await page.waitForFunction(() => typeof releaseTransfer === 'function');
    assert.equal(await importButton.isDisabled(), true);
    assert.equal(await page.evaluate(() => dataTransferWritesPaused), true);
    assert.equal(await page.evaluate(async () => (await window.pywebview.api.save_tasks([])).status), 'error');
    assert.equal(await page.evaluate(() => rawWrites), 1, 'late writes cannot reach the backend');
    await page.evaluate(() => { void runDataTransfer('import'); releaseTransfer(); });
    await page.waitForFunction(() => !dataTransferBusy);
    assert.deepEqual(await page.evaluate(() => calls), ['export'], 'transfers cannot overlap');
    assert.equal(await page.evaluate(() => dataTransferWritesPaused), false);
    assert.deepEqual(errors, []);
    console.log('PASS: Settings placement, export, cancellation, save draining, errors, and late-write protection.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
