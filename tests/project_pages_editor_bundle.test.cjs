const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('built classic script exposes the save queue on the browser global', async () => {
  const context = vm.createContext({ console, setTimeout, clearTimeout });
  // A classic script's top-level var and window properties share a global.
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    '../project-pages-editor/dist/project-pages-editor.js'), 'utf8'), context);
  const api = context.ProjectPagesEditor;
  for (const name of ['mount', 'unmount', 'setDocument', 'flushSave', 'createSaveQueue']) {
    assert.equal(typeof api[name], 'function', name);
  }
  let writes = 0;
  const queue = api.createSaveQueue({ persist: async () => { writes++; return true; } });
  queue.dirty();
  assert.equal(await queue.flush(), true);
  assert.equal(writes, 1);
  assert.equal(queue.isDirty, false);
});
