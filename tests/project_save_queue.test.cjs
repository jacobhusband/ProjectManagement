const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  const isAsync = source.slice(Math.max(0, start - 6), start) === 'async ';
  // Skip the parameter list first: defaults such as `{ silent = false } = {}` contain braces.
  let paren = source.indexOf('(', start) + 1;
  for (let parens = 1; parens; paren++) {
    if (source[paren] === '(') parens++;
    if (source[paren] === ')') parens--;
  }
  const open = source.indexOf('{', paren);
  let depth = 1;
  let end = open + 1;
  while (depth && end < source.length) {
    if (source[end] === '{') depth++;
    if (source[end] === '}') depth--;
    end++;
  }
  return (isAsync ? 'async ' : '') + source.slice(start, end);
}
function context(api) {
  const toasts = [];
  const scope = vm.createContext({
    console: { warn() {} },
    window: { pywebview: { api } },
    db: [],
    projectDataLoadError: '',
    projectSaveInFlight: null,
    projectSaveFollowUp: null,
    toasts,
    toast: (message) => toasts.push(message),
    migrateProjects: (raw) => ({ data: raw, didMigrate: false }),
    migrateStatuses() {},
    syncPinnedProjectOrders() {},
    syncProjectAttachmentFields() {},
    getProjectDeliverables: () => [],
    syncDeliverableAttachmentFields() {},
    syncDeliverableWorkItemFields() {},
  });
  for (const name of ['load', 'queueProjectSave', 'save']) {
    vm.runInContext(extract(name), scope);
  }
  return scope;
}
const flush = () => new Promise((resolve) => setImmediate(resolve));

test('project saves run one at a time and the last one sends the latest projects', async () => {
  let active = 0;
  let maxActive = 0;
  const sent = [];
  const finish = [];
  const c = context({
    save_tasks(data) {
      active++;
      maxActive = Math.max(maxActive, active);
      sent.push(data.map((project) => project.id));
      return new Promise((resolve) => finish.push(() => { active--; resolve({ status: 'success' }); }));
    },
  });

  c.db = [{ id: 'a' }];
  const first = c.save({ silent: true });
  c.db = [{ id: 'b' }];
  const second = c.save({ silent: true });
  c.db = [{ id: 'c' }];
  const third = c.save({ silent: true });
  await flush();
  assert.equal(finish.length, 1);

  finish.shift()();
  assert.equal(await first, true);
  await flush();
  assert.equal(finish.length, 1, 'requests made during a save share one follow-up save');
  finish.shift()();

  assert.equal(await second, true);
  assert.equal(await third, true);
  assert.equal(maxActive, 1);
  assert.deepEqual(sent, [['a'], ['c']]);
});

test('a failed save still lets the queued follow-up save run', async () => {
  const results = [{ status: 'error', message: 'disk full' }, { status: 'success' }];
  const sent = [];
  const c = context({
    save_tasks(data) {
      sent.push(data.length);
      return Promise.resolve(results.shift());
    },
  });

  c.db = [{ id: 'a' }];
  const first = c.save({ silent: true });
  const second = c.save({ silent: true });

  assert.equal(await first, false);
  assert.equal(await second, true);
  assert.equal(sent.length, 2);
});

test('a failed project load pauses saving instead of overwriting projects with an empty list', async () => {
  const saves = [];
  const c = context({
    get_tasks: async () => ({ status: 'error', message: 'tasks.json is damaged and no readable backup was found' }),
    save_tasks: async (data) => { saves.push(data); return { status: 'success' }; },
  });

  const loaded = await c.load();

  assert.ok(Array.isArray(loaded));
  assert.equal(loaded.length, 0);
  assert.match(c.projectDataLoadError, /damaged/);
  c.db = loaded;
  assert.equal(await c.save({ silent: true }), false);
  assert.equal(await c.save(), false);
  assert.equal(saves.length, 0);
  assert.equal(c.toasts.length, 1);
});

test('a load that throws also pauses saving, and a later successful load resumes it', async () => {
  let fail = true;
  const saves = [];
  const c = context({
    get_tasks: async () => {
      if (fail) throw new Error('bridge unavailable');
      return [{ id: '240001' }];
    },
    save_tasks: async (data) => { saves.push(data); return { status: 'success' }; },
  });

  await c.load();
  assert.equal(await c.save({ silent: true }), false);

  fail = false;
  c.db = await c.load();
  assert.equal(c.projectDataLoadError, '');
  assert.equal(await c.save({ silent: true }), true);
  assert.equal(saves.length, 1);
});
