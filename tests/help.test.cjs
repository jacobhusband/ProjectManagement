const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf('\n}\n', start) + 2;
  assert.ok(start >= 0 && end > start, name);
  return source.slice(start, end);
}
class Element {
  constructor(textContent = '') {
    Object.assign(this, { textContent, hidden: false, dataset: {}, attrs: {}, children: [], handlers: {} });
    const classes = new Set();
    this.classList = {
      add: value => classes.add(value), remove: value => classes.delete(value),
      contains: value => classes.has(value),
      toggle: (value, enabled) => enabled ? classes.add(value) : classes.delete(value),
    };
  }
  setAttribute(name, value) { this.attrs[name] = value; }
  querySelector() { return null; }
  addEventListener(name, fn, options) { (this.handlers[name] ||= []).push({ fn, options }); }
  dispatch(name, event) {
    for (const entry of [...(this.handlers[name] || [])]) {
      entry.fn(event);
      if (entry.options?.once) this.handlers[name] = this.handlers[name].filter(item => item !== entry);
    }
  }
  click() { this.dispatch('click', { target: this, stopPropagation() {} }); }
  replaceChildren(child) { this.children = [child]; child.parentNode = this; }
  insertBefore(child) { this.children = [child]; child.parentNode = this; }
  focus() { this.focused = true; }
}
function setup() {
  const sections = [...html.matchAll(/<section class="help-topic" id="([^"]+)" data-help-topic="([^"]+)"[^>]*>([\s\S]*?)<\/section>/g)]
    .map(([, id, topic, content]) => Object.assign(new Element(content.replace(/<[^>]+>/g, ' ')), {
      id, dataset: { helpTopic: topic },
    }));
  const buttons = sections.map(section => Object.assign(new Element(), { dataset: { ...section.dataset } }));
  const ids = Object.fromEntries(['helpSearch', 'helpSearchStatus', 'helpNoResults', 'helpDlgContent',
    'helpDlg', 'toolHelpDlg', 'toolHelpContent', 'toolHelpTitle'].map(id => [id, new Element()]));
  const document = {
    getElementById: id => ids[id],
    querySelectorAll: selector => selector.includes('Sidebar') ? buttons : sections,
    querySelector: selector => selector.includes('Sidebar')
      ? buttons.find(button => button.classList.contains('active'))
      : { dataset: { tab: 'notes' } },
  };
  const context = vm.createContext({ document, showDialog: dialog => { dialog.open = true; } });
  vm.runInContext(source.match(/const HELP_TOPICS = .*;/)[0], context);
  for (const name of ['getActiveHelpTopic', 'setActiveHelpTopic', 'filterHelpTopics', 'openHelp', 'bindToolHelp']) {
    vm.runInContext(extract(name), context);
  }
  const search = query => { ids.helpSearch.value = query; context.filterHelpTopics(); };
  return { context, ids, sections, buttons, search };
}

test('every help topic has matching navigation and searchable content', () => {
  const { context, sections } = setup();
  assert.deepEqual(sections.map(section => section.dataset.helpTopic),
    Array.from(vm.runInContext('HELP_TOPICS', context)));
  for (const section of sections) {
    assert.ok(html.includes(`aria-controls="${section.id}"`));
  }
});

test('help search finds current date and receipt instructions despite markup and whitespace', () => {
  const { context, ids, sections, buttons, search } = setup();
  context.openHelp('projects');
  search(' HARD   due ');
  assert.deepEqual(sections.filter(section => !section.hidden).map(section => section.dataset.helpTopic), ['deliverables']);
  assert.equal(ids.helpSearchStatus.textContent, '1 help topic found.');
  assert.equal(buttons.find(button => button.dataset.helpTopic === 'deliverables').attrs['aria-pressed'], 'true');
  search('receipt');
  assert.equal(sections.find(section => !section.hidden).dataset.helpTopic, 'timesheets');
  search('XREF');
  assert.equal(sections.find(section => !section.hidden).dataset.helpTopic, 'tools');
  search('quota');
  assert.equal(sections.find(section => !section.hidden).dataset.helpTopic, 'misc');
});

test('no-results recovery and reopening help restore topic navigation', () => {
  const { context, ids, sections, buttons, search } = setup();
  search('nonexistent-help-query');
  assert.equal(ids.helpNoResults.hidden, false);
  assert.ok(sections.every(section => section.hidden));
  assert.ok(buttons.every(button => button.hidden));
  context.openHelp('tools');
  assert.equal(ids.helpSearch.value, '');
  assert.equal(ids.helpNoResults.hidden, true);
  assert.ok(buttons.every(button => !button.hidden));
  assert.equal(sections.find(section => !section.hidden).dataset.helpTopic, 'tools');
  context.openHelp();
  assert.equal(sections.find(section => !section.hidden).dataset.helpTopic, 'notes');
});

test('tool help preserves live details, restores them on close, and returns focus', () => {
  const { context, ids } = setup();
  const trigger = new Element();
  const details = new Element('Loading details...');
  trigger.isConnected = true;
  trigger.replaceChildren(details);
  context.bindToolHelp(trigger, details, 'Example plugin');
  trigger.click();
  assert.equal(ids.toolHelpDlg.open, true);
  assert.equal(ids.toolHelpContent.children[0], details);
  details.textContent = 'COMMAND: loaded documentation';
  assert.equal(ids.toolHelpContent.children[0].textContent, 'COMMAND: loaded documentation');
  ids.toolHelpDlg.dispatch('close');
  assert.equal(details.parentNode, trigger);
  assert.equal(details.classList.contains('tool-help-details'), false);
  assert.equal(trigger.focused, true);
  assert.equal(trigger.attrs['aria-disabled'], 'false');
});

test('Space and Enter open help without scrolling or triggering the containing tool', () => {
  for (const key of [' ', 'Enter']) {
    const { context, ids } = setup();
    const trigger = new Element();
    const details = new Element();
    trigger.replaceChildren(details);
    context.bindToolHelp(trigger, details, 'Tool');
    let prevented = false, stopped = false;
    trigger.dispatch('keydown', { target: trigger, key,
      preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
    assert.equal(ids.toolHelpDlg.open, true);
    assert.equal(prevented, true);
    assert.equal(stopped, true);
  }
});

test('documentation clicks in hover content do not also open the help dialog', () => {
  const { context, ids } = setup();
  const trigger = new Element();
  const details = new Element();
  trigger.replaceChildren(details);
  context.bindToolHelp(trigger, details, 'Plugin');
  trigger.dispatch('click', { target: new Element('Documentation'), stopPropagation() {} });
  assert.equal(ids.toolHelpDlg.open, undefined);
});
