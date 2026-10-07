const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const extract = name => {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    const page = await browser.newPage({ bypassCSP: true });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
    await page.setContent(html);
    await page.addStyleTag({ content: fs.readFileSync(path.join(root, 'styles.css'), 'utf8') });
    await page.addScriptTag({ content: `
      const ACTIVITY_STATUS = { RUNNING: 'running', SUCCESS: 'success', ERROR: 'error', WARNING: 'warning', CANCELLED: 'cancelled' };
      const activities = {}, history = {}, moves = [], lookups = [], toasts = [];
      let folders = [{ name: '2026-10-05 MEP IFP' }], failMove = false;
      let publishDestinationQueue = Promise.resolve();
      const publishDestinationPending = new Set();
      const getActivityRecordById = id => activities[id] || history[id];
      const getActivityById = id => activities[id];
      const getLaunchContextProjectRoot = context => context?.projectPath || '';
      const getActivityHistoryDrawingPaths = activity => activity.rerunLaunchContext?.cadFilePaths || [];
      const getWindowsPathLeaf = value => value.split(/[\\\\/]/).pop();
      const toast = message => toasts.push(message);
      const updateActivity = (id, patch) => {
        Object.assign(activities[id], patch);
        if (activities[id].status !== 'running') history[id] = { ...activities[id] };
      };
      const recordActivityHistory = activity => history[activity.id] = activity;
      const completeActivity = (id, patch) => {
        updateActivity(id, patch);
        recordActivityHistory({ ...activities[id] });
      };
      const failActivity = (id, patch) => updateActivity(id, { ...patch, status: 'error' });
      const normalizeDwgComparePairs = value => value;
      const clampActivityProgress = value => value;
      const deriveToolActivityProgress = () => 50;
      const getActivityProjectName = () => 'Project';
      const getActivityLabelFromPayload = () => 'Publish';
      const isTerminalActivityStatus = status => status !== 'running';
      const windowApi = {
        get_publish_pdf_destinations: async (source, project) => {
          lookups.push({ source, project });
          return { status: 'success', pdfFolder: 'M:/Project/PDF', folders };
        },
        move_published_pdf: async (source, project, folder, create) => {
          moves.push({ source, project, folder, create });
          return failMove ? { status: 'error', message: 'The PDF already exists.' } : {
            status: 'success', combinedPdfPath: 'M:/Project/PDF/' + folder + '/set.pdf',
            openFolderPath: 'M:/Project/PDF/' + folder, message: 'Published set moved.'
          };
        }
      };
      window.pywebview = { api: windowApi };
      function start(id) {
        activities[id] = { id, toolId: 'toolPublishDwgs', status: 'running', combinedPdfPath: 'C:/Plots/set.pdf',
          rerunLaunchContext: { projectPath: 'M:/Project' } };
      }
      function done(id) { updateActivityStatusFromPayload({ toolId: 'toolPublishDwgs', activityId: id, message: 'DONE' }); }
      ${['getServerLaunchContext', 'queuePublishDestination', 'showPublishDestination', 'normalizeActivityStatusFromPayload', 'updateActivityStatusFromPayload'].map(extract).join('\n')}
    ` });

    // Finishing a publish never opens the prompt or looks anything up; the button does.
    await page.evaluate(() => { start('skip'); done('skip'); done('skip'); });
    await page.evaluate(() => publishDestinationQueue);
    assert.equal(await page.locator('#publishDestinationDlg').evaluate(node => node.open), false);
    assert.equal(await page.evaluate(() => lookups.length), 0);
    assert.equal(await page.evaluate(() => moves.length), 0);

    // The activity's button opens the prompt; skipping performs no move.
    await page.evaluate(() => queuePublishDestination('skip'));
    await page.locator('#publishDestinationDlg[open]').waitFor();
    assert.equal(await page.locator('#publishDestinationExisting').inputValue(), '2026-10-05 MEP IFP');
    await page.locator('#publishDestinationSkip').click();
    await page.evaluate(() => publishDestinationQueue);
    assert.equal(await page.evaluate(() => moves.length), 0);
    assert.equal(await page.evaluate(() => lookups.length), 1);

    // The button can reopen a skipped prompt and update all saved links.
    await page.evaluate(() => queuePublishDestination('skip'));
    await page.locator('#publishDestinationDlg[open]').waitFor();
    await page.locator('#publishDestinationMove').click();
    await page.evaluate(() => publishDestinationQueue);
    assert.equal(await page.evaluate(() => moves[0].create), false);
    assert.equal(await page.evaluate(() => history.skip.combinedPdfPath), 'M:/Project/PDF/2026-10-05 MEP IFP/set.pdf');

    // Errors remain visible and permit retry; archived tray entries still update history.
    await page.evaluate(() => { start('new'); done('new'); queuePublishDestination('new'); failMove = true; });
    await page.locator('#publishDestinationDlg[open]').waitFor();
    await page.locator('input[name="publishDestinationMode"][value="new"]').check();
    await page.locator('#publishDestinationMove').click();
    assert.equal(await page.locator('#publishDestinationError').textContent(), 'Enter a name for the new folder.');
    await page.locator('#publishDestinationName').fill('2026-10-06 MEP CD90');
    await page.locator('#publishDestinationMove').click();
    await page.waitForFunction(() => document.getElementById('publishDestinationError').textContent === 'The PDF already exists.');
    assert.equal(await page.locator('#publishDestinationDlg').evaluate(node => node.open), true);
    await page.evaluate(() => { failMove = false; delete activities.new; });
    await page.locator('#publishDestinationMove').click();
    await page.evaluate(() => publishDestinationQueue);
    assert.equal(await page.evaluate(() => history.new.openFolderPath), 'M:/Project/PDF/2026-10-06 MEP CD90');
    assert.equal(await page.evaluate(() => moves.at(-1).create), true);

    // Empty PDF roots default to creating a folder; manual DWGs resolve a project.
    await page.evaluate(() => {
      folders = []; start('manual');
      activities.manual.rerunLaunchContext = { cadFilePaths: ['M:/Project/Electrical/E01.dwg'] };
      done('manual'); queuePublishDestination('manual');
    });
    await page.locator('#publishDestinationDlg[open]').waitFor();
    assert.equal(await page.locator('#publishDestinationName').isEnabled(), true);
    assert.equal(await page.evaluate(() => lookups.at(-1).project), 'M:/Project/Electrical/E01.dwg');
    await page.keyboard.press('Escape');
    await page.evaluate(() => publishDestinationQueue);

    // Publishing local CAD files still offers the shared project's PDF folder.
    await page.evaluate(() => {
      start('local');
      activities.local.rerunLaunchContext = { projectPath: 'C:/Local/Project', workLocally: true, serverProjectPath: 'M:/Project' };
      done('local'); queuePublishDestination('local');
    });
    await page.locator('#publishDestinationDlg[open]').waitFor();
    assert.equal(await page.evaluate(() => lookups.at(-1).project), 'M:/Project');
    await page.locator('#publishDestinationSkip').click();
    await page.evaluate(() => publishDestinationQueue);

    // Sets clicked together are offered sequentially, once for each set.
    const lookupsBeforeQueue = await page.evaluate(() => lookups.length);
    await page.evaluate(() => { start('queue1'); start('queue2'); done('queue1'); done('queue2'); queuePublishDestination('queue1'); queuePublishDestination('queue2'); });
    await page.locator('#publishDestinationDlg[open]').waitFor();
    assert.equal(await page.evaluate(() => lookups.length), lookupsBeforeQueue + 1);
    await page.locator('#publishDestinationSkip').click();
    await page.waitForFunction(count => lookups.length === count, lookupsBeforeQueue + 2);
    await page.locator('#publishDestinationDlg[open]').waitFor();
    await page.locator('#publishDestinationSkip').click();
    await page.evaluate(() => publishDestinationQueue);

    // Failed or cancelled work cannot be moved.
    await page.evaluate(() => {
      start('failed'); updateActivityStatusFromPayload({ toolId: 'toolPublishDwgs', activityId: 'failed', message: 'ERROR: Plot failed' });
      queuePublishDestination('failed');
      start('cancelled'); activities.cancelled.status = 'cancelled'; queuePublishDestination('cancelled');
    });
    assert.equal(await page.locator('#publishDestinationDlg').evaluate(node => node.open), false);
    assert.deepEqual(errors, []);
    console.log('Publish destination browser checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
