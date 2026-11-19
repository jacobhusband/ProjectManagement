const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');

function loadPicker(overrides = {}) {
  const context = vm.createContext(overrides);
  for (const name of ['searchTimesheetProjects', 'openAddTimesheetProjectDialog',
    'addTimesheetEntry', 'formatTimesheetProjectName']) {
    const match = source.match(new RegExp(String.raw`^function ${name}\([\s\S]*?^}\r?$`, 'm'));
    assert.ok(match, name);
    vm.runInContext(match[0], context);
  }
  return context;
}

test('project search ranks exact numbers and matches terms across project fields', () => {
  const { searchTimesheetProjects } = loadPicker();
  const annex = { id: '24-1010', name: 'Annex' };
  const clinic = { id: '24-101', name: 'Montréal Clinic', nick: 'North End' };
  const other = { id: '24-202', name: 'Clinic Annex', deliverables: [{ name: 'Survey' }] };
  const projects = [annex, clinic, other];
  const search = (query) => Array.from(searchTimesheetProjects(projects, query));

  assert.deepEqual(search('24101'), [clinic, annex]);
  assert.deepEqual(search('  #24-101  '), [clinic, annex]);
  assert.deepEqual(search('end montreal'), [clinic]);
  assert.deepEqual(search('north 24101'), [clinic]);
  assert.deepEqual(search('   CLINIC   '), [other, clinic]);
  assert.deepEqual(search('survey'), []);
});

test('picker shows one option per project, expands on request, and adds a project-only row', () => {
  const projects = Array.from({ length: 12 }, (_, index) => ({
    id: `24-${100 + index}`,
    name: index === 11 ? 'West Office' : 'East Office',
    deliverables: index === 11 ? [] : [{ name: 'Survey' }, { name: 'Submittal' }],
  }));
  const entries = [];
  let saved = 0;
  const nodes = {
    timesheetProjectDlg: {},
    timesheetProjectList: {
      set innerHTML(_) { this.children = []; },
      get firstElementChild() { return this.children[0]; },
      appendChild(child) { this.children.push(child); },
    },
    timesheetProjectSearch: { focus() {} },
    timesheetProjectResultsStatus: {},
    timesheetProjectMore: {},
  };
  const { openAddTimesheetProjectDialog } = loadPicker({
    db: projects,
    document: { getElementById: (id) => nodes[id] },
    el: (tag, props) => ({ tag, ...props, focus() {}, click() { this.onclick(); } }),
    showDialog: (dialog) => (dialog.open = true),
    closeDlg: (id) => { nodes[id].open = false; },
    requestAnimationFrame: (callback) => callback(),
    currentTimesheetWeek: 'current week',
    formatWeekKey: (week) => week,
    getWeekEntries: () => entries,
    setWeekEntries: (week, rows) => {
      assert.equal(week, 'current week');
      assert.equal(rows, entries);
    },
    createTimesheetEntryId: () => 'ts_new',
    getDefaultPmInitials: () => 'JH',
    getDisciplineFunction: () => 'E',
    toast() {},
    saveTimesheets: () => { saved++; },
    renderTimesheets() {},
  });

  openAddTimesheetProjectDialog();
  const search = nodes.timesheetProjectSearch;
  const list = nodes.timesheetProjectList;
  const more = nodes.timesheetProjectMore;
  assert.equal(list.children.length, 10);
  assert.equal(more.hidden, false);
  more.onclick();
  assert.equal(list.children.length, 12);
  assert.equal(new Set(list.children.map((option) => option.textContent)).size, 12);
  assert.equal(more.hidden, true);

  search.value = 'missing';
  search.oninput();
  assert.equal(nodes.timesheetProjectResultsStatus.textContent, 'No projects found.');
  search.value = 'west';
  search.oninput();
  assert.equal(list.children.length, 1);
  assert.equal(list.firstElementChild.tag, 'button');
  search.onkeydown({ key: 'Enter', preventDefault() {} });
  assert.equal(nodes.timesheetProjectDlg.open, false);
  assert.equal(saved, 1);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].projectId, '24-111');
  assert.equal(entries[0].projectName, 'West Office');
  assert.equal(entries[0].deliverableId, '');
  assert.equal(entries[0].serviceDescription, '');
});
