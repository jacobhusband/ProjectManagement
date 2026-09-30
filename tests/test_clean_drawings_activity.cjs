const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8');
const start = source.indexOf('  document.getElementById("toolCleanDrawings")?.addEventListener("click"');
const end = source.indexOf('  document.getElementById("toolCleanDrawings")?.addEventListener("keydown"', start);
assert.ok(start >= 0 && end > start);

async function scenario(outcome) {
  let handler, finishPreview;
  const events = [];
  const preview = new Promise(resolve => { finishPreview = resolve; });
  const button = { dataset: {}, classList: { contains: () => false },
    setAttribute() {}, removeAttribute() {}, querySelector: () => ({ textContent: '' }),
    addEventListener: (name, fn) => { handler = fn; } };
  const context = {
    document: { getElementById: () => button },
    resolveCadLaunchContextForTool: () => ({ projectPath: 'project' }),
    getLaunchContextProjectRoot: () => 'project',
    ensureAutocadPathLoaded: async () => true,
    beginActivity: info => { events.push(['begin', info]); return 'activity-1'; },
    updateActivity: (id, info) => events.push(['update', id, info]),
    completeActivity: (id, info) => events.push(['complete', id, info]),
    failActivity: (id, info) => events.push(['fail', id, info]),
    // 'removed' is a run taken out of the tray while it waited for its project.
    waitForToolTurn: async (id, toolId, launch, paths) => {
      events.push(['turn', id, toolId, paths, button.dataset.cleanBusy]);
      return outcome !== 'removed';
    },
    confirmCleanDrawingSelection: async () => outcome === 'cancel' ? null : { drawings: ['E01.dwg'] },
    ACTIVITY_STATUS: { SUCCESS: 'success', WARNING: 'warning', CANCELLED: 'cancelled' },
    window: { pywebview: { api: {
      preview_clean_drawings: (launch, id) => { events.push(['preview', id]); return preview; },
      run_clean_drawings: async (selection, launch, id) => { events.push(['run', id]); return { status: 'success', count: 1, output: 'output' }; },
    } } },
  };
  vm.runInNewContext(source.slice(start, end), context);
  const running = handler({ currentTarget: button });
  await new Promise(resolve => setImmediate(resolve));
  // The activity must be visible while the initial scan is still unresolved.
  assert.equal(events[0][0], 'begin');
  assert.equal(events[1][0], 'preview');
  assert.equal(events[1][1], 'activity-1');
  assert.equal(events.filter(e => e[0] === 'complete').length, 0);
  finishPreview(outcome === 'error' ? { status: 'error', message: 'scan failed' } :
    { status: 'success', titleblocks: ['x-TB.dwg'], drawings: ['E01.dwg'], project: 'project' });
  await running;
  assert.equal(events.filter(e => e[0] === 'begin').length, 1);
  assert.equal(button.dataset.cleanBusy, undefined);
  if (outcome === 'error') assert.equal(events.at(-1)[0], 'fail');
  else if (outcome === 'removed') assert.deepEqual(events.at(-1).slice(0, 3), ['turn', 'activity-1', 'toolCleanDrawings']);
  else assert.equal(events.at(-1)[2].status, outcome === 'cancel' ? 'cancelled' : 'success');
  assert.equal(events.filter(e => e[0] === 'run').length, outcome === 'success' ? 1 : 0);
  const turn = events.find(e => e[0] === 'turn');
  if (['success', 'removed'].includes(outcome)) {
    // The cleaning waits for its project after the dialog, and another clean may start meanwhile.
    assert.equal(turn[2], 'toolCleanDrawings');
    assert.deepEqual(Array.from(turn[3]), ['project']);
    assert.equal(turn[4], undefined, 'the dialog lock is released before waiting');
    assert.ok(events.indexOf(turn) > events.findIndex(e => e[0] === 'update' && /confirmation/.test(e[2].message)));
  } else {
    assert.equal(turn, undefined);
  }
}

(async () => {
  for (const outcome of ['success', 'cancel', 'error', 'removed']) await scenario(outcome);
  const progressContext = { clampActivityProgress: value => Math.max(0, Math.min(100, value)) };
  const pStart = source.indexOf('function deriveToolActivityProgress(');
  const pEnd = source.indexOf('function updateActivityStatusFromPayload(', pStart);
  vm.runInNewContext(source.slice(pStart, pEnd), progressContext);
  const progress = progressContext.deriveToolActivityProgress;
  assert.ok(progress('toolCleanDrawings', 'Validating drawing 2 of 3: E02.dwg', 50) > 50);
  assert.equal(progress('toolCleanDrawings', 'AutoCAD sheet cleanup: running (10s elapsed)…', 60), 60);
  assert.equal(progress('toolCleanDrawings', 'Checking source versions and delivering validated drawings…', 80), 95);
  console.log('Clean Drawings activity tests passed: immediate activity, shared ID, success, cancellation, failure, waiting for the project, progress.');
})().catch(error => { console.error(error); process.exitCode = 1; });
