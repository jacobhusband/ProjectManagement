const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const dockSource = fs.readFileSync(path.join(__dirname, '../industry-projects.js'), 'utf8');

function extract(name) {
  const match = dockSource.match(new RegExp(String.raw`^function ${name}\([\s\S]*?^}\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
}

function setup() {
  const dock = {
    input: { value: '', focus() {} },
    items: [], multi: [], anchor: null, deliverable: null, project: null,
    pendingKey: null, pendingLabel: '',
  };
  const context = vm.createContext({
    industryCommandDock: dock,
    ensureCommandDock: () => dock,
    renderCommandDockItems() {}, updateCommandDockContext() {},
    syncCommandDockSelection() {}, setCommandDockExpanded() {},
    focusCommandDockGroup() {}, runCommandDockItem() {},
    saveCount: 0,
    save: async () => { context.saveCount += 1; },
    renderProjectsPreservingExpandedDeliverables() {},
    INDUSTRY_STATUS_OPTIONS: ['Complete'],
    hasStatus: (deliverable, status) => deliverable.status === status,
    setSingleStatus: (deliverable, status) => { deliverable.status = status; },
    isDeliverablePinned: (deliverable) => deliverable.pinned === true,
    setDeliverablePinnedState: (deliverable, next) => { deliverable.pinned = next === true; },
    industryPlural: (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`,
    getDeliverableToolMenuEntries: () => [],
    getCommandHotkeyEntries: () => [],
    DELIVERABLE_QUICK_ACCESS_ACTIONS: [],
    buildCommandDockTargetGroup: () => null,
    isProjectWorkLocally: () => false,
    getProjectActionFolderPath: () => 'P:/x',
  });
  vm.runInContext([
    'getCommandDockTargets', 'setCommandDockTargets', 'toggleDeliverableInSelection',
    'selectDeliverableForCommands', 'buildCommandDockGroups',
  ].map(extract).join('\n'), context);
  return { context, dock };
}

function commands(context) {
  const groups = context.buildCommandDockGroups(
    context.industryCommandDock.deliverable,
    context.industryCommandDock.project,
    context.getCommandDockTargets()
  );
  return groups.flatMap((group) => group.items).filter((item) => !item.hidden);
}

test('Ctrl-click adds and removes rows; a plain click goes back to one', () => {
  const { context, dock } = setup();
  const project = { id: 'P1' };
  const [a, b, c] = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];

  context.selectDeliverableForCommands(a, project);
  assert.equal(context.getCommandDockTargets().length, 1);

  context.toggleDeliverableInSelection(b, project);
  context.toggleDeliverableInSelection(c, project);
  assert.deepEqual(Array.from(context.getCommandDockTargets(), (e) => e.deliverable.id), ['a', 'b', 'c']);
  assert.equal(dock.deliverable, c);

  context.toggleDeliverableInSelection(b, project);
  assert.deepEqual(Array.from(context.getCommandDockTargets(), (e) => e.deliverable.id), ['a', 'c']);

  context.toggleDeliverableInSelection(c, project);
  assert.equal(dock.multi.length, 0);
  assert.equal(dock.deliverable, a);

  context.toggleDeliverableInSelection(a, project);
  assert.equal(dock.deliverable, null);
  assert.equal(context.getCommandDockTargets().length, 0);

  context.toggleDeliverableInSelection(a, project);
  context.toggleDeliverableInSelection(b, project);
  context.selectDeliverableForCommands(c, project);
  assert.equal(dock.multi.length, 0);
  assert.equal(dock.deliverable, c);
});

test('a multi-selection offers only pin, unpin and status, and they act on every row', async () => {
  const { context } = setup();
  const project = { id: 'P1' };
  const [a, b, c] = [{ id: 'a', pinned: true }, { id: 'b' }, { id: 'c' }];
  context.setCommandDockTargets([a, b, c].map((deliverable) => ({ deliverable, project })));

  let items = commands(context);
  assert.deepEqual(Array.from(items, (item) => item.label), ['Complete', 'Pin 2 deliverables', 'Unpin 1 deliverable']);

  const target = () => ({ targets: context.getCommandDockTargets() });
  await items.find((item) => item.key === 'pin').run(target());
  assert.deepEqual([a, b, c].map((d) => d.pinned), [true, true, true]);
  assert.equal(context.saveCount, 1);

  items = commands(context);
  assert.deepEqual(Array.from(items, (item) => item.label), ['Complete', 'Unpin 3 deliverables']);
  await items.find((item) => item.key === 'unpin').run(target());
  assert.deepEqual([a, b, c].map((d) => d.pinned), [false, false, false]);

  await items.find((item) => item.key === 'status:Complete').run(target());
  assert.deepEqual([a, b, c].map((d) => d.status), ['Complete', 'Complete', 'Complete']);
  assert.equal(commands(context).find((item) => item.key === 'status:Complete').checked, true);
});

test('a single selection keeps the one pin toggle', async () => {
  const { context } = setup();
  const deliverable = { id: 'a' };
  const project = { id: 'P1' };
  context.selectDeliverableForCommands(deliverable, project);
  const pin = commands(context).find((item) => item.key === 'pin');
  assert.equal(pin.label, 'Pin deliverable');
  assert.ok(!commands(context).some((item) => item.key === 'unpin'));
  await pin.run({ deliverable, project, targets: context.getCommandDockTargets() });
  assert.equal(deliverable.pinned, true);
  assert.equal(commands(context).find((item) => item.key === 'pin').label, 'Unpin deliverable');
});
