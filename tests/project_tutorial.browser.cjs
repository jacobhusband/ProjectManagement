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
    page.on('pageerror', error => { errors.push(error.message); console.error(error.message); });
    page.setDefaultTimeout(8000);
    await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>|<link\b[^>]*>/gi, ''));
    for (const file of ['styles.css', 'industry.css', 'modern-workspace.css', 'deliverables-workspace.css']) {
      await page.addStyleTag({ path: path.join(root, file) });
    }
    const names = ['el', 'createIcon', 'val', 'normalizePinnedProjectOrder', 'normalizePinnedDeliverableOrder',
      'isDeliverablePinned', 'createWorkItemPinButton', 'addDeliverableCard', 'refreshModalDeliverableSummary',
      'toggleModalDeliverableCard', 'buildStatusPicker', 'readStatusPickerFrom', 'getModalDeliverableTaskItems',
      'getEffectiveDueStr', 'getLegacyDueDates', 'getModalDeliverableNoteItems', 'addRefRowFrom', 'readForm', 'fillForm', 'onSaveProject', 'closeDlg', 'openNew', 'clearModalFieldErrors', 'showModalFieldError', 'parseDueStr', 'getDeclarativeClickAction', 'handleDeclarativeClick'];
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
      const getActiveDueField = deliverable => deliverable.hardDue ? 'hardDue' : deliverable.due ? 'due' : '';
      const getDueBadgeStateClass = () => 'upcoming';
      const describeDeliverableDue = () => 'Due date';
      const humanDate = value => value;
      const compareDeliverablesByDueDesc = () => 0;
      const isFinished = deliverable => (deliverable.statuses || []).includes('Complete');
      const validateAllDueDates = () => true;
      const flushModalEmailSession = () => {};
      const toast = () => {};
      let failSave = false, deferSave = false, releaseSave;
      const render = () => {
        const tbody = document.getElementById('tbody');
        tbody.replaceChildren();
        for (const project of db) for (const deliverable of project.deliverables) {
          const row = document.createElement('tr');
          row.dataset.deliverableId = deliverable.id;
          row.innerHTML = '<td>' + deliverable.name + '</td>';
          row.addEventListener('click', () => {
            industryCommandDock.project = project; industryCommandDock.deliverable = deliverable;
            updateProjectTutorialSelection();
          });
          tbody.appendChild(row);
        }
      };
      const save = async () => {
        savedProjects.push(structuredClone(db));
        if (deferSave) await new Promise(resolve => releaseSave = resolve);
        return !failSave;
      };
      const beginModalEmailSession = () => {};
      let nextId = 0; const createId = prefix => prefix + '_' + ++nextId;
      const createDeliverable = () => ({ id: createId('dlv'), name: '', due: '', hardDue: '', tasks: [], noteItems: [], statuses: [] });
      const createBlankProject = () => ({ id: '', name: '', path: '', deliverables: [], refs: [] });
      let industryCommandDock = { project: null, deliverable: null, multi: [], input: document.createElement('input') };
      const dockRoot = document.createElement('div'); dockRoot.id = 'commandDock';
      industryCommandDock.input.className = 'cmd-search'; dockRoot.append(industryCommandDock.input); document.body.append(dockRoot);
      const autoFormatDateInput = () => {}, validateDueDateInput = () => {}, validateDeliverableDateOrder = () => {};
      ${source.slice(source.indexOf('let projectTutorial = null;'), source.indexOf('function showMainApp()'))}
      document.getElementById('quickNew').onclick = openNew;
      document.addEventListener('click', handleDeclarativeClick, true);
      document.getElementById('search').addEventListener('input', render);

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
      document.getElementById('appLoader').remove();
    ` });

    const panel = page.locator('#projectTutorial');
    const stage = expected => page.waitForFunction(value => document.getElementById('projectTutorial').dataset.stage === value, expected);
    async function start() {
      await page.evaluate(() => { db = []; startProjectTutorial(); });
      await stage('new');
      await page.locator('#quickNew').click();
      await stage('path');
      assert.equal(await panel.evaluate(node => node.parentElement.id), 'editDlg');
      await page.locator('#f_id').fill('TUTORIAL-1');
      await page.locator('#f_name').fill('Tutorial project');
    }
    await start();
    await page.locator('#btnSaveProject').click();
    await stage('path');
    assert.match(await page.locator('#projectTutorialError').textContent(), /folder path/);
    await page.locator('#f_path').fill('M:\\Projects\\Tutorial');
    await page.locator('#btnSaveProject').click();
    await stage('details');
    await page.locator('#projectTutorialNext').click();
    assert.match(await page.locator('#projectTutorialError').textContent(), /name and a valid due date/);
    await page.locator('.d-name').fill('DD90');
    await page.locator('.d-due').fill('11/30/2026');
    await page.setViewportSize({ width: 680, height: 700 });
    await page.evaluate(() => document.documentElement.dataset.theme = 'light');
    await page.screenshot({ path: path.join(root, 'tmp/tutorial-compact-light.png') });
    await page.setViewportSize({ width: 1000, height: 900 });
    await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
    await page.locator('#projectTutorialNext').click();
    await stage('save');
    assert.equal(await page.locator('#projectTutorialNext').isVisible(), false);
    await page.screenshot({ path: path.join(root, 'tmp/tutorial-form.png') });
    await page.evaluate(() => { deferSave = true; });
    await page.locator('#btnSaveProject').click();
    await stage('saving');
    assert.equal(await page.locator('#editDlg').evaluate(node => node.open), false);
    await page.evaluate(() => { deferSave = false; releaseSave(); });
    await stage('select');
    await page.locator('#tbody tr').click();
    await stage('publish');
    await page.locator('#commandDock .cmd-search').fill('publ');
    await stage('publish');
    await page.locator('#commandDock .cmd-search').fill('publish');
    await stage('done');
    assert.equal(await page.evaluate(() => savedProjects.at(-1)[0].deliverables[0].name), 'DD90');
    await page.locator('#projectTutorialNext').click();
    assert.equal(await panel.isVisible(), false);
    assert.equal(await page.locator('.project-tutorial-target').count(), 0);
    console.log('PASS: real project form, path validation, deliverable, date, save, selection and typing Publish.');

    await start();
    await page.locator('#f_path').fill('M:\\Projects\\Tutorial');
    await page.locator('#btnSaveProject').click();
    await page.locator('.d-name').fill('Permit set');
    await page.locator('.d-due').fill('12/01/2026');
    await page.evaluate(() => { failSave = true; });
    await page.locator('#btnSaveProject').click();
    await stage('retry');
    await page.evaluate(() => { failSave = false; });
    await page.locator('#projectTutorialNext').click();
    await stage('select');
    await page.locator('#commandDock .cmd-search').fill('publish');
    await stage('select');
    await page.locator('#tbody tr').click();
    await stage('done');
    console.log('PASS: failed saves require retry; typing Publish without the saved deliverable cannot finish.');

    await start();
    await page.locator('#editDlg [data-close-dialog="editDlg"]').click();
    await page.waitForFunction(() => projectTutorial === null);
    assert.equal(await panel.isVisible(), false);
    await page.evaluate(() => startProjectTutorial());
    await page.locator('[data-click-action="stopProjectTutorial"]').click();
    assert.equal(await page.evaluate(() => projectTutorial), null);
    console.log('PASS: cancel, close, and restart clean up the guide and highlights.');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
