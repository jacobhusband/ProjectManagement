// NODE_PATH can point at the bundled runtime, as in notes_editor.browser.cjs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
function extract(name) {
  const match = source.match(new RegExp(`^function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0];
}

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  try {
    const context = await browser.newContext({ bypassCSP: true, viewport: { width: 1000, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>|<link\b[^>]*>/gi, ''));
    for (const file of ['styles.css', 'industry.css', 'modern-workspace.css', 'deliverables-workspace.css']) {
      await page.addStyleTag({ path: path.join(root, file) });
    }
    const names = ['el', 'createIcon', 'val', 'normalizePinnedProjectOrder', 'normalizePinnedDeliverableOrder',
      'isDeliverablePinned', 'createWorkItemPinButton', 'addDeliverableCard', 'refreshModalDeliverableSummary',
      'toggleModalDeliverableCard', 'buildStatusPicker', 'readStatusPickerFrom', 'getModalDeliverableTaskItems',
      'getModalDeliverableNoteItems', 'addRefRowFrom', 'readForm', 'fillForm', 'onSaveProject', 'closeDlg'];
    await page.addScriptTag({ content: `
      ${source.match(/^const PIN_ICON_PATH =[\s\S]*?;/m)[0]}
      ${source.match(/^const STATUS_CANON =[\s\S]*?;/m)[0]}
      const LABEL_TO_KEY = {}, savedProjects = [];
      let db = [], editIndex = 0, _aiMatchSnapshot = null, openAttachmentPanelContext = null;
      const normalizeProject = project => structuredClone(project);
      const normalizeDeliverable = deliverable => structuredClone(deliverable);
      const normalizeLightingSchedule = value => value;
      const normalizeTitle24 = value => value;
      const createDefaultLightingSchedule = () => ({});
      const createDefaultTitle24 = () => ({});
      const normalizeProjectPath = value => value;
      const normalizeWindowsPath = value => value;
      const normalizeTask = value => structuredClone(value);
      const normalizeDeliverableNoteItems = value => value || [];
      const normalizeDeliverableNoteItem = value => structuredClone(value);
      const buildDeliverableNotesText = () => '';
      const getProjectDeliverables = project => project.deliverables;
      const getModalProjectDraft = () => document.getElementById('deliverableList')._projectDraft;
      const setModalProjectDraft = project => { document.getElementById('deliverableList')._projectDraft = project; };
      const getModalProjectAttachments = () => getModalProjectDraft().attachments || [];
      const getModalProjectLinks = () => getModalProjectDraft().links || [];
      const syncDeliverableAttachmentFields = () => {};
      const setDeliverableCardAttachments = (card, items) => { card._attachmentItems = items || []; };
      const getDeliverableCardAttachments = card => card._attachmentItems;
      const renderModalDeliverableTaskList = () => {};
      const getActiveDiscipline = () => 'Electrical';
      const parseDueStr = value => value ? new Date(value) : null;
      const getHardDueStr = deliverable => deliverable.hardDue || '';
      const getActiveDueField = deliverable => deliverable.hardDue ? 'hardDue' : deliverable.due ? 'due' : '';
      const getDueBadgeStateClass = () => 'upcoming';
      const describeDeliverableDue = () => 'Hard due date';
      const createDueKindTag = () => el('span', { textContent: 'HARD ' });
      const humanDate = value => value;
      const compareDeliverablesByDueDesc = () => 0;
      const isFinished = deliverable => (deliverable.statuses || []).includes('Complete');
      const validateAllDueDates = () => true;
      const flushModalEmailSession = () => {};
      const toast = () => {};
      const render = () => {};
      const save = () => { savedProjects.push(structuredClone(db)); };
      ${names.map(extract).join('\n')}
      window.openPinTestProject = (deliverables) => {
        db = [{ id: 'PIN-TEST', name: 'Pin test', deliverables }];
        editIndex = 0;
        fillForm(db[0]);
        const dlg = document.getElementById('editDlg');
        dlg.dataset.mode = 'full';
        dlg.showModal();
      };
      document.getElementById('btnSaveProject').addEventListener('click', onSaveProject);
      document.querySelector('#editDlg [data-close-dialog]').addEventListener('click', () => closeDlg('editDlg'));
      document.getElementById('appLoader').remove();
    ` });
    const fixture = (pinned, pinnedOrder = null) => ({
      id: 'deliverable-1', name: 'MEP information', pinned, pinnedOrder, hardDue: '10/07/2026',
      statuses: ['In progress'], tasks: [{ text: 'Existing task', done: false }],
      noteItems: [{ text: 'Existing note', pinned: true }], attachments: [],
    });
    const card = page.locator('#deliverableList .deliverable-card').first();
    const pin = card.locator('.deliverable-summary-pin');
    const summary = card.locator('.deliverable-card-summary');
    const isExpanded = () => card.evaluate(node => node.classList.contains('is-expanded'));

    // Pinning an existing unpinned deliverable stays in the draft until Save Changes.
    await page.evaluate(deliverables => openPinTestProject(deliverables), [fixture(false)]);
    assert.equal(await pin.getAttribute('aria-pressed'), 'false');
    await pin.click();
    assert.equal(await pin.textContent(), 'Unpin');
    assert.equal(await pin.getAttribute('aria-pressed'), 'true');
    assert.equal(await isExpanded(), true);
    assert.equal(await page.evaluate(() => db[0].deliverables[0].pinned), false);
    await page.locator('#btnSaveProject').click();
    assert.equal(await page.evaluate(() => savedProjects.at(-1)[0].deliverables[0].pinned), true);
    await page.evaluate(() => { fillForm(db[0]); document.getElementById('editDlg').showModal(); });
    assert.equal(await pin.getAttribute('aria-label'), 'Unpin deliverable');
    await page.locator('#editDlg [data-close-dialog]').click();

    // Unpinning must override the original pin and clear its manual order.
    await page.evaluate(deliverables => openPinTestProject(deliverables), [fixture(true, 4)]);
    assert.equal(await card.getAttribute('data-pinned-order'), '4');
    await pin.click();
    assert.equal(await pin.textContent(), 'Pin');
    assert.equal(await card.getAttribute('data-pinned-order'), '');
    await page.locator('#btnSaveProject').click();
    const unpinned = await page.evaluate(() => savedProjects.at(-1)[0].deliverables[0]);
    assert.equal(unpinned.pinned, false);
    assert.equal(unpinned.pinnedOrder, null);
    assert.equal(unpinned.tasks[0].text, 'Existing task');
    assert.equal(unpinned.noteItems[0].text, 'Existing note');

    // Cancel discards the change, while an untouched pin retains its order on save.
    await page.evaluate(deliverables => openPinTestProject(deliverables), [fixture(true, 4)]);
    await pin.click();
    await page.locator('#editDlg [data-close-dialog]').click();
    await page.evaluate(() => { fillForm(db[0]); document.getElementById('editDlg').showModal(); });
    assert.equal(await pin.getAttribute('aria-pressed'), 'true');
    await page.locator('#btnSaveProject').click();
    assert.equal(await page.evaluate(() => savedProjects.at(-1)[0].deliverables[0].pinnedOrder), 4);

    // Native Enter/Space button activation must not trigger the summary's toggle.
    await page.evaluate(deliverables => openPinTestProject(deliverables), [fixture(false), { ...fixture(false), id: 'deliverable-2' }]);
    await summary.focus();
    await page.keyboard.press('Enter');
    assert.equal(await isExpanded(), false);
    await pin.focus();
    await page.keyboard.press('Enter');
    assert.equal(await pin.getAttribute('aria-pressed'), 'true');
    assert.equal(await isExpanded(), false);
    await page.keyboard.press('Space');
    assert.equal(await pin.getAttribute('aria-pressed'), 'false');
    assert.equal(await isExpanded(), false);
    await page.locator('#deliverableList .deliverable-card').nth(1).locator('.deliverable-summary-pin').click();
    await page.locator('#btnSaveProject').click();
    assert.deepEqual(await page.evaluate(() => db[0].deliverables.map(d => d.pinned)), [false, true]);

    // A deliverable added in this edit session can be pinned before its first save.
    await page.evaluate(() => { fillForm(db[0]); document.getElementById('editDlg').showModal(); });
    await page.evaluate(deliverable => addDeliverableCard(deliverable, { insertAtTop: true }), { ...fixture(false), id: 'new-deliverable' });
    await pin.click();
    await page.locator('#btnSaveProject').click();
    assert.equal(await page.evaluate(() => db[0].deliverables.find(d => d.id === 'new-deliverable').pinned), true);

    assert.deepEqual(errors, []);
    console.log('Project modal pin: save, reopen, unpin, cancel, order preservation and keyboard checks passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
