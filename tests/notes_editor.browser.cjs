// Run after building project-pages-editor. NODE_PATH can point at the bundled runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setContent('<html data-theme="dark"><body><div class="page-view-scroll" style="height:800px;overflow:auto"><div id="root"></div></div></body></html>');
    for (const file of ['styles.css', 'project-pages-editor/dist/project-pages-editor-project-pages-editor.css']) {
      await page.addStyleTag({ path: path.join(root, file) });
    }
    await page.addScriptTag({ path: path.join(root, 'project-pages-editor/dist/project-pages-editor.js') });
    await page.evaluate(() => {
      window.saved = {};
      window.pages = {
        A: '<p>Alpha notes</p>',
        B: '<p>Beta notes</p>',
        C: '<p><span style="color:black"><strong>Dark text</strong></span> <a href="https://example.com">link</a></p>',
      };
      window.openTestPage = (id) => window.ProjectPagesEditor.setDocument({
        documentKey: id, title: id, kind: 'project', project: { id: 'project', name: 'Test project' },
        html: saved[id] || pages[id],
        navigationPages: [{ id: 'A', title: 'Parent', depth: 0 }, { id: 'B', title: 'Child', depth: 1 }],
        trashEntries: [{ id: 'trash', title: 'Deleted page', count: 1 }],
        onRestoreTrash: (id) => { window.restored = id; },
        onHtmlChange: (html) => { saved[id] = html; },
        onSaveAsset: () => new Promise((resolve) => { window.finishUpload = resolve; }),
        onToast: (message) => { window.lastToast = message; },
      });
      ProjectPagesEditor.mount(document.getElementById('root'));
      openTestPage('A');
    });
    const editor = page.locator('#pageEditor');
    await editor.waitFor();
    await editor.click();
    await page.keyboard.press('Control+End');
    await page.keyboard.type(' edited');
    await page.evaluate(async () => { await ProjectPagesEditor.flushSave(); openTestPage('B'); });
    await page.waitForFunction(() => document.querySelector('#pageEditor')?.textContent === 'Beta notes');
    await editor.click();
    await page.keyboard.press('Control+z');
    assert.equal(await editor.textContent(), 'Beta notes', 'Undo must not restore page A');

    await page.evaluate(() => openTestPage('C'));
    await page.waitForFunction(() => document.querySelector('#pageEditor')?.textContent.includes('Dark text'));
    await editor.click();
    await page.keyboard.press('Control+a');
    await page.getByRole('button', { name: 'Reset text color', exact: true }).click();
    assert.equal(await editor.locator('[style*="color"]').count(), 0);
    assert.equal(await editor.locator('strong').textContent(), 'Dark text');
    assert.equal(await editor.locator('a').getAttribute('href'), 'https://example.com');
    await page.getByRole('button', { name: 'Clear formatting', exact: true }).click();
    assert.equal(await editor.locator('strong').count(), 0);
    assert.equal(await editor.locator('a').count(), 1, 'Clear formatting preserves links');

    await editor.click();
    await page.keyboard.press('Control+End');
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.setData('text/html', '<p style="color:#000;background:white"><strong>Email text</strong> <a href="https://example.org">email link</a></p>');
      document.querySelector('#pageEditor').dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data }));
    });
    assert.equal(await editor.locator('[style*="color"]').count(), 0);
    assert.ok((await editor.textContent()).includes('Email text'));
    assert.equal(await editor.locator('strong').textContent(), 'Email text');

    // An upload retains its insertion point even if the caret is moved, and flush waits.
    await page.evaluate(() => openTestPage('A'));
    await page.waitForFunction(() => document.querySelector('#pageEditor')?.textContent.includes('Alpha'));
    await editor.click();
    await page.keyboard.press('Control+Home');
    await page.waitForFunction(() => getSelection().anchorOffset === 0);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.evaluate(() => {
      const data = new DataTransfer();
      data.items.add(new File([new Uint8Array([137,80,78,71])], 'test.png', { type: 'image/png' }));
      document.querySelector('#pageEditor').dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data }));
    });
    await page.waitForFunction(() => typeof finishUpload === 'function');
    await page.keyboard.press('Control+End');
    await page.evaluate(() => {
      window.didFlush = false;
      window.flushing = ProjectPagesEditor.flushSave().then(() => { window.didFlush = true; openTestPage('B'); });
    });
    assert.equal(await page.evaluate(() => didFlush), false);
    await page.evaluate(async () => {
      finishUpload({ status: 'success', assetPath: 'assets/test.png' });
      await flushing;
    });
    await page.waitForFunction(() => document.querySelector('#pageEditor')?.textContent === 'Beta notes');
    assert.equal(await editor.locator('img').count(), 0, 'Image must not leak into B');
    const savedA = await page.evaluate(() => saved.A);
    assert.ok(savedA.includes('assets/test.png'));
    assert.ok(savedA.indexOf('<img') < savedA.indexOf('Alpha'), `Upload keeps original insertion point: ${savedA}`);

    await page.getByRole('button', { name: 'Collapse Parent' }).click();
    await page.getByRole('button', { name: 'Child', exact: true }).waitFor({ state: 'hidden' });
    await page.getByRole('searchbox', { name: 'Filter pages' }).fill('Child');
    await page.getByRole('button', { name: 'Child', exact: true }).waitFor();
    await page.locator('.notes-trash summary').click();
    await page.getByRole('button', { name: 'Restore Deleted page' }).click();
    assert.equal(await page.evaluate(() => restored), 'trash');

    // Color buttons are operable by keyboard and use contrasting theme tokens.
    await editor.click();
    await page.keyboard.press('Control+a');
    await page.getByRole('button', { name: 'Color', exact: true }).click();
    const swatch = page.getByRole('option', { name: 'Text color: Blue', exact: true });
    await swatch.focus();
    await page.keyboard.press('Enter');
    assert.ok(await editor.locator('[style*="--notes-color-blue"]').count());
    for (const theme of ['dark', 'light']) {
      await page.evaluate((theme) => document.documentElement.dataset.theme = theme, theme);
      const colors = await editor.locator('[style*="--notes-color-blue"]').first().evaluate((node) => ({ color: getComputedStyle(node).color, bg: getComputedStyle(document.documentElement).getPropertyValue('--bg') }));
      assert.ok(colors.color.startsWith('rgb('));
      const contrast = await page.evaluate(() => {
        const probe = document.createElement('span');
        document.body.append(probe);
        const luminance = (rgb) => {
          const values = rgb.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => {
            v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
          });
          return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
        };
        probe.style.color = 'var(--bg)';
        const background = luminance(getComputedStyle(probe).color);
        const ratios = ['gray','brown','orange','yellow','green','blue','purple','pink','red'].map(name => {
          probe.style.color = `var(--notes-color-${name})`;
          const text = luminance(getComputedStyle(probe).color);
          return (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05);
        });
        probe.remove();
        return Math.min(...ratios);
      });
      assert.ok(contrast >= 4.5, `${theme} palette contrast ${contrast}`);
    }
    await page.evaluate(() => {
      document.documentElement.dataset.theme = 'dark';
      pages.Long = '<h2>Project coordination</h2>' + '<p>Coordination notes and decisions.</p>'.repeat(150);
      openTestPage('Long');
    });
    await page.waitForFunction(() => document.querySelector('#pageEditor')?.textContent.includes('Project coordination'));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.locator('.page-view-scroll').evaluate(node => { node.scrollTop = 1100; node.dispatchEvent(new Event('scroll')); });
    await page.evaluate(async () => { await ProjectPagesEditor.flushSave(); openTestPage('B'); });
    await page.waitForFunction(() => document.querySelector('#pageTitle')?.textContent === 'B');
    await page.evaluate(() => openTestPage('Long'));
    await page.waitForFunction(() => document.querySelector('.page-view-scroll').scrollTop === 1100);
    await page.evaluate(() => openTestPage('B'));
    await page.waitForFunction(() => document.querySelector('#pageTitle')?.textContent === 'B');
    await editor.click();
    await page.keyboard.press('Control+End');
    await page.keyboard.press('Enter');
    await page.keyboard.type('/excel');
    await page.keyboard.press('Enter');
    await page.getByRole('dialog', { name: 'Add Excel workbook' }).waitFor();
    await page.waitForFunction(() => document.activeElement?.tagName === 'INPUT' && !!document.activeElement.closest('[role="dialog"]'));
    const dialogButtons = page.getByRole('dialog').locator('button:not(:disabled)');
    await dialogButtons.first().focus();
    await page.keyboard.press('Shift+Tab');
    assert.ok(await dialogButtons.last().evaluate(node => node === document.activeElement));
    await page.keyboard.press('Tab');
    assert.ok(await dialogButtons.first().evaluate(node => node === document.activeElement));
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    if (process.env.NOTES_SCREENSHOT) await page.screenshot({ path: process.env.NOTES_SCREENSHOT });
    assert.deepEqual(errors, []);
    console.log('Notes browser checks passed: undo isolation, formatting, paste, delayed uploads, sidebar, trash controls, keyboard colors.');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
