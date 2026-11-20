const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');

function extract(name) {
  const match = source.match(
    new RegExp(String.raw`^(?:async )?function ${name}\([\s\S]*?^}\r?$`, 'm')
  );
  assert.ok(match, `${name} exists in script.js`);
  return match[0];
}

function createFakeDocument() {
  const createNode = (type, tagName = '') => ({
    nodeType: type,
    tagName,
    className: '',
    children: [],
    _text: '',
    get textContent() {
      if (this.children.length) {
        return this.children.map((child) => child.textContent).join('');
      }
      return this._text;
    },
    set textContent(value) {
      this._text = String(value ?? '');
      this.children = [];
    },
    appendChild(child) {
      if (child.nodeType === 11) {
        this.children.push(...child.children);
      } else {
        this.children.push(child);
      }
      return child;
    },
  });

  return {
    createDocumentFragment: () => createNode(11),
    createElement: (tag) => createNode(1, tag.toUpperCase()),
    createTextNode: (text) => {
      const node = createNode(3);
      node._text = String(text ?? '');
      return node;
    },
  };
}

function loadSearchHelpers(overrides = {}) {
  const document = createFakeDocument();
  const context = vm.createContext({
    document,
    el: (tag, props = {}) => {
      const node = document.createElement(tag);
      Object.assign(node, props);
      return node;
    },
    getProjectDeliverables: (project) =>
      Array.isArray(project?.deliverables) ? project.deliverables : [],
    syncDeliverableWorkItemFields: () => {},
    getEffectiveDueStr: (deliverable) =>
      deliverable?.due || deliverable?.hardDue || deliverable?.softDue || '',
    ...overrides,
  });

  for (const name of [
    'foldProjectSearchText',
    'normalizeProjectSearchText',
    'buildFoldedTextMap',
    'getHighlightNeedles',
    'findHighlightTextRanges',
    'highlightText',
    'extractAccountFromPath',
    'createContextSnippet',
    'parseProjectSearchQuery',
    'doesProjectSearchTermMatchField',
    'filterProjectDeliverableRowsForSearch',
    'getMatchContext',
    'matches',
  ]) {
    vm.runInContext(extract(name), context);
  }
  return context;
}

const sampleProjects = [
  {
    id: '251476',
    name: 'AAA, 7935 Blue Diamond Rd., Las Vegas, NV',
    nick: 'Blue Diamond',
    path: 'M:\\MBH\\AAA\\2025\\251476 AAA, 7935 Blue Diamond Rd., Las Vegas, NV',
    notes: 'Coordinate service upgrade with NV Energy in Las Vegas.',
    deliverables: [
      { id: 'd_aaa_lv_permit', name: 'Permit Submittal', due: '11/25/2026', statuses: ['Waiting'] },
      { id: 'd_aaa_lv_rfi', name: 'RFI #1', due: '11/19/2026', statuses: ['In progress'] },
    ],
  },
  {
    id: '251208',
    name: 'AAA, 8225 Laguna Blvd. Ste 120, Elk Grove, CA',
    nick: '',
    path: 'M:\\MBH\\AAA\\251208 AAA, 8225 Laguna Blvd. Ste 120, Elk Grove, CA',
    notes: '',
    deliverables: [
      { id: 'd_aaa_eg_cd', name: 'CD Set', due: '12/01/2026', statuses: ['In progress'] },
    ],
  },
  {
    id: '260235',
    name: 'AAA, 2095 Diamond Blvd Suite B-135, Concord, CA',
    nick: 'Blue Diamond',
    path: 'M:\\MBH\\AAA\\2026\\260235 AAA, 2095 Diamond Blvd Suite B-135, Concord, CA',
    notes: '',
    deliverables: [
      { id: 'd_aaa_con_permit', name: 'Permit Submittal', due: '11/20/2026', statuses: ['Delivered'] },
      { id: 'd_aaa_con_rfi', name: 'RFI #2', due: '11/28/2026', statuses: ['Waiting'] },
    ],
  },
  {
    id: '260767',
    name: 'Taco Bell Cantina Expansion, 3717 S. Las Vegas Blvd. Suite #1C, Las Vegas, NV',
    nick: '',
    path: 'P:\\Valerio\\Taco Bell\\2026\\260767 Taco Bell Cantina Expansion, Las Vegas, NV',
    notes: '',
    deliverables: [
      { id: 'd_tb_lv', name: 'Permit Submittal', due: '11/22/2026', statuses: ['In progress'] },
    ],
  },
  {
    id: '250421',
    name: 'BofA, 3400 W. Magnolia Blvd., Burbank, CA',
    nick: '',
    path: '\\\\acies.lan\\cachedrive\\projects2\\Gensler\\BAC\\2025\\250421 BofA, 3400 W. Magnolia Blvd., Burbank, CA',
    notes: '',
    deliverables: [
      { id: 'd_bofa_burb', name: 'Plan Check Response', due: '11/19/2026', statuses: ['Pending Review'] },
    ],
  },
  {
    id: '251119',
    name: 'Montréal Clinic - Las Palmas, Vegas Rd',
    nick: '17th & Tustin',
    path: 'M:\\Ware Malcomb\\2025\\251119 Montreal Clinic',
    notes: '',
    deliverables: [
      { id: 'd_mtl_dd', name: 'DD90', due: '12/10/2026', statuses: ['In progress'] },
    ],
  },
];

test('multi-term project search finds AAA in Las Vegas regardless of order, quotes, commas, or connectors', () => {
  const { matches } = loadSearchHelpers();
  const findIds = (query) =>
    sampleProjects.filter((project) => matches(query, project)).map((project) => project.id);

  assert.deepEqual(findIds('AAA vegas'), ['251476']);
  assert.deepEqual(findIds('vegas AAA'), ['251476']);
  assert.deepEqual(findIds('"AAA" "vegas"'), ['251476']);
  assert.deepEqual(findIds('"AAA" and "vegas"'), ['251476']);
  assert.deepEqual(findIds('AAA and vegas'), ['251476']);
  assert.deepEqual(findIds('AAA, vegas'), ['251476']);
  assert.deepEqual(findIds('AAA + vegas'), ['251476']);
  assert.deepEqual(findIds('AAA'), ['251476', '251208', '260235']);
  assert.deepEqual(findIds('vegas'), ['251476', '260767', '251119']);
});

test('quoted phrases stay contiguous while unquoted terms match anywhere across fields', () => {
  const { matches } = loadSearchHelpers();
  const findIds = (query) =>
    sampleProjects.filter((project) => matches(query, project)).map((project) => project.id);

  // "las vegas" excludes "Las Palmas, Vegas Rd" (251119)
  assert.deepEqual(findIds('"las vegas"'), ['251476', '260767']);
  assert.deepEqual(findIds('"las vegas" aaa'), ['251476']);
  // Cross-field: name + nick
  assert.deepEqual(findIds('aaa blue diamond'), ['251476', '260235']);
  // Account extracted from path + name
  assert.deepEqual(findIds('gensler burbank'), ['250421']);
  assert.deepEqual(findIds('mbh concord'), ['260235']);
  // Path server/root noise does not falsely match projects
  assert.deepEqual(findIds('cachedrive'), []);
  assert.deepEqual(findIds('acies'), []);
  assert.deepEqual(findIds('projects2'), []);
  // Diacritics & connectors
  assert.deepEqual(findIds('montreal'), ['251119']);
  assert.deepEqual(findIds('17th and tustin'), ['251119']);
  assert.deepEqual(findIds('17th & tustin'), ['251119']);
});

test('project IDs support hyphen/hash formatting without confusing date searches', () => {
  const { matches } = loadSearchHelpers();
  const findIds = (query) =>
    sampleProjects.filter((project) => matches(query, project)).map((project) => project.id);

  assert.deepEqual(findIds('251476'), ['251476']);
  assert.deepEqual(findIds('#251476'), ['251476']);
  assert.deepEqual(findIds('25-1476'), ['251476']);
  // 11/19 matches deliverables due 11/19/2026, NOT project ID 251119
  assert.deepEqual(findIds('11/19'), ['251476', '250421']);
  assert.deepEqual(findIds('AAA 11/19'), ['251476']);
});

test('combining project and deliverable terms requires a single deliverable to cover remaining terms', () => {
  const { getMatchContext, filterProjectDeliverableRowsForSearch } = loadSearchHelpers();

  // "AAA permit waiting":
  // 251476 has Permit Submittal (Waiting) -> matches!
  // 260235 has Permit Submittal (Delivered) and RFI #2 (Waiting) -> must NOT match!
  const lvCtx = getMatchContext('AAA permit waiting', sampleProjects[0]);
  const concordCtx = getMatchContext('AAA permit waiting', sampleProjects[2]);
  assert.ok(lvCtx);
  assert.equal(lvCtx.allTermsMatchedProject, false);
  assert.deepEqual(
    Array.from(lvCtx.deliverables, (entry) => entry.deliverable.id),
    ['d_aaa_lv_permit']
  );
  assert.equal(concordCtx, null);

  // Filtering deliverable rows narrows to matching deliverables only when search needed them
  const lvRows = sampleProjects[0].deliverables.map((deliverable) => ({
    project: sampleProjects[0],
    deliverable,
  }));
  const mapDeliverableSearch = new Map([[sampleProjects[0], lvCtx]]);
  assert.deepEqual(
    Array.from(
      filterProjectDeliverableRowsForSearch(lvRows, mapDeliverableSearch),
      (row) => row.deliverable.id
    ),
    ['d_aaa_lv_permit']
  );

  // When all terms match on the project itself ("AAA vegas"), all deliverables stay visible
  const lvProjectCtx = getMatchContext('AAA vegas', sampleProjects[0]);
  assert.equal(lvProjectCtx.allTermsMatchedProject, true);
  const mapProjectSearch = new Map([[sampleProjects[0], lvProjectCtx]]);
  assert.deepEqual(
    Array.from(
      filterProjectDeliverableRowsForSearch(lvRows, mapProjectSearch),
      (row) => row.deliverable.id
    ),
    ['d_aaa_lv_permit', 'd_aaa_lv_rfi']
  );
});

test('highlightText and createContextSnippet highlight all matched multi-term tokens including accents', () => {
  const { parseProjectSearchQuery, highlightText, createContextSnippet } = loadSearchHelpers();

  const terms = parseProjectSearchQuery('AAA vegas');
  const frag = highlightText('AAA, 7935 Blue Diamond Rd., Las Vegas, NV', terms);
  assert.equal(frag.textContent, 'AAA, 7935 Blue Diamond Rd., Las Vegas, NV');
  const marks = frag.children
    .filter((child) => child.tagName === 'MARK')
    .map((child) => child.textContent);
  assert.deepEqual(marks, ['AAA', 'Vegas']);

  const accentFrag = highlightText('Montréal Clinic', parseProjectSearchQuery('montreal'));
  assert.equal(accentFrag.textContent, 'Montréal Clinic');
  assert.deepEqual(
    accentFrag.children
      .filter((child) => child.tagName === 'MARK')
      .map((child) => child.textContent),
    ['Montréal']
  );

  const longNote =
    'A'.repeat(80) + ' Coordinate AAA service upgrade in Las Vegas tomorrow.';
  const snippet = createContextSnippet(longNote, terms, 20);
  const snippetMarks = snippet.children
    .filter((child) => child.tagName === 'MARK')
    .map((child) => child.textContent);
  assert.ok(snippetMarks.includes('AAA'));
});

test('empty, whitespace, and lone-quote inputs are handled safely', () => {
  const { parseProjectSearchQuery, matches } = loadSearchHelpers();

  assert.deepEqual(Array.from(parseProjectSearchQuery('')), []);
  assert.deepEqual(Array.from(parseProjectSearchQuery('   ')), []);
  assert.deepEqual(Array.from(parseProjectSearchQuery('"')), []);
  assert.equal(matches('', sampleProjects[0]), true);
  assert.equal(matches('   ', sampleProjects[0]), true);
  assert.equal(matches('"', sampleProjects[0]), true);
  // Standalone connector stays searchable when it is the only token
  assert.equal(parseProjectSearchQuery('and').length, 1);
  assert.equal(parseProjectSearchQuery('&').length, 1);
  assert.equal(matches('&', sampleProjects[5]), true);
});
