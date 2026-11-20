const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const scriptSource = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const dockSource = fs.readFileSync(path.join(root, 'industry-projects.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function extract(name, from = scriptSource) {
  const match = from.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, `function ${name} should exist`);
  return match[0];
}

test('toast assigns .toast-notification, replaces previous toasts, and clears the command dock on Projects', () => {
  const appended = [];
  const removed = [];
  const doc = {
    body: {
      dataset: { activeTab: 'projects' },
      append(node) { appended.push(node); },
    },
    querySelector(selector) {
      if (selector === '.toast-notification') {
        return appended.find((node) => node.className === 'toast-notification' && !removed.includes(node)) || null;
      }
      return null;
    },
  };
  const context = vm.createContext({
    document: doc,
    setTimeout: () => 0,
    el: (tag, props) => ({
      tag,
      ...props,
      remove() { removed.push(this); },
    }),
  });
  vm.runInContext(extract('toast'), context);

  context.toast('First message');
  assert.equal(appended.length, 1);
  assert.equal(appended[0].className, 'toast-notification');
  assert.equal(appended[0].role, 'status');
  assert.match(appended[0].style, /--modern-command-height/);
  assert.match(appended[0].style, /pointer-events:\s*none/);

  context.toast('Second message');
  assert.equal(removed.length, 1);
  assert.equal(removed[0], appended[0]);
  assert.equal(appended.length, 2);

  doc.body.dataset.activeTab = 'tools';
  context.toast('Tools message');
  assert.match(appended[2].style, /inset:\s*auto auto 24px 50%/);
});

test('openProjectPathFolder routes to local copy when Work locally is enabled', async () => {
  const calls = [];
  const context = vm.createContext({
    isProjectWorkLocally: (project) => project?.workLocally === true,
    openProjectDirectory: async (project, kind) => { calls.push(['openProjectDirectory', kind, project.id]); },
    convertPath: (p) => p,
    toast: (msg) => calls.push(['toast', msg]),
    window: {
      pywebview: {
        api: {
          open_path: async (p) => { calls.push(['open_path', p]); return { status: 'success' }; },
        },
      },
    },
  });
  vm.runInContext(extract('openProjectPathFolder'), context);

  await context.openProjectPathFolder({ id: '250001', path: 'M:\\Server', localProjectPath: 'C:\\Local', workLocally: true });
  assert.deepEqual(calls, [['openProjectDirectory', 'local', '250001']]);

  calls.length = 0;
  await context.openProjectPathFolder({ id: '250001', path: 'M:\\Server', localProjectPath: 'C:\\Local', workLocally: false });
  assert.deepEqual(calls[0], ['open_path', 'M:\\Server']);
});

test('timesheets save queue serializes writes, debounces rapid input, and pauses on unreadable data', async () => {
  let active = 0;
  let maxConcurrent = 0;
  const savedPayloads = [];
  let releaseFirst;
  let calls = 0;

  const context = vm.createContext({
    timesheetDb: { weeks: { w1: [{ hours: { mon: 1 } }] }, expenses: {}, lastModified: null },
    console: { warn() {} },
    toast() {},
    setTimeout,
    clearTimeout,
    window: {
      pywebview: {
        api: {
          get_timesheets: async () => ({ status: 'error', code: 'data_file_unreadable', message: 'corrupt json' }),
          save_timesheets: async (payload) => {
            calls += 1;
            active += 1;
            maxConcurrent = Math.max(maxConcurrent, active);
            const snapshot = JSON.parse(JSON.stringify(payload));
            if (calls === 1) {
              await new Promise((resolve) => { releaseFirst = resolve; });
            }
            savedPayloads.push(snapshot);
            active -= 1;
            return { status: 'success' };
          },
        },
      },
    },
  });
  vm.runInContext(
    [
      'let timesheetsDataLoadError = "";',
      'let timesheetSaveInFlight = null;',
      'let timesheetSaveFollowUp = null;',
      'let timesheetSaveTimeout = null;',
      extract('normalizeIsoTimestamp'),
      extract('loadTimesheets'),
      extract('queueTimesheetSave'),
      extract('saveTimesheets'),
      extract('debouncedSaveTimesheets'),
      extract('flushPendingTimesheetSave'),
    ].join('\n'),
    context
  );

  // Concurrent direct saves must serialize and finish with the latest state.
  const first = context.saveTimesheets({ silent: true });
  context.timesheetDb.weeks.w1[0].hours.mon = 4;
  const second = context.saveTimesheets({ silent: true });
  context.timesheetDb.weeks.w1[0].hours.mon = 8;
  const third = context.saveTimesheets({ silent: true });
  releaseFirst();
  await Promise.all([first, second, third]);
  assert.equal(maxConcurrent, 1);
  assert.equal(savedPayloads.length, 2);
  assert.equal(savedPayloads[1].weeks.w1[0].hours.mon, 8);

  // Debounced saves collapse rapid edits into a single flush.
  savedPayloads.length = 0;
  context.timesheetDb.weeks.w1[0].hours.mon = 2;
  context.debouncedSaveTimesheets(30);
  context.timesheetDb.weeks.w1[0].hours.mon = 6;
  context.debouncedSaveTimesheets(30);
  await context.flushPendingTimesheetSave();
  assert.equal(savedPayloads.length, 1);
  assert.equal(savedPayloads[0].weeks.w1[0].hours.mon, 6);

  // Unreadable data load pauses subsequent saves.
  savedPayloads.length = 0;
  await context.loadTimesheets();
  const ok = await context.saveTimesheets({ silent: true });
  assert.equal(ok, false);
  assert.equal(savedPayloads.length, 0);
});

test('Partial Print dock entry, Freeze/Thaw settings inputs, and updated Help copy are wired without sortable list headers', () => {
  assert.doesNotMatch(htmlSource, /data-sort=/);
  assert.match(htmlSource, /id="settings_manageLayers_freezePatterns"/);
  assert.match(htmlSource, /id="settings_manageLayers_thawPatterns"/);
  assert.doesNotMatch(htmlSource, /The pencil icon in the app header/);
  assert.doesNotMatch(htmlSource, /The theme control in the header/);
  assert.doesNotMatch(htmlSource, /refresh control beside the version in the header/);
  assert.match(dockSource, /key:\s*"tool:toolPublishPartial"/);
  assert.match(dockSource, /publishMode:\s*"partial"/);
  assert.match(scriptSource, /const partialPrint = launchContext\?\.publishMode === "partial"/);
  assert.match(scriptSource, /askPublishExcelRefresh\(launchContext, \{ requireSelection: partialPrint \}\)/);
});

test('toast supports interactive action buttons (Undo) and invokes onAction once', async () => {
  const appended = [];
  const removed = [];
  let actionCount = 0;
  const doc = {
    body: {
      dataset: { activeTab: 'projects' },
      append(node) { appended.push(node); },
    },
    querySelector: () => null,
  };
  const context = vm.createContext({
    document: doc,
    setTimeout: () => 0,
    clearTimeout() {},
    el: (tag, props) => ({
      tag,
      children: [],
      ...props,
      append(...nodes) { this.children.push(...nodes); },
      remove() { removed.push(this); },
    }),
  });
  vm.runInContext(extract('toast'), context);

  context.toast('Deleted deliverable.', { actionLabel: 'Undo', onAction: () => { actionCount += 1; } });
  assert.equal(appended.length, 1);
  assert.match(appended[0].style, /pointer-events:\s*auto/);
  const btn = appended[0].children.find((child) => child.className === 'toast-action-btn');
  assert.ok(btn, 'Undo action button should render');
  assert.equal(btn.textContent, 'Undo');
  btn.onclick();
  btn.onclick();
  assert.equal(actionCount, 1);
  assert.equal(removed.length, 1);
});

test('project undo stack restores deliverable state snapshots and enforces limit', async () => {
  const toasts = [];
  const context = vm.createContext({
    toast: (msg) => toasts.push(msg),
    console: { warn() {} },
  });
  vm.runInContext(
    [
      'const PROJECT_UNDO_LIMIT = 25;',
      'const projectUndoStack = [];',
      'let projectUndoInFlight = false;',
      extract('snapshotDeliverableUndoState'),
      extract('restoreDeliverableUndoState'),
      extract('pushProjectUndo'),
      extract('undoLastProjectAction'),
    ].join('\n'),
    context
  );

  const dlv = {
    name: '50% CD',
    due: '12/01/2026',
    status: 'In progress',
    statuses: ['In progress'],
    statusTags: ['in-progress'],
    pinned: false,
    tasks: [{ text: 'Check panels', done: false }],
  };
  const snap = context.snapshotDeliverableUndoState(dlv);
  dlv.name = '90% CD';
  dlv.due = '12/15/2026';
  dlv.status = 'Complete';
  dlv.statuses = ['Complete'];
  dlv.statusTags = ['complete'];
  dlv.pinned = true;
  dlv.tasks[0].done = true;

  context.pushProjectUndo({
    label: 'Set to Complete',
    undo: () => context.restoreDeliverableUndoState(dlv, snap),
  });
  assert.equal(await context.undoLastProjectAction(), true);
  assert.equal(dlv.name, '50% CD');
  assert.equal(dlv.due, '12/01/2026');
  assert.equal(dlv.status, 'In progress');
  assert.equal(dlv.pinned, false);
  assert.equal(dlv.tasks[0].done, false);
  assert.match(toasts[0], /Undid: Set to Complete/);
  assert.equal(await context.undoLastProjectAction(), false);
});

test('parsePromptDate supports relative date offsets (+7d, +1w, +2w, -3d) from a base date', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('parsePromptDate', dockSource), context);

  const base = new Date(2026, 10, 10); // Nov 10, 2026
  const plus1w = context.parsePromptDate('+1w', base);
  assert.equal(plus1w.getFullYear(), 2026);
  assert.equal(plus1w.getMonth(), 10);
  assert.equal(plus1w.getDate(), 17);

  const minus3d = context.parsePromptDate('-3d', base);
  assert.equal(minus3d.getFullYear(), 2026);
  assert.equal(minus3d.getMonth(), 10);
  assert.equal(minus3d.getDate(), 7);

  const plus2w = context.parsePromptDate('+2 weeks', base);
  assert.equal(plus2w.getDate(), 24);
});

test('board scroll preservation, search view restore, calendar Escape/presets, editDlg guard, and dock commands are wired', () => {
  assert.match(scriptSource, /const prevScrollLeft = host\.scrollLeft \|\| 0;/);
  assert.match(scriptSource, /preSearchProjectsViewMode = projectsViewMode;/);
  assert.match(scriptSource, /function getInlineCalendarQuickPresets\(/);
  assert.match(scriptSource, /function closeInlineCalendar\(/);
  assert.match(scriptSource, /function confirmDiscardEditDlgChanges\(/);
  assert.match(dockSource, /key:\s*"set-due-date"/);
  assert.match(dockSource, /key:\s*"rename-deliverable"/);
  assert.match(dockSource, /key:\s*"duplicate-deliverable"/);
});

test('hidden aria-modal overlays and closed-dialog details do not block type-to-command or Ctrl+Z undo', () => {
  const hiddenLightbox = {
    hidden: true,
    closest: () => ({ tagName: 'DIALOG' }),
    getClientRects: () => [],
  };
  const closedDialogDetails = {
    hidden: false,
    closest: (sel) => (sel.includes('dialog:not([open])') ? { tagName: 'DIALOG' } : null),
    getClientRects: () => [],
  };
  const visibleModal = {
    hidden: false,
    closest: () => null,
    getClientRects: () => [{ width: 400, height: 300 }],
  };

  let openDialog = null;
  let overlayNodes = [hiddenLightbox, closedDialogDetails];
  const doc = {
    querySelector: (sel) => (sel === 'dialog[open]' ? openDialog : null),
    querySelectorAll: () => overlayNodes,
  };

  const dockCtx = vm.createContext({ document: doc });
  vm.runInContext(extract('hasVisibleCommandBlockingOverlay', dockSource), dockCtx);
  const scriptCtx = vm.createContext({ document: doc });
  vm.runInContext(extract('hasVisibleModalOverlay', scriptSource), scriptCtx);

  assert.equal(dockCtx.hasVisibleCommandBlockingOverlay(), false);
  assert.equal(scriptCtx.hasVisibleModalOverlay(), false);

  overlayNodes = [hiddenLightbox, visibleModal];
  assert.equal(dockCtx.hasVisibleCommandBlockingOverlay(), true);
  assert.equal(scriptCtx.hasVisibleModalOverlay(), true);

  overlayNodes = [hiddenLightbox];
  openDialog = { open: true };
  assert.equal(dockCtx.hasVisibleCommandBlockingOverlay(), true);
  assert.equal(scriptCtx.hasVisibleModalOverlay(), true);
});

test('toast preserves active focus, prevents mousedown focus steal, and only uses showPopover over open dialogs', () => {
  let focusRestored = 0;
  let popoverCalls = 0;
  let hasOpenDialog = false;
  const activeInput = {
    isConnected: true,
    focus() { focusRestored += 1; doc.activeElement = activeInput; },
  };
  const doc = {
    activeElement: activeInput,
    body: {
      dataset: { activeTab: 'projects' },
      append() {},
    },
    querySelector: (sel) => (sel === 'dialog[open]' && hasOpenDialog ? { open: true } : null),
  };
  const created = [];
  const context = vm.createContext({
    document: doc,
    setTimeout: () => 0,
    clearTimeout() {},
    el: (tag, props) => {
      const node = {
        tag,
        children: [],
        ...props,
        append(...nodes) { this.children.push(...nodes); },
        remove() {},
        showPopover() {
          popoverCalls += 1;
          doc.activeElement = doc.body;
        },
      };
      created.push(node);
      return node;
    },
  });
  vm.runInContext(extract('toast'), context);

  // On Projects with no open modal dialog, toast avoids showPopover and prevents mousedown focus steal.
  context.toast('Updated status.', { actionLabel: 'Undo', onAction: () => {} });
  assert.equal(popoverCalls, 0);
  const toastNode = created[0];
  const undoBtn = toastNode.children.find((c) => c.className === 'toast-action-btn');
  let preventedToast = false;
  let preventedBtn = false;
  toastNode.onmousedown({ preventDefault() { preventedToast = true; } });
  undoBtn.onmousedown({ preventDefault() { preventedBtn = true; } });
  assert.equal(preventedToast, true);
  assert.equal(preventedBtn, true);

  // Over an open modal dialog, toast uses showPopover and restores focus if it shifted.
  hasOpenDialog = true;
  context.toast('Saved inside modal.');
  assert.equal(popoverCalls, 1);
  assert.equal(focusRestored, 1);
  assert.equal(doc.activeElement, activeInput);
});

test('re-clicking the already-selected deliverable focuses the command input when blurred', () => {
  let focusCount = 0;
  const dlv = { id: 'd1', name: '90% CD' };
  const proj = { id: '250001', name: 'Test Project' };
  const input = { focus() { focusCount += 1; } };
  const dock = {
    deliverable: dlv,
    project: proj,
    multi: [],
    anchor: { deliverable: dlv, project: proj },
    pendingKey: null,
    pendingLabel: '',
    items: [],
    input,
  };
  const doc = { activeElement: { tagName: 'BODY' } };
  const context = vm.createContext({
    document: doc,
    ensureCommandDock: () => dock,
    renderCommandDockItems() {},
    updateCommandDockContext() {},
    syncCommandDockSelection() {},
    setCommandDockExpanded() {},
    focusCommandDockGroup() {},
  });
  vm.runInContext(extract('selectDeliverableForCommands', dockSource), context);

  context.selectDeliverableForCommands(dlv, proj);
  assert.equal(focusCount, 1);

  doc.activeElement = input;
  context.selectDeliverableForCommands(dlv, proj);
  assert.equal(focusCount, 1);
});
