const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');
const dock = fs.readFileSync(path.join(__dirname, '../industry-projects.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function extract(source, name) {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
}

function model() {
  const identity = value => value;
  const c = vm.createContext({
    Date, createId: () => 'dlv_test', isFinished: () => false,
    normalizeAttachments: value => value || [], normalizeDeliverableLinks: value => value || [],
    buildLegacyEmailRefsFromAttachments: () => [], buildLegacyLinksFromAttachments: () => [],
    normalizePage: value => value || {}, normalizeDeliverableNoteItems: value => value || [],
    normalizeTask: identity, normalizePinnedDeliverableOrder: identity,
    normalizeWorkroomCadDiscipline: identity, normalizeWorkroomPhase: identity,
    normalizeWorkroomReturnType: identity, normalizeChecklistInstance: identity,
    normalizeChecklistContext: identity, createDefaultChecklistContext: () => ({}),
    migrateStatusFields() {}, syncStatusArrays() {},
    syncDeliverableAttachmentFields() {}, syncDeliverableWorkItemFields() {},
  });
  for (const name of ['parseDueStr', 'getActiveDueField', 'getEffectiveDueStr',
    'getLegacyDueDates', 'applyDeliverableDueDate', 'normalizeDeliverable', 'createDeliverable']) {
    vm.runInContext(extract(app, name), c);
  }
  return c;
}

test('migration preserves original paired dates, uses the firm deadline and is repeatable', () => {
  const c = model();
  const original = { id: 'dlv_original', name: 'Permit', due: '11/20/2026', hardDue: '11/25/2026',
    notes: 'Keep this context', tasks: [{ text: 'Review' }], pinned: true, pinnedOrder: 2 };
  const snapshot = plain(original);
  const migrated = c.normalizeDeliverable(original);
  assert.equal(migrated.due, '11/25/2026');
  assert.equal('hardDue' in migrated, false);
  assert.deepEqual(plain(migrated.legacyDueDates), { due: '11/20/2026', hardDue: '11/25/2026' });
  assert.deepEqual(original, snapshot);
  assert.deepEqual(plain(c.normalizeDeliverable(migrated)), plain(migrated));
  assert.equal(migrated.id, original.id);
  assert.equal(migrated.notes, original.notes);
  assert.deepEqual(plain(migrated.tasks), original.tasks);
  assert.equal(migrated.pinnedOrder, original.pinnedOrder);
});

test('old records with a single date migrate without losing that date', () => {
  const c = model();
  for (const [input, expected] of [
    [{}, ''], [{ due: '11/20/2026' }, '11/20/2026'],
    [{ hardDue: '11/25/2026' }, '11/25/2026'],
    [{ due: '11/20/2026', hardDue: 'tbd' }, '11/20/2026'],
  ]) assert.equal(c.normalizeDeliverable(input).due, expected);
  const fresh = c.createDeliverable({ name: 'New', due: '11/30/2026' });
  assert.equal(fresh.due, '11/30/2026');
  assert.equal('hardDue' in fresh, false);
  assert.equal('legacyDueDates' in fresh, false);
});

test('a cleared migrated due date remains blank after save and reload', () => {
  const c = model();
  const migrated = c.normalizeDeliverable({ due: '11/20/2026', hardDue: '11/25/2026' });
  c.applyDeliverableDueDate(migrated, 'due', '');
  const reloaded = c.normalizeDeliverable(plain(migrated));
  assert.equal(c.getEffectiveDueStr(reloaded), '');
  assert.equal(reloaded.legacyDueDates.hardDue, '11/25/2026');
});

function prompt() {
  const input = { value: '', focus() {}, select() {} };
  const dockState = { input, root: { classList: { add() {} } },
    columns: {}, promptView: {}, pending: {}, scope: {}, footShortcuts: {} };
  const c = vm.createContext({ Date, industryActivePrompt: null, industryCommandDock: dockState,
    ensureCommandDock: () => dockState, renderPromptView() {}, setCommandDockExpanded() {},
    messages: [], completed: [], toast(message) { c.messages.push(message); },
    completeAddDeliverablePrompt() { c.completed.push(plain(c.industryActivePrompt.values)); },
  });
  vm.runInContext(extract(app, 'parseDueStr'), c);
  for (const name of ['parsePromptDate', 'formatPromptDate', 'startAddDeliverablePrompt',
    'syncPromptInput', 'setPromptStep', 'advancePromptStep']) vm.runInContext(extract(dock, name), c);
  return c;
}

test('Add Deliverable completes after description and one optional due date', () => {
  const c = prompt();
  c.startAddDeliverablePrompt({ id: 'project' });
  c.advancePromptStep('');
  assert.equal(c.industryActivePrompt.step, 0);
  c.advancePromptStep('Permit');
  assert.equal(c.industryActivePrompt.step, 1);
  assert.equal(c.industryCommandDock.pending.textContent, 'Add Deliverable · 2/2 Due Date');
  c.advancePromptStep('invalid');
  assert.equal(c.completed.length, 0);
  c.advancePromptStep('11/25/2026');
  assert.deepEqual(plain(c.completed), [{ name: 'Permit', due: '11/25/2026' }]);
  c.setPromptStep(5);
  assert.equal(c.industryActivePrompt.step, 1);
  for (const skip of ['', 'skip', 'none']) {
    c.startAddDeliverablePrompt({ id: 'project' }, 'Undated');
    c.advancePromptStep(skip);
    assert.deepEqual(plain(c.completed.at(-1)), { name: 'Undated', due: '' });
  }
});
