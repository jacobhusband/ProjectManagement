// Run with Node and Playwright available (NODE_PATH may point to the bundled runtime).
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
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    // index.html's Content-Security-Policy would refuse the inline script injected below.
    const context = await browser.newContext({ bypassCSP: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // Use the real document and workflow handlers, with only the desktop bridge stubbed.
    await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ''));
    await page.addStyleTag({ content: fs.readFileSync(path.join(root, 'styles.css'), 'utf8') });
    const names = ['generateWorkflowId', 'ensureWorkflowToolDescriptors', 'getWorkflowToolDescriptor',
      'getUserWorkflows', 'getWorkflowDisplayName', 'getCommandHotkeyBindings', 'getCommandHotkeyOptions',
      'renderHotkeySettings', 'renderWorkflowCards', 'openWorkflowBuilder', 'populateWorkflowAddStepSelect',
      'renderWorkflowBuilderSteps', 'buildStepParamControl', 'updateWorkflowStepParam', 'addWorkflowStepFromSelect',
      'moveWorkflowStep', 'removeWorkflowStep', 'showWorkflowBuilderError', 'hideWorkflowBuilderError',
      'saveWorkflowFromBuilder', 'deleteWorkflowFromBuilder', 'renderWorkflowPreFlightSections',
      'collectPreFlightInputs', 'openWorkflowPreFlight', 'closeWorkflowPreFlight', 'initWorkflowsUi',
      'getDeclarativeClickAction', 'handleDeclarativeClick'];
    await page.addScriptTag({ content: `
      let userSettings = { commandHotkeys: {} }, workflowToolDescriptors = null,
        workflowBuilderState = null, workflowPreFlightState = null;
      let saves = 0;
      const DELIVERABLE_QUICK_ACCESS_ACTIONS = [];
      const getDeliverableToolMenuEntries = () => [];
      function el(tag, attrs) { const node = document.createElement(tag); Object.assign(node, attrs); return node; }
      function closeDlg(id) { document.getElementById(id).close(); }
      const debouncedSaveUserSettings = () => saves++;
      window.pywebview = { api: { get_workflow_tools: async () => ({ tools: [
        { toolId: 'first', displayName: 'First tool', params: [], requiredInputs: [{ key: 'projectFolder', type: 'folder', label: 'Project folder' }] },
        { toolId: 'second', displayName: 'Second tool', params: [], requiredInputs: [] }
      ] }) } };
      ${names.map(extract).join('\n')}
      document.addEventListener('click', handleDeclarativeClick, true);
      initWorkflowsUi();
      document.getElementById('settingsDlg').showModal();
    ` });
    await page.getByRole('button', { name: 'Create workflow', exact: true }).click();
    await page.locator('#workflowBuilderDlg[open]').waitFor();
    await page.locator('#workflowBuilderName').fill('Prepare and publish');
    await page.locator('#workflowAddStepSelect').selectOption('first');
    await page.locator('#workflowAddStepBtn').click();
    await page.locator('#workflowAddStepSelect').selectOption('second');
    await page.locator('#workflowAddStepBtn').click();
    assert.equal(await page.locator('.workflow-step').count(), 2);
    await page.locator('.workflow-step').nth(1).getByTitle('Move up').click();
    await page.locator('#workflowBuilderSaveBtn').click();
    const workflowId = await page.evaluate(() => getUserWorkflows()[0].id);
    assert.equal(await page.evaluate(() => getUserWorkflows()[0].steps[0].toolId), 'second');
    await page.locator('#settings_hotkey_1').selectOption(`workflow:${workflowId}`);
    await page.getByRole('button', { name: 'Edit workflow', exact: true }).filter({ visible: true }).click();
    await page.locator('#workflowBuilderDlg[open]').waitFor();
    assert.equal(await page.locator('#workflowBuilderName').inputValue(), 'Prepare and publish');
    await page.locator('#workflowBuilderName').fill('Updated workflow');
    await page.locator('#workflowBuilderSaveBtn').click();
    assert.equal(await page.evaluate(() => getUserWorkflows().length), 1);
    assert.equal(await page.evaluate(() => getUserWorkflows()[0].name), 'Updated workflow');
    await page.evaluate(() => {
      window.preflightResult = 'pending';
      openWorkflowPreFlight(getUserWorkflows()[0], {}, { '1': { projectFolder: 'C:\\Project' } })
        .then(result => window.preflightResult = result);
    });
    await page.locator('#workflowPreFlightDlg[open]').waitFor();
    await page.locator('#workflowPreFlightRunBtn').click();
    assert.equal(await page.evaluate(() => window.preflightResult.stepInputs['1'].projectFolder), 'C:\\Project');
    await page.evaluate(() => {
      openWorkflowPreFlight(getUserWorkflows()[0], {}, {}).then(result => window.preflightResult = result);
    });
    await page.locator('#workflowPreFlightDlg[open]').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => window.preflightResult), null);
    assert.deepEqual(errors, []);
    console.log('PASS: create, reorder, save, assign, edit, input review, and Escape cancellation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
