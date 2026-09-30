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

function extractConst(name) {
  const match = source.match(new RegExp(`^const ${name} =[\\s\\S]*?;\\r?$`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0];
}

const FUNCTIONS = [
  'isTerminalActivityStatus', 'isRunningActivityStatus', 'isQueuedActivityStatus',
  'clampActivityProgress', 'normalizeActivityTimestamp', 'normalizeDwgComparePairs', 'deepCloneJson',
  'normalizeWindowsPath', 'getWindowsPathLeaf', 'getWindowsPathParent', 'findProjectRootPath',
  'parseProjectFromPath', 'normalizeProjectPath', 'normalizeWorkroomFolderPath',
  'getLaunchContextProjectRoot', 'findActivityProjectForPath', 'getActivityById', 'bindToolActivity',
  'releaseToolActivity', 'upsertActivity', 'updateActivity', 'completeActivity', 'acceptActivity',
  'getActivityDisplayTitle', 'getProjectActivityLane', 'getActivityLanes', 'waitForActivityLanes',
  'waitForToolTurn', 'releaseActivityLanes', 'describeActivityLaneWait', 'grantActivityLanes',
];

function setup() {
  const context = vm.createContext({
    console,
    ACTIVITY_STATUS: Object.freeze({
      QUEUED: 'queued', RUNNING: 'running', SUCCESS: 'success',
      WARNING: 'warning', ERROR: 'error', CANCELLED: 'cancelled',
    }),
    ACTIVITY_CANCELLABLE_TOOL_IDS: new Set(),
    activityTrayState: { items: [] },
    activeToolActivityIds: new Map(),
    db: [{ id: '250597', name: 'Bank Remodel', path: 'M:\\BofA\\2026\\250597 Bank Remodel' }],
    recordActivityHistory() {}, syncToolCardRunning() {}, renderActivityTray() {},
    maybeExpandActivityTray() {},
    getActivityProjectName: ({ projectName }) => projectName || '',
    isRerunnableToolId: () => true,
  });
  vm.runInContext(
    [
      extractConst('PROJECT_ROOT_SEGMENT_REGEX'),
      extractConst('activityLaneState'),
      extractConst('ACTIVITY_SINGLE_RUN_TOOL_IDS'),
      ...FUNCTIONS.map(extract),
    ].join('\n'),
    context
  );
  // Starts an activity the way a tool handler does and reports how its wait ended.
  const launch = (id, lanes, { label = 'Publish', toolId = 'toolPublishDwgs', projectName = '' } = {}) => {
    context.upsertActivity({ id, toolId, label, projectName, status: 'running' });
    const outcome = { value: 'waiting' };
    context.waitForActivityLanes(id, lanes).then((value) => { outcome.value = value; });
    return outcome;
  };
  const activity = (id) => context.getActivityById(id);
  return { context, launch, activity };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));
const lanesOf = (context, options) => Array.from(context.getActivityLanes(options)).sort();

test('other projects run at the same time; the same project waits for the running tool', async () => {
  const { context, launch, activity } = setup();
  const publish = launch('publish', ['project:250597'], { projectName: 'Bank Remodel' });
  const otherProject = launch('layers', ['project:250601'], { label: 'Freeze / Thaw' });
  const sameProject = launch('xrefs', ['project:250597'], { label: 'Clean Xrefs' });
  await settle();

  assert.equal(publish.value, true);
  assert.equal(otherProject.value, true);
  assert.equal(sameProject.value, 'waiting');
  assert.equal(activity('xrefs').status, 'queued');
  assert.equal(activity('xrefs').message, 'Waiting for Publish to finish on Bank Remodel.');
  const queuedAt = activity('xrefs').startedAt;

  context.completeActivity('publish', {});
  await settle();
  assert.equal(sameProject.value, true);
  assert.equal(activity('xrefs').status, 'running');
  assert.equal(activity('xrefs').message, 'Starting...');
  assert.ok(activity('xrefs').startedAt >= queuedAt, 'time spent waiting is not counted as running');
});

test('runs for one project start in the order they were launched', async () => {
  const { context, launch } = setup();
  const started = [];
  const outcomes = ['first', 'second', 'third'].map((id) => {
    const outcome = launch(id, ['project:250597']);
    return { id, outcome };
  });
  const record = async () => {
    await settle();
    outcomes.forEach(({ id, outcome }) => {
      if (outcome.value === true && !started.includes(id)) started.push(id);
    });
  };
  await record();
  context.completeActivity('first', {});
  await record();
  assert.deepEqual(started, ['first', 'second']);
  context.completeActivity('second', { status: 'error' });
  await record();
  assert.deepEqual(started, ['first', 'second', 'third']);
});

test('removing a waiting run stops it and lets the next one through', async () => {
  const { context, launch } = setup();
  launch('running', ['project:250597']);
  const removed = launch('removed', ['project:250597']);
  const next = launch('next', ['project:250597']);
  await settle();

  context.completeActivity('removed', { status: 'cancelled', message: 'Removed from queue.' });
  await settle();
  assert.equal(removed.value, false, 'the tool handler is told not to start');
  assert.equal(next.value, 'waiting');

  context.acceptActivity('running');
  await settle();
  assert.equal(next.value, true, 'a run cleared from the tray gives up its project');
});

test('a later run cannot jump ahead of an earlier run waiting for the same project', async () => {
  const { context, launch, activity } = setup();
  launch('holder', ['project:250597']);
  const workflow = launch('workflow', ['project:250597', 'project:250601'], { label: 'Workflow' });
  const later = launch('later', ['project:250601']);
  await settle();
  assert.equal(workflow.value, 'waiting');
  assert.equal(later.value, 'waiting');
  assert.match(activity('later').message, /^Waiting for Workflow to finish/);

  context.completeActivity('holder', {});
  await settle();
  assert.equal(workflow.value, true);
  assert.equal(later.value, 'waiting');
  context.completeActivity('workflow', {});
  await settle();
  assert.equal(later.value, true);
});

test('Freeze / Thaw and Clean Xrefs run one at a time even for different projects', async () => {
  const { context, launch, activity } = setup();
  const lanesFor = (projectPath) =>
    context.getActivityLanes({ toolIds: ['toolManageLayers'], launchContext: { projectPath } });
  const first = launch('a', lanesFor('M:\\BofA\\2026\\250597 Bank Remodel'), { label: 'Freeze / Thaw', toolId: 'toolManageLayers' });
  const second = launch('b', lanesFor('M:\\CU\\2026\\250601 Credit Union'), { label: 'Freeze / Thaw', toolId: 'toolManageLayers' });
  const publish = launch('c', context.getActivityLanes({
    toolIds: ['toolPublishDwgs'], launchContext: { projectPath: 'M:\\X\\250777 Other' },
  }));
  await settle();
  assert.equal(first.value, true);
  assert.equal(second.value, 'waiting');
  assert.equal(publish.value, true);
  assert.equal(
    activity('b').message,
    'Waiting for the other Freeze / Thaw run to finish. Freeze / Thaw runs one at a time.'
  );
});

test('a project lane follows its number, so server and local copies share it', () => {
  const { context } = setup();
  assert.deepEqual(
    lanesOf(context, {
      toolIds: ['toolPublishDwgs'],
      launchContext: {
        projectPath: 'M:\\BofA\\2026\\250597 Bank Remodel, 100 Main St',
        cadFilePaths: ['C:\\Users\\Me\\Local\\250597 Bank Remodel\\Electrical\\E01.dwg'],
      },
    }),
    ['project:250597']
  );
  assert.deepEqual(lanesOf(context, { launchContext: { projectId: '250601' } }), ['project:250601']);
  assert.deepEqual(
    lanesOf(context, { paths: ['C:\\Temp\\Loose Drawings\\E01.dwg'] }),
    ['folder:c:\\temp\\loose drawings']
  );
  assert.deepEqual(
    lanesOf(context, { toolIds: ['publishDwgs', 'manageLayers', 'cleanXrefs', 'constructor'] }),
    ['tool:toolCleanXrefs', 'tool:toolManageLayers']
  );
  assert.deepEqual(lanesOf(context, {}), [], 'a run with no known project waits for nothing');
});
