const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../industry-projects.js'), 'utf8');

function extract(name) {
  const match = source.match(new RegExp(String.raw`^(?:async )?function ${name}\([\s\S]*?^}\r?$`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0];
}

// The command line filters commands by default and only searches projects or
// deliverables when the query starts with "#".
function runFilter(value, items, options = {}) {
  const section = { querySelector: () => null, hidden: false };
  const dock = {
    input: { value },
    items: items.map(item => ({ ...item, node: { hidden: false }, section })),
    sections: [{ key: 'target', section, limit: options.limit || 0, more: { hidden: true, textContent: '' } }],
    activeIndex: options.activeIndex ?? -1,
  };
  const context = vm.createContext({
    industryCommandDock: dock,
    getVisibleCommandDockItems: () => dock.items.filter(item => !item.node.hidden),
    setCommandDockActive: index => { dock.activeIndex = index; },
  });
  vm.runInContext(
    [
      extract('parseCommandDockQuery'),
      extract('isCommandDockTargetItem'),
      extract('commandDockWithinOneEdit'),
      extract('scoreCommandDockMatch'),
      extract('filterCommandDock'),
      'filterCommandDock();',
    ].join('\n'),
    context
  );
  if (options.inspect) options.inspect(dock, context);
  return dock.items.filter(item => !item.node.hidden).map(item => item.label);
}

const items = [
  { key: 'project:24-101', kind: 'project', label: 'Harborview Clinic', search: '24-101 Harborview Clinic' },
  { key: 'project:24-202', kind: 'project', label: 'Maple Street Lofts', search: '24-202 Maple Street Lofts', searchOnly: true },
  { key: 'deliverable:d1', kind: 'deliverable', label: 'DD90', search: 'DD90 in progress' },
  { key: 'pin', label: 'Pin deliverable', search: 'pin deliverable' },
  { key: 'add-deliverable', label: 'Add Deliverable', search: 'add deliverable new create' },
];

test('a number selects only its assigned hotkey; # still searches project numbers', () => {
  const numbered = [...items, { key: 'hotkey:1', label: 'Publish', search: '1 Publish' },
    { key: 'tool:other', label: 'Tool 1' }];
  assert.deepEqual(runFilter('1', numbered), ['Publish']);
  assert.deepEqual(runFilter('9', numbered), []);
  assert.deepEqual(runFilter('#24-101', numbered), ['Harborview Clinic']);
});

test('an empty line browses targets and commands, skipping search-only entries', () => {
  assert.deepEqual(runFilter('', items), [
    'Harborview Clinic',
    'DD90',
    'Pin deliverable',
    'Add Deliverable',
  ]);
});

test('a plain query searches commands only', () => {
  assert.deepEqual(runFilter('deliverable', items), ['Pin deliverable', 'Add Deliverable']);
  assert.deepEqual(runFilter('harborview', items), []);
  assert.deepEqual(runFilter('dd90', items), []);
});

test('a leading # searches projects and deliverables only', () => {
  assert.deepEqual(runFilter('#harborview', items), ['Harborview Clinic']);
  assert.deepEqual(runFilter('#dd90', items), ['DD90']);
  assert.deepEqual(runFilter('#deliverable', items), []);
});

test('# alone lists every target, including search-only projects', () => {
  assert.deepEqual(runFilter('#', items), ['Harborview Clinic', 'Maple Street Lofts', 'DD90']);
  assert.deepEqual(runFilter('# maple', items), ['Maple Street Lofts']);
});

test('commands tolerate one substituted, extra, missing, or transposed letter', () => {
  for (const query of ['delivarable', 'deliverrable', 'delverable', 'delivreable']) {
    assert.deepEqual(runFilter(query, items), ['Pin deliverable', 'Add Deliverable'], query);
  }
  assert.deepEqual(runFilter('add delverable', items), ['Add Deliverable']);
  assert.deepEqual(runFilter('delvxxable', items), []);
});

test('target names tolerate typos while identifiers and short queries stay literal', () => {
  assert.deepEqual(runFilter('#harbrview clinc', items), ['Harborview Clinic']);
  assert.deepEqual(runFilter('#mapel', items), ['Maple Street Lofts']);
  assert.deepEqual(runFilter('#24-102', items), []);
  assert.deepEqual(runFilter('#dd91', items), []);
  assert.deepEqual(runFilter('pn', items), []);
  assert.deepEqual(runFilter('harbrview', items), []);
});

test('literal matches rank above typos before limits and receive keyboard selection', () => {
  const candidates = [
    { kind: 'project', label: 'Maple Court' },
    { kind: 'project', label: 'Mapel Court' },
  ];
  assert.deepEqual(runFilter('#mapel', candidates, {
    limit: 1,
    activeIndex: 0,
    inspect: dock => assert.equal(dock.items[dock.activeIndex].label, 'Mapel Court'),
  }), ['Mapel Court']);
});

test('clearing a query restores browse order and preserves the selected item', () => {
  runFilter('deliverable', [
    { label: 'Delverable' },
    { label: 'Deliverable' },
  ], { inspect: (dock, context) => {
    assert.equal(dock.items[dock.activeIndex].label, 'Deliverable');
    dock.input.value = '';
    vm.runInContext('filterCommandDock();', context);
    assert.deepEqual(dock.items.map(item => item.label), ['Delverable', 'Deliverable']);
    assert.equal(dock.items[dock.activeIndex].label, 'Deliverable');
  } });
});
