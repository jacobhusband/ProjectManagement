const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const context = vm.createContext({ Date, console, MAX_HOURS_PER_DAY: 24, WFH_SUFFIX: ' - WFH',
    timesheetDb: { weeks: {}, lastModified: 'before' },
    userSettings: { defaultPmInitials: 'JH' },
    getDisciplineFunction: () => 'E',
    saveTimesheets: async () => true,
    renderTimesheets: () => {},
  });
  const sources = ['script.js', 'industry-projects.js'].map(file =>
    fs.readFileSync(path.join(__dirname, '..', file), 'utf8')).join('\n');
  const names = ['getWeekStartDate', 'formatWeekKey', 'getTimesheetProjectMatchKey',
    'getTimesheetEntryMatchKey', 'getWeekEntries', 'setWeekEntries', 'normalizeTimesheetHours',
    'createTimesheetEntryId', 'formatTimesheetProjectName', 'getDefaultPmInitials',
    'getTimesheetTaskNumberForDeliverable', 'getTimesheetEntryDescription', 'stripWfhSuffix',
    'hasWfhSuffix', 'appendWfhSuffix', 'getMissingDeliverables', 'normalizeDeliverableNames',
    'parseDeliverableList', 'addDeliverableHoursToTimesheet', 'parseTimesheetPromptDate',
    'advanceTimesheetHoursPrompt'];
  names.forEach(name => {
    const match = sources.match(new RegExp(`^(?:async )?function ${name}\\([^]*?^}`, 'm'));
    assert.ok(match, name);
    vm.runInContext(match[0], context);
  });
  return context;
}
const project = { id: '123', name: 'Office' };
const deliverable = { id: 'd1', name: 'DD90' };

test('creates today by default and accumulates without duplicate rows or descriptions', async () => {
  const c = setup();
  await c.addDeliverableHoursToTimesheet(project, deliverable, 1.5);
  await c.addDeliverableHoursToTimesheet(project, deliverable, 2);
  const entries = c.getWeekEntries(c.formatWeekKey(new Date()));
  const day = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][new Date().getDay()];
  assert.equal(entries.length, 1);
  assert.equal(entries[0].hours[day], 3.5);
  assert.equal(entries[0].serviceDescription, 'DD90');
});

test('uses selected date across week/year boundaries and preserves other days', async () => {
  const c = setup();
  const saturday = new Date(2026, 0, 3, 12);
  const sunday = new Date(2026, 0, 4, 12);
  await c.addDeliverableHoursToTimesheet(project, deliverable, 2, saturday);
  await c.addDeliverableHoursToTimesheet(project, deliverable, 3, sunday);
  await c.addDeliverableHoursToTimesheet(project, deliverable, 1, new Date(2026, 0, 2, 12));
  assert.equal(Object.keys(c.timesheetDb.weeks).length, 2);
  const first = c.getWeekEntries(c.formatWeekKey(saturday))[0];
  assert.equal(first.hours.sat, 2);
  assert.equal(first.hours.fri, 1);
  assert.equal(c.getWeekEntries(c.formatWeekKey(sunday))[0].hours.sun, 3);
});

test('reuses project row, preserves metadata and WFH, prefers exact deliverable', async () => {
  const c = setup();
  const date = new Date(2026, 8, 11, 12);
  const key = c.formatWeekKey(date);
  c.setWeekEntries(key, [{ id: 'existing', projectId: '123', deliverableId: 'other',
    serviceDescription: 'Survey - WFH', taskNumber: '0.SV', hours: { fri: 1, mon: 4 } }]);
  await c.addDeliverableHoursToTimesheet(project, deliverable, 2, date);
  let entries = c.getWeekEntries(key);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].serviceDescription, 'Survey, DD90 - WFH');
  assert.equal(entries[0].taskNumber, '0.SV');
  assert.equal(entries[0].hours.mon, 4);
  entries.push({ id: 'exact', projectId: '123', deliverableId: 'd1', hours: { fri: 0 } });
  await c.addDeliverableHoursToTimesheet(project, deliverable, 1, date);
  entries = c.getWeekEntries(key);
  assert.equal(entries[0].hours.fri, 3);
  assert.equal(entries[1].hours.fri, 1);
});

test('rejects invalid hours and daily totals above 24 without mutation', async () => {
  const c = setup();
  for (const hours of [0, -1, NaN, Infinity, 25, 0.01]) {
    await assert.rejects(c.addDeliverableHoursToTimesheet(project, deliverable, hours));
  }
  await c.addDeliverableHoursToTimesheet({ id: 'other' }, deliverable, 23);
  const before = JSON.stringify(c.timesheetDb);
  await assert.rejects(c.addDeliverableHoursToTimesheet(project, deliverable, 2), /Only 1.0 hours/);
  assert.equal(JSON.stringify(c.timesheetDb), before);
});

test('failed save restores existing data and removes newly created weeks', async () => {
  const c = setup();
  await c.addDeliverableHoursToTimesheet(project, deliverable, 2);
  const before = JSON.stringify(c.timesheetDb);
  c.saveTimesheets = async () => false;
  await assert.rejects(c.addDeliverableHoursToTimesheet(project, deliverable, 1), /Failed to save/);
  assert.equal(JSON.stringify(c.timesheetDb), before);
  await assert.rejects(c.addDeliverableHoursToTimesheet(project, deliverable, 1, new Date(2000, 0, 1)), /Failed to save/);
  assert.equal(JSON.stringify(c.timesheetDb), before);
});

test('dates use local calendar days and reject impossible dates', () => {
  const c = setup();
  assert.equal(c.parseTimesheetPromptDate('2026-09-11').getDate(), 11);
  assert.equal(c.parseTimesheetPromptDate('09/11/2026').getMonth(), 8);
  for (const text of ['02/30/2026', '2026-13-01', 'garbage']) {
    assert.equal(c.parseTimesheetPromptDate(text), null);
  }
  assert.equal(c.parseTimesheetPromptDate('').toDateString(), new Date().toDateString());
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  assert.equal(c.parseTimesheetPromptDate('yesterday').toDateString(), yesterday.toDateString());
});

test('prompt validates hours, defaults date to today, and prevents double submission', async () => {
  const c = setup();
  c.industryActivePrompt = { project, deliverable, step: 0, values: {} };
  c.toast = () => {};
  c.setPromptStep = step => { c.industryActivePrompt.step = step; };
  await c.advanceTimesheetHoursPrompt('invalid');
  assert.equal(c.industryActivePrompt.step, 0);
  await c.advanceTimesheetHoursPrompt('2.5');
  assert.equal(c.industryActivePrompt.step, 1);
  let calls = 0;
  let finish;
  c.addDeliverableHoursToTimesheet = async (p, d, hours, date) => {
    calls++;
    assert.equal(hours, '2.5');
    assert.equal(date.toDateString(), new Date().toDateString());
    await new Promise(resolve => { finish = resolve; });
    return { hours: 2.5 };
  };
  c.cancelCommandDockPrompt = () => { c.industryActivePrompt = null; };
  c.setCommandDockExpanded = () => {};
  c.industryCommandDock = null;
  c.getProjectShortName = () => 'Office';
  c.formatPromptDate = date => date.toDateString();
  const pending = c.advanceTimesheetHoursPrompt('');
  await c.advanceTimesheetHoursPrompt('');
  assert.equal(calls, 1);
  finish();
  await pending;
  assert.equal(c.industryActivePrompt, null);
});
