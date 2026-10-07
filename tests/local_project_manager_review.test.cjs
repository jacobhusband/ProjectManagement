const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
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
  return source.slice(source.slice(start - 6, start) === 'async ' ? start - 6 : start, end);
}
function context(candidateFiles) {
  const scope = vm.createContext({
    copyProjectLocallyDialogState: {
      syncReviewVisible: true,
      localProjectPath: 'C:\\Local Projects\\260243',
      launchContext: null,
      sync: { previewLoaded: true, resolvedServerProjectPath: 'S:\\260243', candidateFiles },
    },
    getLocalProjectManagerServerPathInfo: () => ({ path: 'S:\\260243' }),
    deepCloneJson: (value, fallback) => value ?? fallback,
  });
  for (const name of ['getLocalProjectManagerCopyToServerReviewGroups', 'buildLocalProjectManagerCopyToServerReviewPayload']) {
    vm.runInContext(extract(name), scope);
  }
  return scope;
}

const rows = () => [
  { relativePath: 'Electrical\\E01.dwg', changeType: 'newer', selected: true },
  { relativePath: 'Electrical\\E02.dwg', changeType: 'missing', selected: true },
  { relativePath: 'Electrical\\old.dwg', changeType: 'missing', selected: false, directionLabel: 'Deleted on server' },
  { relativePath: 'Electrical\\gone.dwg', changeType: 'deleted', selected: false, directionLabel: 'Deleted locally' },
];

test('the server review never sends rows that were not preselected', () => {
  const c = context(rows());

  const payload = c.buildLocalProjectManagerCopyToServerReviewPayload();
  const groups = c.getLocalProjectManagerCopyToServerReviewGroups(c.copyProjectLocallyDialogState.sync);

  assert.deepEqual(Array.from(payload.localSelectedRelativePaths), ['Electrical\\E01.dwg', 'Electrical\\E02.dwg']);
  assert.deepEqual(Array.from(groups.skippedFiles, (row) => row.relativePath), ['Electrical\\old.dwg', 'Electrical\\gone.dwg']);
  assert.equal(groups.deleteFiles.length, 0);
});

test('a deletion is only sent once it is explicitly selected, and it is listed as a deletion', () => {
  const candidates = rows();
  candidates[3].selected = true;
  const c = context(candidates);

  const payload = c.buildLocalProjectManagerCopyToServerReviewPayload();
  const groups = c.getLocalProjectManagerCopyToServerReviewGroups(c.copyProjectLocallyDialogState.sync);

  assert.ok(payload.localSelectedRelativePaths.includes('Electrical\\gone.dwg'));
  assert.deepEqual(Array.from(groups.deleteFiles, (row) => row.relativePath), ['Electrical\\gone.dwg']);
  assert.equal(groups.replaceFiles.some((row) => row.changeType === 'deleted'), false);
});

function comparisonContext(result, { localProjectExists = true } = {}) {
  const calls = [];
  const c = context([]);
  Object.assign(c.copyProjectLocallyDialogState, {
    localProjectExists,
    activeTab: 'copy',
    syncReviewVisible: false,
    copyToLocal: { candidateFiles: [] },
  });
  Object.assign(c, {
    window: { pywebview: { api: { compare_project_timestamps: async () => {
      calls.push('compare');
      return result;
    } } } },
    renderCopyProjectLocallyDialog: () => {},
    shouldShowLocalProjectManagerServerPathFallback: () => false,
    normalizeWindowsPath: (value) => value,
    formatCopyProjectLocallySizeLabel: () => '1 MB',
    loadLocalProjectManagerDirectionPreview: async (direction) => {
      calls.push(direction);
      const state = direction === 'to_server'
        ? c.copyProjectLocallyDialogState.sync : c.copyProjectLocallyDialogState.copyToLocal;
      state.previewLoaded = true;
      state.candidateFiles = direction === 'to_server'
        ? [{ relativePath: 'Electrical/E01.dwg', scopeType: 'managed', changeType: 'newer', selected: true }]
        : [];
    },
  });
  for (const name of [
    'normalizeLocalProjectManagerDirectionCandidateFile',
    'applyLocalProjectManagerComparisonDirectionPreviews',
    'buildLocalProjectManagerComparisonBannerMessage',
    'runLocalProjectManagerTimestampComparison',
  ]) vm.runInContext(extract(name), c);
  return { c, calls };
}

function comparisonResult(localCandidates, serverCandidates = []) {
  return {
    status: 'success', summary: serverCandidates.length ? 'mixed' : 'local-newer',
    localToServerCandidates: localCandidates,
    serverToLocalCandidates: serverCandidates,
    conflictCandidateCount: 0,
  };
}

for (const discipline of ['Electrical', 'Plumbing', 'Mechanical']) {
  test(`Work Locally opens newer ${discipline} and Xrefs replacements first`, async () => {
    const paths = [`${discipline}/sheet.dwg`, 'Xrefs/background.dwg'];
    const result = comparisonResult(paths.map((relativePath) => ({
      relativePath, scopeType: 'managed', changeType: 'newer', selectedByDefault: true,
    })));
    const { c } = comparisonContext(result);
    await c.runLocalProjectManagerTimestampComparison();

    assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, true);
    assert.equal(c.copyProjectLocallyDialogState.activeTab, 'sync');
    const payload = c.buildLocalProjectManagerCopyToServerReviewPayload();
    assert.deepEqual(Array.from(payload.localSelectedRelativePaths), paths);
    assert.deepEqual(Array.from(payload.serverSelectedRelativePaths), []);
    assert.match(c.copyProjectLocallyDialogState.comparisonBannerMessage, /replace the older server copies/);
  });
}

test('mixed changes review local replacements before server downloads', async () => {
  const { c } = comparisonContext(comparisonResult([
    { relativePath: 'Electrical/local.dwg', scopeType: 'managed', changeType: 'newer', selectedByDefault: true },
  ], [
    { relativePath: 'Xrefs/server.dwg', scopeType: 'managed', changeType: 'newer', selectedByDefault: true },
  ]));
  await c.runLocalProjectManagerTimestampComparison();

  assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, true);
  assert.equal(c.copyProjectLocallyDialogState.copyToLocal.candidateFiles.length, 1);
  assert.deepEqual(Array.from(c.buildLocalProjectManagerCopyToServerReviewPayload().serverSelectedRelativePaths), []);
  assert.match(c.copyProjectLocallyDialogState.comparisonBannerMessage, /local files first/);
});

for (const [name, localCandidates, serverCandidates] of [
  ['server-only changes', [], [{ relativePath: 'Electrical/server.dwg', scopeType: 'managed', changeType: 'newer' }]],
  ['aligned copies', [], []],
  ['local additions outside managed folders', [{ relativePath: 'Arch/new.dwg', scopeType: 'additive_only', changeType: 'missing' }], []],
  ['unmanaged replacements', [{ relativePath: 'Reports/notes.txt', scopeType: 'additive_only', changeType: 'newer' }], []],
]) {
  test(`${name} keep the server-files view`, async () => {
    const { c } = comparisonContext(comparisonResult(localCandidates, serverCandidates));
    await c.runLocalProjectManagerTimestampComparison();
    assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, false);
    assert.equal(c.copyProjectLocallyDialogState.activeTab, 'copy');
  });
}

test('conflicts still require resolution before showing the replacement review', async () => {
  const result = comparisonResult([
    { relativePath: 'Electrical/local.dwg', scopeType: 'managed', changeType: 'newer' },
  ]);
  Object.assign(result, { summary: 'conflict', conflictCandidateCount: 1 });
  const { c } = comparisonContext(result);
  await c.runLocalProjectManagerTimestampComparison();
  assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, false);
});

test('first-time local copies do not run a comparison', async () => {
  const { c, calls } = comparisonContext(null, { localProjectExists: false });
  await c.runLocalProjectManagerTimestampComparison();
  assert.deepEqual(calls, []);
  assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, false);
});

test('older comparison responses check local changes before server changes', async () => {
  const { c, calls } = comparisonContext({ status: 'success', summary: 'local-newer' });
  await c.runLocalProjectManagerTimestampComparison();
  assert.deepEqual(calls, ['compare', 'to_server', 'to_local']);
  assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, true);
});

test('failed comparisons do not offer a replacement', async () => {
  const { c } = comparisonContext({ status: 'error', message: 'Server unavailable' });
  await c.runLocalProjectManagerTimestampComparison();
  assert.equal(c.copyProjectLocallyDialogState.syncReviewVisible, false);
  assert.equal(c.copyProjectLocallyDialogState.comparisonBannerMessage, 'Server unavailable');
  assert.equal(c.copyProjectLocallyDialogState.comparisonLoading, false);
});
