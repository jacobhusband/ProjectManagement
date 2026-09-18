const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const dockSource = fs.readFileSync(path.join(__dirname, '../industry-projects.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');

function extract(source, name) {
  const match = source.match(new RegExp(String.raw`^function ${name}\([\s\S]*?^}\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
}

function setup(settings = {}) {
  const dock = { input: { value: '#project', focus() {} }, items: [] };
  const context = vm.createContext({
    userSettings: settings,
    ensureCommandDock: () => dock,
    renderCommandDockItems() {}, updateCommandDockContext() {},
    syncCommandDockSelection() {}, setCommandDockExpanded() {},
    setCommandDockActive() {}, focusCommandDockGroup() {},
    runCommandDockItem: item => { dock.ran = item; },
  });
  vm.runInContext([
    ...['parseDueStr', 'getEffectiveDueStr', 'compareDeliverablesByDueDesc'].map(n => extract(appSource, n)),
    ...['getCommandDockProjectDeliverables', 'selectDeliverableForCommands', 'selectProjectForCommands'].map(n => extract(dockSource, n)),
  ].join('\n'), context);
  return { context, dock };
}

test('default window includes the 30-day boundary, future and undated entries, newest first', () => {
  const { context } = setup();
  const project = { deliverables: [
    { id: 'old', due: '2026-08-11' },
    { id: 'boundary', due: '2026-08-12' },
    { id: 'today', due: '2026-09-11' },
    { id: 'future', hardDue: '2026-10-01' },
    { id: 'undated' }, null,
  ] };
  const options = { now: new Date(2026, 8, 11, 23, 59) };
  assert.deepEqual(Array.from(context.getCommandDockProjectDeliverables(project, options), d => d.id),
    ['future', 'today', 'boundary', 'undated']);
  assert.equal(project.deliverables[0].id, 'old');
  context.userSettings.commandLineShowAllDeliverables = true;
  assert.equal(context.getCommandDockProjectDeliverables(project, options).length, 5);
  context.userSettings.commandLineShowAllDeliverables = false;
  assert.equal(context.getCommandDockProjectDeliverables(project, { ...options, includeAll: true }).length, 5);
});

test('selecting a project selects its latest deliverable and honors a pending command', () => {
  const { context, dock } = setup({ commandLineShowAllDeliverables: true });
  const project = { deliverables: [{ due: '2025-01-01' }, { due: '2026-09-01' }, {}] };
  const pending = { key: 'publish', scope: 'deliverable' };
  dock.pendingKey = pending.key;
  dock.items = [pending];
  context.selectProjectForCommands(project);
  assert.equal(dock.project, project);
  assert.equal(dock.deliverable, project.deliverables[1]);
  assert.equal(dock.input.value, '');
  assert.equal(dock.ran, pending);
});

test('projects with only old deliverables retain project commands without selecting a hidden entry', () => {
  const { context, dock } = setup();
  const project = { deliverables: [{ due: '2000-01-01' }] };
  const pending = { key: 'add-deliverable', scope: 'project' };
  dock.pendingKey = pending.key;
  dock.items = [pending];
  context.selectProjectForCommands(project);
  assert.equal(dock.project, project);
  assert.equal(dock.deliverable, null);
  assert.equal(dock.ran, pending);
  context.selectProjectForCommands(null);
  assert.equal(dock.project, null);
});
