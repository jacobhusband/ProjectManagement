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
  return source.slice(start, end);
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
