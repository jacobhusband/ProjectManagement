// NODE_PATH may point at the bundled runtime's node_modules.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const extract = name => {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
};

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  try {
    const context = await browser.newContext({ bypassCSP: true, viewport: { width: 1298, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>|<link\b[^>]*>/gi, ''));
    for (const file of ['styles.css', 'industry.css', 'modern-workspace.css', 'deliverables-workspace.css']) {
      await page.addStyleTag({ path: path.join(root, file) });
    }
    await page.addScriptTag({ content: `
      let currentTimesheetWeek = new Date(2026, 9, 5);
      let timesheetDb = { weeks: {}, expenses: {} };
      const saves = [], openedFiles = [], messages = [];
      const toast = message => messages.push(message);
      const normalizeIsoTimestamp = value => value;
      let failSave = false, holdSave = false, releaseSave, releaseSlowPreview;
      function receipt(total, title) {
        const canvas = document.createElement('canvas');
        canvas.width = 600; canvas.height = 1200;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 600, 1200);
        ctx.fillStyle = '#222'; ctx.font = 'bold 36px monospace';
        ctx.fillText(title, 50, 95);
        ctx.font = '24px monospace';
        ctx.fillText('October 6, 2026', 50, 145);
        for (let i = 0; i < 8; i++) ctx.fillText('Receipt item ' + (i + 1), 50, 240 + i * 70);
        ctx.font = 'bold 38px monospace'; ctx.fillText('TOTAL  $' + total, 50, 1010);
        return { status: 'success', dataUrl: canvas.toDataURL(), width: 600, height: 1200 };
      }
      const receiptA = receipt('33.38', 'THE HENRY');
      const receiptB = receipt('20.99', 'UBER');
      window.pywebview = { api: {
        get_expense_image_preview: async (file, size) => {
          if (file === 'missing.png') return { status: 'error', message: 'Image file not found.' };
          if (file === 'slow.png' && size === 1800) await new Promise(resolve => { releaseSlowPreview = resolve; });
          return { ...(file === 'uber.png' ? receiptB : receiptA), path: file };
        },
        resolve_expense_attachment_path: async file => ({ status: 'success', path: file }),
        open_path: async file => { openedFiles.push(file); return { status: 'success' }; },
        select_expense_images: async () => ({ status: 'success', paths: ['new-receipt.png'] }),
        save_timesheets: async data => {
          if (failSave) return { status: 'error', message: 'Disk unavailable' };
          const snapshot = structuredClone(data);
          if (holdSave) await new Promise(resolve => { releaseSave = resolve; });
          saves.push(snapshot);
          return { status: 'success' };
        },
      } };
      ${['el', 'getWeekStartDate', 'formatWeekKey', 'showDialog', 'closeDlg', 'getDeclarativeClickAction', 'handleDeclarativeClick', 'saveTimesheets'].map(extract).join('\n')}
      ${source.slice(source.indexOf('// ===================== EXPENSE SHEET FUNCTIONS'), source.indexOf('function createIcon('))}
      document.addEventListener('click', handleDeclarativeClick, true);
      initExpenseEntryEditor(); initImagePreviewDialog();
      document.getElementById('appLoader').remove();
      window.fixture = () => {
        const projects = [{
          id: 'project-1', projectName: 'Shops at Crystals - Space 207, Las Vegas, NV', projectId: '261301',
          entries: [{ id: 'original', date: '2026-10-06', description: 'Lunch at The Henry', expense: 30, mileage: 12, extra: 'preserve me' }],
          images: [
            { id: 'a', filename: 'Lunch receipt.png', path: 'lunch.png' },
            { id: 'b', filename: 'Uber receipt.png', path: 'uber.png' },
            { id: 'c', filename: 'Receipt.pdf', path: 'receipt.pdf' },
            { id: 'd', filename: 'Missing receipt.png', path: 'missing.png' },
            { id: 'e', filename: 'Slow receipt.png', path: 'slow.png' },
          ],
        }, { id: 'custom', source: 'custom', projectName: 'Custom expense', entries: [], images: [] }];
        setWeekExpenses(formatWeekKey(currentTimesheetWeek), projects); renderExpenses();
      };
      fixture();
    ` });
    const dlg = page.locator('#addExpenseEntryDlg');
    const amount = page.locator('#exp_amount');
    const description = page.locator('#exp_description');
    const save = page.locator('#btnSaveExpenseEntry');
    const close = () => dlg.getByRole('button', { name: 'Close', exact: true }).click();
    const entries = () => page.evaluate(() => getWeekExpenses('2026-10-04')[0].entries);
    const waitImage = () => page.waitForFunction(() => !document.getElementById('expenseReceiptImg').hidden);

    // Thumbnail opens an editable receipt workspace; selecting an existing entry preserves its ID and metadata.
    await page.evaluate(() => document.querySelector('.expense-image-preview-btn').click());
    await waitImage();
    assert.equal(await dlg.isVisible(), true);
    const imageBounds = await page.locator('#expenseReceiptStage').boundingBox();
    const fieldBounds = await amount.boundingBox();
    assert.ok(fieldBounds.x > imageBounds.x + imageBounds.width, 'receipt and amount appear side by side');
    await page.locator('#expenseEntrySelect').selectOption('0');
    assert.equal(await amount.inputValue(), '30');
    await amount.fill('33.38');
    await save.click();
    await page.waitForFunction(() => document.getElementById('expenseEntrySaveStatus').textContent.startsWith('Saved'));
    assert.equal(await dlg.isVisible(), true, 'saving keeps the receipt open');
    assert.equal((await entries()).length, 1);
    assert.equal((await entries())[0].expense, 33.38);
    assert.equal((await entries())[0].id, 'original');
    assert.equal((await entries())[0].extra, 'preserve me');
    assert.equal(await page.locator('#expenseGrandTotal').textContent(), '$42.08');
    assert.equal(await page.evaluate(() => saves.at(-1).expenses['2026-10-04'].projects[0].entries[0].expense), 33.38);

    // Receipt navigation retains the active draft. Switching entry selection also retains unsaved field values.
    await amount.fill('34.25');
    await page.locator('#expenseReceiptNextBtn').click();
    await page.waitForFunction(() => document.getElementById('expenseReceiptImg').alt === 'Uber receipt.png');
    assert.equal(await amount.inputValue(), '34.25');
    await page.locator('#expenseEntrySelect').selectOption('new');
    await description.fill('Uber ride to airport');
    await amount.fill('20.99');
    await page.locator('#expenseEntrySelect').selectOption('0');
    assert.equal(await amount.inputValue(), '34.25');
    await page.locator('#expenseEntrySelect').selectOption('new');
    assert.equal(await amount.inputValue(), '20.99');
    assert.equal(await description.inputValue(), 'Uber ride to airport');

    // Save & Next creates exactly one entry and resets the new-entry fields for the next receipt.
    await page.locator('#exp_date').fill('2026-10-06');
    await page.locator('#expenseEntrySaveNextBtn').click();
    await page.waitForFunction(() => document.getElementById('expenseReceiptPosition').textContent === '3 of 5');
    assert.equal((await entries()).length, 2);
    assert.equal((await entries())[1].expense, 20.99);
    assert.equal(await amount.inputValue(), '');
    assert.equal(await description.inputValue(), '');
    assert.equal(await page.locator('#exp_date').inputValue(), '2026-10-06');
    assert.equal(await page.locator('#expenseReceiptZoomInBtn').isDisabled(), true);
    await page.locator('#expenseReceiptOpenBtn').click();
    assert.deepEqual(await page.evaluate(() => openedFiles), ['receipt.pdf']);
    assert.equal(await dlg.isVisible(), true);

    // Missing previews keep the editor usable. Closing/Escape discard unsaved data.
    await page.locator('#expenseReceiptNextBtn').click();
    await page.waitForFunction(() => document.getElementById('expenseReceiptStatus').textContent.includes('Image file not found'));
    await amount.fill('99');
    await close();
    await page.waitForFunction(() => expenseEntryEditorState === null);
    assert.equal((await entries()).length, 2);
    await page.evaluate(() => openExpenseEntryEditor(0, 1, 0));
    await waitImage();
    assert.equal(await amount.inputValue(), '33.38');
    await amount.fill('45');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => expenseEntryEditorState === null);
    assert.equal((await entries())[0].expense, 33.38);

    // Late image responses cannot replace the latest receipt or reopen a dismissed editor.
    await page.evaluate(() => openExpenseEntryEditor(0, 4));
    await page.waitForFunction(() => typeof releaseSlowPreview === 'function');
    await page.locator('#expenseReceiptThumbnails button').nth(1).click();
    await waitImage();
    await page.evaluate(() => releaseSlowPreview());
    await page.waitForFunction(() => expenseAttachmentPreviewCache.get('1800:slow.png')?.status === 'success');
    assert.equal(await page.locator('#expenseReceiptImg').getAttribute('alt'), 'Uber receipt.png');
    assert.equal(await page.locator('#expenseReceiptPosition').textContent(), '2 of 5');

    // Button and wheel zoom, drag-to-pan, fit, and viewport resizing share the established viewer behavior.
    await page.locator('#expenseReceiptZoomInBtn').click();
    assert.ok(await page.evaluate(() => imagePreviewState.scale > 1));
    const stage = await page.locator('#expenseReceiptStage').boundingBox();
    await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2);
    await page.mouse.wheel(0, -120);
    await page.waitForFunction(() => imagePreviewState.scale > 1.4);
    await page.mouse.down(); await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2 + 60); await page.mouse.up();
    assert.ok(await page.evaluate(() => imagePreviewState.translateY > 0));
    await page.locator('#expenseReceiptFitBtn').click();
    assert.equal(await page.evaluate(() => imagePreviewState.scale), 1);

    if (process.env.EXPENSE_EDITOR_SCREENSHOT_DIR) {
      fs.mkdirSync(process.env.EXPENSE_EDITOR_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.EXPENSE_EDITOR_SCREENSHOT_DIR, 'expense-editor-desktop.png') });
    }

    // A failed backend save leaves both the draft and original record intact, and does not advance receipts.
    await page.locator('#expenseEntrySelect').selectOption('0');
    await amount.fill('50');
    await page.evaluate(() => { failSave = true; });
    await page.locator('#expenseEntrySaveNextBtn').click();
    await page.waitForFunction(() => document.getElementById('expenseEntrySaveStatus').textContent.startsWith('Could not save'));
    assert.equal((await entries())[0].expense, 33.38);
    assert.equal(await amount.inputValue(), '50');
    assert.equal(await page.locator('#expenseReceiptPosition').textContent(), '2 of 5');
    await page.evaluate(() => { failSave = false; });
    await close();
    await page.waitForFunction(() => expenseEntryEditorState === null);

    await page.evaluate(() => {
      expenseAttachmentPreviewCache.delete('1800:slow.png');
      releaseSlowPreview = null;
      openExpenseEntryEditor(0, 4);
    });
    await page.waitForFunction(() => typeof releaseSlowPreview === 'function');
    assert.equal(await page.locator('#expenseEntrySaveNextBtn').isDisabled(), true, 'last receipt has no next action');
    await close();
    await page.waitForFunction(() => expenseEntryEditorState === null);
    await page.evaluate(() => releaseSlowPreview());
    await page.waitForFunction(() => expenseAttachmentPreviewCache.get('1800:slow.png')?.status === 'success');
    assert.equal(await dlg.isVisible(), false);
    assert.equal(await page.locator('#expenseReceiptImg').getAttribute('src'), null);

    // A failed new-entry save can be retried without creating a duplicate; fields lock during a pending save.
    await page.evaluate(() => { openExpenseEntryEditor(0); failSave = true; });
    await amount.fill('8');
    await save.click();
    await page.waitForFunction(() => document.getElementById('expenseEntrySaveStatus').textContent.startsWith('Could not save'));
    assert.equal((await entries()).length, 2);
    assert.equal(await amount.inputValue(), '8');
    await page.evaluate(() => { failSave = false; holdSave = true; });
    await save.click();
    await page.waitForFunction(() => typeof releaseSave === 'function');
    assert.equal(await amount.isDisabled(), true);
    assert.equal(await save.isDisabled(), true);
    await page.evaluate(() => saveExpenseEntry());
    assert.equal((await entries()).length, 3, 'a second save during persistence cannot insert another entry');
    await page.evaluate(() => { holdSave = false; releaseSave(); });
    await page.waitForFunction(() => document.getElementById('expenseEntrySaveStatus').textContent.startsWith('Saved'));
    assert.equal(await amount.isDisabled(), false);
    await close();
    await page.waitForFunction(() => expenseEntryEditorState === null);

    // Empty/custom projects keep a compact form, with normal validation and Enter-to-save.
    await page.evaluate(() => openAddExpenseEntryDialog(1));
    assert.equal(await page.locator('#expenseReceiptPanel').isVisible(), false);
    await amount.fill('-1');
    await save.click();
    assert.equal(await page.evaluate(() => getWeekExpenses('2026-10-04')[1].entries.length), 0);
    await amount.fill('12.50');
    await amount.press('Enter');
    await page.waitForFunction(() => !document.getElementById('addExpenseEntryDlg').open);
    assert.equal(await page.evaluate(() => getWeekExpenses('2026-10-04')[1].entries[0].expense), 12.5);
    await page.waitForFunction(() => expenseEntryEditorState === null);

    // Narrow viewports stack the receipt above reachable fields, with no horizontal overflow.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => openExpenseEntryEditor(0, 0, 0));
    await waitImage();
    await amount.scrollIntoViewIfNeeded();
    const dialogBounds = await dlg.boundingBox();
    const mobileAmount = await amount.boundingBox();
    assert.ok(dialogBounds.width <= 390 && mobileAmount.x >= dialogBounds.x);
    assert.ok(mobileAmount.x + mobileAmount.width <= dialogBounds.x + dialogBounds.width + 1);
    assert.ok(await page.locator('.expense-entry-workspace').evaluate(node => node.scrollWidth <= node.clientWidth + 1));
    await page.evaluate(() => document.documentElement.dataset.theme = 'light');
    if (process.env.EXPENSE_EDITOR_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.EXPENSE_EDITOR_SCREENSHOT_DIR, 'expense-editor-mobile-light.png') });
    }
    await close();
    await page.waitForFunction(() => expenseEntryEditorState === null);

    // Shared image preview still works for notes and other attachments after the expense workspace closes.
    await page.evaluate(() => openImagePreviewDialog({ ...receiptA, filename: 'Note image.png' }));
    await page.waitForFunction(() => imagePreviewState.baseWidth > 0);
    assert.equal(await page.locator('#imagePreviewDlg').isVisible(), true);
    assert.equal(await page.locator('#imagePreviewImg').getAttribute('alt'), 'Note image.png');
    await page.locator('#imagePreviewCloseBtn').click();
    await page.waitForFunction(() => !document.getElementById('imagePreviewDlg').open);

    await page.evaluate(() => { failSave = true; return addExpenseImages(0); });
    assert.equal(await page.evaluate(() => getWeekExpenses('2026-10-04')[0].images.length), 5);
    assert.equal(await dlg.isVisible(), false, 'failed attachment saves do not open the editor');

    // Attaching images takes the user directly to the first newly attached receipt.
    await page.evaluate(() => { failSave = false; return addExpenseImages(0); });
    await waitImage();
    assert.equal(await dlg.isVisible(), true);
    assert.equal(await page.locator('#expenseReceiptFilename').textContent(), 'new-receipt.png');
    assert.equal(await page.locator('#expenseReceiptPosition').textContent(), '6 of 6');
    await close();

    assert.deepEqual(errors, []);
    console.log('Expense receipt editor: edit/add, totals, persistence, drafts, navigation, save failures, zoom/pan, PDF/missing previews, keyboard and responsive checks passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
