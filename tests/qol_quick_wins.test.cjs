const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const scriptSource = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const dockSource = fs.readFileSync(path.join(root, 'industry-projects.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function extract(name, from = scriptSource) {
  const match = from.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, `function ${name} should exist`);
  return match[0];
}

test('toast assigns .toast-notification, replaces previous toasts, and clears the command dock on Projects', () => {
  const appended = [];
  const removed = [];
  const doc = {
    body: {
      dataset: { activeTab: 'projects' },
      append(node) { appended.push(node); },
    },
    querySelector(selector) {
      if (selector === '.toast-notification') {
        return appended.find((node) => node.className === 'toast-notification' && !removed.includes(node)) || null;
      }
      return null;
    },
  };
  const context = vm.createContext({
    document: doc,
    setTimeout: () => 0,
    el: (tag, props) => ({
      tag,
      ...props,
      remove() { removed.push(this); },
    }),
  });
  vm.runInContext(extract('toast'), context);

  context.toast('First message');
  assert.equal(appended.length, 1);
  assert.equal(appended[0].className, 'toast-notification');
  assert.equal(appended[0].role, 'status');
  assert.match(appended[0].style, /--modern-command-height/);
  assert.match(appended[0].style, /pointer-events:\s*none/);

  context.toast('Second message');
  assert.equal(removed.length, 1);
  assert.equal(removed[0], appended[0]);
  assert.equal(appended.length, 2);

  doc.body.dataset.activeTab = 'tools';
  context.toast('Tools message');
  assert.match(appended[2].style, /inset:\s*auto auto 24px 50%/);
});

test('openProjectPathFolder routes to local copy when Work locally is enabled', async () => {
  const calls = [];
  const context = vm.createContext({
    isProjectWorkLocally: (project) => project?.workLocally === true,
    openProjectDirectory: async (project, kind) => { calls.push(['openProjectDirectory', kind, project.id]); },
    convertPath: (p) => p,
    toast: (msg) => calls.push(['toast', msg]),
    window: {
      pywebview: {
        api: {
          open_path: async (p) => { calls.push(['open_path', p]); return { status: 'success' }; },
        },
      },
    },
  });
  vm.runInContext(extract('openProjectPathFolder'), context);

  await context.openProjectPathFolder({ id: '250001', path: 'M:\\Server', localProjectPath: 'C:\\Local', workLocally: true });
  assert.deepEqual(calls, [['openProjectDirectory', 'local', '250001']]);

  calls.length = 0;
  await context.openProjectPathFolder({ id: '250001', path: 'M:\\Server', localProjectPath: 'C:\\Local', workLocally: false });
  assert.deepEqual(calls[0], ['open_path', 'M:\\Server']);
});

test('timesheets save queue serializes writes, debounces rapid input, and pauses on unreadable data', async () => {
  let active = 0;
  let maxConcurrent = 0;
  const savedPayloads = [];
  let releaseFirst;
  let calls = 0;

  const context = vm.createContext({
    timesheetDb: { weeks: { w1: [{ hours: { mon: 1 } }] }, expenses: {}, lastModified: null },
    console: { warn() {} },
    toast() {},
    setTimeout,
    clearTimeout,
    window: {
      pywebview: {
        api: {
          get_timesheets: async () => ({ status: 'error', code: 'data_file_unreadable', message: 'corrupt json' }),
          save_timesheets: async (payload) => {
            calls += 1;
            active += 1;
            maxConcurrent = Math.max(maxConcurrent, active);
            const snapshot = JSON.parse(JSON.stringify(payload));
            if (calls === 1) {
              await new Promise((resolve) => { releaseFirst = resolve; });
            }
            savedPayloads.push(snapshot);
            active -= 1;
            return { status: 'success' };
          },
        },
      },
    },
  });
  vm.runInContext(
    [
      'let timesheetsDataLoadError = "";',
      'let timesheetSaveInFlight = null;',
      'let timesheetSaveFollowUp = null;',
      'let timesheetSaveTimeout = null;',
      extract('normalizeIsoTimestamp'),
      extract('loadTimesheets'),
      extract('queueTimesheetSave'),
      extract('saveTimesheets'),
      extract('debouncedSaveTimesheets'),
      extract('flushPendingTimesheetSave'),
    ].join('\n'),
    context
  );

  // Concurrent direct saves must serialize and finish with the latest state.
  const first = context.saveTimesheets({ silent: true });
  context.timesheetDb.weeks.w1[0].hours.mon = 4;
  const second = context.saveTimesheets({ silent: true });
  context.timesheetDb.weeks.w1[0].hours.mon = 8;
  const third = context.saveTimesheets({ silent: true });
  releaseFirst();
  await Promise.all([first, second, third]);
  assert.equal(maxConcurrent, 1);
  assert.equal(savedPayloads.length, 2);
  assert.equal(savedPayloads[1].weeks.w1[0].hours.mon, 8);

  // Debounced saves collapse rapid edits into a single flush.
  savedPayloads.length = 0;
  context.timesheetDb.weeks.w1[0].hours.mon = 2;
  context.debouncedSaveTimesheets(30);
  context.timesheetDb.weeks.w1[0].hours.mon = 6;
  context.debouncedSaveTimesheets(30);
  await context.flushPendingTimesheetSave();
  assert.equal(savedPayloads.length, 1);
  assert.equal(savedPayloads[0].weeks.w1[0].hours.mon, 6);

  // Unreadable data load pauses subsequent saves.
  savedPayloads.length = 0;
  await context.loadTimesheets();
  const ok = await context.saveTimesheets({ silent: true });
  assert.equal(ok, false);
  assert.equal(savedPayloads.length, 0);
});

test('list view sort headers, Partial Print dock entry, Freeze/Thaw settings inputs, and updated Help copy are wired', () => {
  assert.match(htmlSource, /<th class="reg-th deliverables-header" data-sort="deliverable" tabindex="0">Deliverable<\/th>/);
  assert.match(htmlSource, /<th class="reg-th" data-sort="due" tabindex="0">Due<\/th>/);
  assert.match(htmlSource, /<th class="reg-th" data-sort="status" tabindex="0">Status<\/th>/);
  assert.match(htmlSource, /id="settings_manageLayers_freezePatterns"/);
  assert.match(htmlSource, /id="settings_manageLayers_thawPatterns"/);
  assert.doesNotMatch(htmlSource, /The pencil icon in the app header/);
  assert.doesNotMatch(htmlSource, /The theme control in the header/);
  assert.doesNotMatch(htmlSource, /refresh control beside the version in the header/);
  assert.match(dockSource, /key:\s*"tool:toolPublishPartial"/);
  assert.match(dockSource, /publishMode:\s*"partial"/);
  assert.match(scriptSource, /const partialPrint = launchContext\?\.publishMode === "partial"/);
  assert.match(scriptSource, /askPublishExcelRefresh\(launchContext, \{ requireSelection: partialPrint \}\)/);
});
