const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');

function extract(name) {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0];
}

const FUNCTIONS = [
  'isTerminalActivityStatus', 'isRunningActivityStatus', 'isQueuedActivityStatus',
  'clampActivityProgress', 'normalizeActivityTimestamp', 'normalizeDwgComparePairs', 'deepCloneJson',
  'normalizeWindowsPath', 'getWindowsPathLeaf', 'getActivityById', 'bindToolActivity',
  'releaseToolActivity', 'upsertActivity', 'updateActivity', 'completeActivity', 'getActivityDisplayTitle',
  'getActivityRecordById', 'normalizeActivityHistoryEntry', 'mergeActivityHistoryEntries',
  'recordActivityHistory', 'saveActivityHistory', 'loadActivityHistory', 'removeActivityHistoryEntry',
  'getActivityHistoryDrawingPaths', 'getActivityHistoryProjectFolder', 'filterActivityHistoryEntries',
  'getActivityHistoryDayLabel',
];
const T0 = Date.UTC(2026, 8, 28, 15, 0);

function setup(api = {}) {
  const calls = { saves: 0 };
  const context = vm.createContext({
    console: { warn() {} },
    window: { pywebview: { api } },
    ACTIVITY_STATUS: Object.freeze({
      QUEUED: 'queued', RUNNING: 'running', SUCCESS: 'success',
      WARNING: 'warning', ERROR: 'error', CANCELLED: 'cancelled',
    }),
    ACTIVITY_HISTORY_LIMIT: 3,
    ACTIVITY_HISTORY_STATUS_LABELS: {
      success: 'Succeeded', warning: 'Finished with warnings', error: 'Failed', cancelled: 'Cancelled',
    },
    ACTIVITY_CANCELLABLE_TOOL_IDS: new Set(),
    activityTrayState: { items: [] },
    activityHistoryState: { entries: [], query: '', loaded: false, canSave: false, loadPromise: null },
    activeToolActivityIds: new Map(),
    debouncedSaveActivityHistory: () => { calls.saves++; },
    renderActivityHistory() {}, renderActivityTray() {}, maybeExpandActivityTray() {},
    syncToolCardRunning() {}, releaseActivityLanes() {},
    getActivityProjectName: ({ projectName }) => projectName || '',
    isRerunnableToolId: () => true,
    getLaunchContextProjectRoot: (launchContext) => launchContext?.rootProjectPath || '',
  });
  vm.runInContext(FUNCTIONS.map(extract).join('\n'), context);
  const ids = () => Array.from(context.activityHistoryState.entries, (entry) => entry.id);
  return { context, calls, ids };
}

test('a finished activity is recorded and stays reachable after the tray is cleared', () => {
  const { context, calls, ids } = setup();
  context.upsertActivity({
    id: 'publish-1', toolId: 'toolPublishDwgs', label: 'Publish', status: 'running',
    rerunLaunchContext: { rootProjectPath: 'M:\\Proj', cadFilePaths: ['M:\\Proj\\E1.dwg'] },
  });
  assert.deepEqual(ids(), [], 'running work is not history yet');

  context.completeActivity('publish-1', { message: 'Plotted 1 drawing.', openFolderPath: 'C:\\Plots' });
  assert.deepEqual(ids(), ['publish-1']);
  assert.equal(calls.saves, 1);
  const [entry] = context.activityHistoryState.entries;
  assert.equal(entry.status, 'success');
  assert.equal(entry.openFolderPath, 'C:\\Plots');
  assert.equal(entry.progress, undefined, 'transient tray state is not kept');

  context.activityTrayState.items = [];
  assert.equal(context.getActivityRecordById('publish-1').openFolderPath, 'C:\\Plots');
  assert.equal(context.getActivityRecordById('missing'), null);
});

test('a queued run that was removed before it started is not recorded', () => {
  const { context, ids } = setup();
  context.upsertActivity({ id: 'queued-1', toolId: 'toolPublishDwgs', status: 'queued' });
  context.completeActivity('queued-1', { status: 'cancelled', message: 'Removed from queue.' });
  assert.deepEqual(ids(), []);
});

test('merging keeps the newest entries, prefers the first list, and drops unfinished ones', () => {
  const { context } = setup();
  const merged = context.mergeActivityHistoryEntries(
    [{ id: 'b', status: 'success', endedAt: T0 + 2000, message: 'fresh' }],
    [
      { id: 'b', status: 'success', endedAt: T0 + 2000, message: 'stale' },
      { id: 'a', status: 'error', endedAt: T0 + 1000 },
      { id: 'c', status: 'warning', endedAt: T0 + 3000 },
      { id: 'd', status: 'success', endedAt: T0 },
      { id: 'running', status: 'running', endedAt: T0 + 9000 },
      { status: 'success' },
      null,
    ]
  );
  assert.deepEqual(Array.from(merged, (entry) => entry.id), ['c', 'b', 'a']);
  assert.equal(merged[1].message, 'fresh');
});

test('activity finished before the stored history loads is merged, and nothing saves until then', async () => {
  let saved;
  const { context, calls, ids } = setup({
    get_activity_history: async () => ({
      status: 'success', entries: [{ id: 'old', status: 'success', endedAt: T0 }],
    }),
    save_activity_history: async (payload) => { saved = payload; return { status: 'success' }; },
  });
  context.recordActivityHistory({ id: 'new', status: 'success', endedAt: T0 + 1000 });
  assert.equal(await context.saveActivityHistory(), false);
  assert.equal(saved, undefined, 'saving now would replace the stored history');

  await context.loadActivityHistory();
  assert.deepEqual(ids(), ['new', 'old']);
  assert.equal(calls.saves, 2, 'the merged history is queued for saving');
  assert.equal(await context.saveActivityHistory(), true);
  assert.deepEqual(Array.from(saved.entries, (entry) => entry.id), ['new', 'old']);
});

test('an unreadable history file is never saved over', async () => {
  const { context } = setup({
    get_activity_history: async () => ({ status: 'error', message: 'damaged', entries: [] }),
    save_activity_history: async () => { throw new Error('must not save'); },
  });
  await context.loadActivityHistory();
  assert.equal(context.activityHistoryState.loaded, true);
  assert.equal(context.activityHistoryState.canSave, false);
  assert.equal(await context.saveActivityHistory(), false);
});

test('drawings, the project folder and search come from the stored activity', () => {
  const { context } = setup();
  const entry = context.normalizeActivityHistoryEntry({
    id: 'xrefs', status: 'success', label: 'Clean Xrefs', projectName: 'Bank Remodel', endedAt: T0,
    openFolderPath: 'C:\\Output',
    rerunLaunchContext: {
      rootProjectPath: 'M:\\Proj',
      cadFilePaths: ['M:\\Proj\\E1.dwg', 'm:/proj/e1.DWG', 'M:\\Proj\\Notes.pdf'],
    },
    dwgComparePairs: [{ newPath: 'M:\\Proj\\x-A1.dwg', oldPath: 'M:\\Proj\\Old\\x-A1.dwg' }],
  });

  assert.deepEqual(Array.from(context.getActivityHistoryDrawingPaths(entry)), [
    'M:\\Proj\\E1.dwg',
    'M:\\Proj\\x-A1.dwg',
  ]);
  assert.equal(context.getActivityHistoryProjectFolder(entry), 'M:\\Proj');
  assert.equal(
    context.getActivityHistoryProjectFolder({ ...entry, openFolderPath: 'm:\\proj\\' }),
    '',
    'no second button for the folder the activity already opens'
  );

  const matches = (query) => context.filterActivityHistoryEntries([entry], query).length === 1;
  assert.ok(matches('x-a1'), 'drawing names are searchable');
  assert.ok(matches('bank clean'), 'every word must match somewhere');
  assert.ok(matches('succeeded'), 'status labels are searchable');
  assert.ok(!matches('failed'));
});

test('entries are grouped under today, yesterday, or their date', () => {
  const { context } = setup();
  const now = new Date(2026, 8, 28, 9, 0);
  assert.equal(context.getActivityHistoryDayLabel(new Date(2026, 8, 28, 0, 5).getTime(), now), 'Today');
  assert.equal(context.getActivityHistoryDayLabel(new Date(2026, 8, 27, 23, 55).getTime(), now), 'Yesterday');
  assert.notEqual(context.getActivityHistoryDayLabel(new Date(2026, 8, 20).getTime(), now), 'Yesterday');
  assert.equal(context.getActivityHistoryDayLabel(0, now), 'Earlier');
});

test('removing an entry takes it out of history', () => {
  const { context, calls, ids } = setup();
  context.recordActivityHistory({ id: 'one', status: 'success', endedAt: T0 });
  assert.equal(context.removeActivityHistoryEntry('one'), true);
  assert.equal(context.removeActivityHistoryEntry('one'), false);
  assert.deepEqual(ids(), []);
  assert.equal(calls.saves, 2);
});
