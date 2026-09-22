const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8');
function extract(name) {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
}
function context(extra = {}) {
  const ctx = vm.createContext({
    console, confirm: () => true, createId: () => 'trash-id',
    toast: () => {}, render: () => {}, renderGlobalPagesView: () => {}, renderPageView: () => {},
    pageNav: {}, globalPages: [], globalPageTrash: [], activeGlobalPageId: null,
    flushPageSave: async () => true, save: async () => true, saveGlobalPages: async () => true,
    getProjectSubpages: (p) => p.subpages,
    getProjectSubpageById: (p, id) => p.subpages.find((page) => page.id === id),
    getProjectSubpageDescendantIds: () => new Set(['child']),
    normalizeGlobalPage: (p) => p,
    ...extra,
  });
  return ctx;
}
test('project trash preserves descendants, files and IDs through serialization and restore', async () => {
  const ctx = context();
  vm.runInContext(extract('deleteProjectSubpage') + '\n' + extract('restoreNotesTrash'), ctx);
  const project = { subpages: [
    { id: 'parent', title: 'Parent', parentId: null, page: { html: '<div data-page-file="book.xlsx"></div>' } },
    { id: 'child', title: 'Child', parentId: 'parent', page: { html: 'Child notes' } },
    { id: 'other', title: 'Other' },
  ] };
  await ctx.deleteProjectSubpage(project, project.subpages[0]);
  assert.deepEqual(project.subpages.map(p => p.id), ['other']);
  const reloaded = JSON.parse(JSON.stringify(project));
  assert.equal(reloaded.pageTrash[0].pages.length, 2);
  await ctx.restoreNotesTrash(reloaded, 'trash-id');
  assert.equal(reloaded.pageTrash.length, 0);
  assert.equal(reloaded.subpages.find(p => p.id === 'child').parentId, 'parent');
  assert.ok(reloaded.subpages.find(p => p.id === 'parent').page.html.includes('book.xlsx'));
});
test('failed trash and restore writes roll back without deleting data', async () => {
  let succeeds = false;
  const ctx = context({ save: async () => succeeds });
  vm.runInContext(extract('deleteProjectSubpage') + '\n' + extract('restoreNotesTrash'), ctx);
  const original = { id: 'parent', title: 'Keep me', page: { html: 'important' } };
  const project = { subpages: [original] };
  await ctx.deleteProjectSubpage(project, original);
  assert.equal(project.subpages[0], original);
  assert.equal(project.pageTrash.length, 0);
  succeeds = true;
  await ctx.deleteProjectSubpage(project, original);
  succeeds = false;
  await ctx.restoreNotesTrash(project, 'trash-id');
  assert.equal(project.subpages.length, 0);
  assert.equal(project.pageTrash[0].pages[0], original);
});
test('workspace trash round-trips independently of live pages', async () => {
  const ctx = context({ globalPages: [{ id: 'a', title: 'A', page: { html: 'note' } }] });
  vm.runInContext(extract('deleteGlobalPage') + '\n' + extract('restoreNotesTrash'), ctx);
  await ctx.deleteGlobalPage(ctx.globalPages[0]);
  assert.equal(ctx.globalPages.length, 0);
  ctx.globalPageTrash = JSON.parse(JSON.stringify(ctx.globalPageTrash));
  await ctx.restoreNotesTrash(null, 'trash-id');
  assert.equal(ctx.globalPages[0].page.html, 'note');
  assert.equal(ctx.globalPageTrash.length, 0);
});
test('failed flush prevents navigation; retry permits it', async () => {
  let succeeds = false, renders = 0;
  const ctx = context({
    pageNavigationRequest: 0, pageEditorTarget: {}, pageNav: { project: { id: 'A' } },
    flushPageSave: async () => succeeds,
    ensurePageViewReady: () => {}, showPageView: () => {}, renderPageView: () => renders++,
  });
  vm.runInContext(extract('openProjectPage') + '\n' + extract('openGlobalPage'), ctx);
  await ctx.openProjectPage({ id: 'B' });
  assert.equal(ctx.pageNav.project.id, 'A');
  await ctx.openGlobalPage({ id: 'G' });
  assert.equal(ctx.pageNav.project.id, 'A');
  succeeds = true;
  await ctx.openProjectPage({ id: 'B' });
  assert.equal(ctx.pageNav.project.id, 'B');
  assert.equal(renders, 1);
});
test('only the newest navigation request wins when flushing is slow', async () => {
  const pending = [];
  const ctx = context({
    pageNavigationRequest: 0, pageEditorTarget: {},
    flushPageSave: () => new Promise(resolve => pending.push(resolve)),
    ensurePageViewReady: () => {}, showPageView: () => {},
  });
  vm.runInContext(extract('openProjectPage'), ctx);
  const b = ctx.openProjectPage({ id: 'B' });
  const c = ctx.openProjectPage({ id: 'C' });
  pending[1](true); await c;
  pending[0](true); await b;
  assert.equal(ctx.pageNav.project.id, 'C');
});
