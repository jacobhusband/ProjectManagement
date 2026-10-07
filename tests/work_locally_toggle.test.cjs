const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../script.js'), 'utf8');
const dockSource = fs.readFileSync(require('node:path').join(__dirname, '../industry-projects.js'), 'utf8');
function extract(name, from = source) {
  return from.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'))[0];
}
function extractConst(name) {
  return source.match(new RegExp(`^const ${name} =[\\s\\S]*?;\\r?$`, 'm'))[0];
}

const SERVER = 'M:\\Clients\\260243 Sample Clinic';
const LOCAL = 'C:\\Users\\Me\\Documents\\Local Projects\\260243 Sample Clinic';

function loadContext(extra = {}) {
  const toasts = [];
  const context = vm.createContext({
    toast: (message, duration) => toasts.push({ message, duration }),
    getActiveDiscipline: () => 'Electrical',
    getSharedToolLaunchEntry: (id) => ({ id, isReady: true }),
    save: async () => { context.saveCount += 1; },
    saveCount: 0,
    toasts,
    ...extra,
  });
  vm.runInContext(
    [
      extractConst('PROJECT_ROOT_SEGMENT_REGEX'),
      extractConst('WORK_LOCALLY_MISSING_COPY_MESSAGE'),
      ...[
        'convertPath', 'normalizeWindowsPath', 'getWindowsPathLeaf', 'getWindowsPathParent',
        'findProjectRootPath', 'normalizeProjectPath', 'isProjectWorkLocally',
        'getProjectLocalFolderPath', 'getProjectActionFolderPath',
        'buildProjectsTabToolLaunchContext', 'getServerLaunchContext',
        'getLaunchContextProjectRoot', 'hasLaunchContextProjectPath', 'launchSharedToolCard',
        'buildDeliverablePdfLookupProject', 'resolveProjectLocalFolder', 'setProjectWorkLocally',
      ].map((name) => extract(name)),
      ...[
        'buildCommandDockGroups', 'updateCommandDockContext', 'toggleCommandDockWorkLocally',
      ].map((name) => extract(name, dockSource)),
    ].join('\n'),
    context
  );
  return context;
}

function classList() {
  const names = new Set();
  return {
    add: (...list) => list.forEach((name) => names.add(name)),
    remove: (...list) => list.forEach((name) => names.delete(name)),
    toggle: (name, force) => {
      if (force === undefined ? !names.has(name) : force) names.add(name);
      else names.delete(name);
    },
    contains: (name) => names.has(name),
  };
}

function makeDock(overrides = {}) {
  return {
    project: null,
    deliverable: null,
    pendingKey: null,
    items: [],
    root: { classList: classList() },
    context: { classList: classList(), textContent: '', title: '' },
    scope: { textContent: '' },
    input: { placeholder: '' },
    pending: { textContent: '', hidden: true },
    workLocally: { classList: classList(), title: '' },
    workLocallyInput: { checked: false, disabled: true },
    ...overrides,
  };
}

const project = (overrides = {}) => ({
  id: '260243', name: 'Sample Clinic', path: SERVER, localProjectPath: LOCAL, ...overrides,
});

test('tool launch context points at the server folder until Work locally is on', () => {
  const context = loadContext();
  const server = context.buildProjectsTabToolLaunchContext(project(), { name: 'CD' });
  assert.equal(server.projectPath, SERVER);
  assert.equal(server.rootProjectPath, SERVER);
  assert.equal(server.workLocally, false);

  const local = context.buildProjectsTabToolLaunchContext(project({ workLocally: true }), { name: 'CD' });
  assert.equal(local.projectPath, LOCAL);
  assert.equal(local.rootProjectPath, LOCAL);
  assert.equal(local.serverProjectPath, SERVER);
  assert.equal(local.workLocally, true);
  assert.equal(local.projectId, '260243');
});

test('Work Locally copy tool always starts from the server path', () => {
  const context = loadContext();
  const local = context.buildProjectsTabToolLaunchContext(project({ workLocally: true }), {});
  const forCopy = context.getServerLaunchContext(local);
  assert.equal(forCopy.projectPath, SERVER);
  assert.equal(forCopy.rootProjectPath, SERVER);
  assert.equal(forCopy.workLocally, false);

  const server = context.buildProjectsTabToolLaunchContext(project(), {});
  assert.equal(context.getServerLaunchContext(server), server);
  assert.equal(context.getServerLaunchContext(null), null);
});

test('a tool cannot launch on a missing local copy, but the copy tool still can', () => {
  const context = loadContext();
  const noCopy = project({ workLocally: true, localProjectPath: '' });
  const launchContext = context.buildProjectsTabToolLaunchContext(noCopy, {});
  assert.equal(launchContext.projectPath, '');

  // Would fall through to card.click() on a DOM this test does not have.
  assert.equal(context.launchSharedToolCard('toolPublishDwgs', launchContext), false);
  assert.equal(context.toasts.length, 1);
  assert.match(context.toasts[0].message, /no local copy/i);

  context.runLocalProjectManager = () => Promise.resolve();
  assert.equal(context.launchSharedToolCard('toolCopyProjectLocally', launchContext), true);
});

test('quick access searches only the local copy while Work locally is on', () => {
  const context = loadContext();
  const server = context.buildDeliverablePdfLookupProject(project());
  assert.equal(server.path, SERVER);
  assert.equal(server.localProjectPath, LOCAL);

  const local = context.buildDeliverablePdfLookupProject(project({ workLocally: true }));
  assert.equal(local.path, LOCAL);
  assert.equal(local.localProjectPath, LOCAL);
  assert.equal(local.id, '260243');

  const missing = context.buildDeliverablePdfLookupProject(
    project({ workLocally: true, localProjectPath: '' })
  );
  assert.equal(missing.path, '');
  assert.equal(missing.localProjectPath, '');
});

test('turning Work locally on uses the recorded copy and saves', async () => {
  const context = loadContext();
  const target = project();
  assert.equal(await context.setProjectWorkLocally(target, true), true);
  assert.equal(target.workLocally, true);
  assert.equal(target.localProjectPath, LOCAL);
  assert.equal(context.saveCount, 1);

  assert.equal(await context.setProjectWorkLocally(target, false), true);
  assert.equal(target.workLocally, false);
  assert.equal(context.saveCount, 2);
});

test('turning Work locally on adopts an unrecorded copy, and refuses when there is none', async () => {
  const lookups = [];
  const context = loadContext({
    window: {
      pywebview: {
        api: {
          get_local_project_copy_info: async (serverPath) => {
            lookups.push(serverPath);
            return { status: 'success', path: LOCAL, exists: true };
          },
        },
      },
    },
  });
  const unrecorded = project({ localProjectPath: '' });
  assert.equal(await context.setProjectWorkLocally(unrecorded, true), true);
  assert.equal(unrecorded.localProjectPath, LOCAL);
  assert.equal(unrecorded.workLocally, true);
  assert.deepEqual(lookups, [SERVER]);

  const refusing = loadContext({
    window: {
      pywebview: {
        api: {
          get_local_project_copy_info: async () => ({ status: 'success', path: LOCAL, exists: false }),
        },
      },
    },
  });
  const uncopied = project({ localProjectPath: '' });
  assert.equal(await refusing.setProjectWorkLocally(uncopied, true), false);
  assert.ok(!uncopied.workLocally);
  assert.equal(uncopied.localProjectPath, '');
  assert.equal(refusing.saveCount, 0);

  const offline = loadContext({ window: {} });
  assert.equal(await offline.setProjectWorkLocally(project({ localProjectPath: '' }), true), false);
});

test('the flag survives normalizeProject and the project edit modal', () => {
  assert.match(source, /workLocally: project\.workLocally === true,/);
  assert.match(source, /workLocally: existingProject\?\.workLocally === true,/);
  assert.match(source, /localProjectPath: "",\r?\n\s+workLocally: false,/);
});

// ---- Command dock: the project action bar ----------------------------------

function loadDockContext(dock, extra = {}) {
  const calls = [];
  const context = loadContext({
    calls,
    INDUSTRY_STATUS_OPTIONS: [],
    hasStatus: () => false,
    isDeliverablePinned: () => false,
    getDeliverableToolMenuEntries: () => [],
    getCommandHotkeyEntries: () => [],
    DELIVERABLE_QUICK_ACCESS_ACTIONS: [],
    getDeliverableQuickAccessActionLabel: () => '',
    buildCommandDockTargetGroup: () => null,
    getProjectShortName: (project) => project?.name || '',
    ensureCommandDock: () => dock,
    openProjectDirectory: async (target, kind) => { calls.push(['openProjectDirectory', kind, target.id]); },
    window: {
      pywebview: {
        api: { open_path: async (path) => { calls.push(['open_path', path]); return { status: 'success' }; } },
      },
    },
    ...extra,
  });
  return context;
}

function folderCommand(context, project) {
  const groups = context.buildCommandDockGroups(null, project);
  return groups.find((group) => group.key === 'project').items.find((item) => item.key === 'folder');
}

test('dock folder command opens the server folder until Work locally is on, then the local copy', async () => {
  const context = loadDockContext(makeDock());
  const server = folderCommand(context, project());
  assert.equal(server.label, 'Open project folder');
  assert.equal(server.hidden, false);
  await server.run({ project: project() });
  assert.deepEqual(Array.from(context.calls, (call) => call[0]), ['open_path']);
  assert.equal(context.calls[0][1], SERVER);

  context.calls.length = 0;
  const local = folderCommand(context, project({ workLocally: true }));
  assert.equal(local.label, 'Open local project folder');
  assert.equal(local.hidden, false);
  await local.run({ project: project({ workLocally: true }) });
  assert.deepEqual(Array.from(context.calls, (call) => call.slice(0, 2)), [['openProjectDirectory', 'local']]);
});

test('dock folder command hides when the current mode has no folder to open', () => {
  const context = loadDockContext(makeDock());
  assert.equal(folderCommand(context, project({ path: '', localProjectPath: '' })).hidden, true);
  // Work locally with no local copy: the server folder is not a stand-in.
  assert.equal(folderCommand(context, project({ workLocally: true, localProjectPath: '' })).hidden, true);
  // No project selected yet: the command must stay listed so it can be picked first.
  assert.equal(folderCommand(context, null).hidden, false);
});

test('dock checkbox follows the selected project and is disabled without one', () => {
  const dock = makeDock();
  const context = loadDockContext(dock);

  context.updateCommandDockContext();
  assert.equal(dock.workLocallyInput.disabled, true);
  assert.equal(dock.workLocallyInput.checked, false);
  assert.match(dock.workLocally.title, /select a project/i);

  dock.project = project();
  context.updateCommandDockContext();
  assert.equal(dock.workLocallyInput.disabled, false);
  assert.equal(dock.workLocallyInput.checked, false);
  assert.equal(dock.workLocally.classList.contains('is-checked'), false);
  assert.doesNotMatch(dock.scope.textContent, /local copy/);

  dock.project = project({ workLocally: true });
  context.updateCommandDockContext();
  assert.equal(dock.workLocallyInput.checked, true);
  assert.equal(dock.workLocally.classList.contains('is-checked'), true);
  assert.match(dock.scope.textContent, /working on the local copy/);

  dock.deliverable = { name: 'CD' };
  context.updateCommandDockContext();
  assert.match(dock.scope.textContent, /Acts on 1 deliverable · working on the local copy/);
});

test('dock checkbox saves the change, and springs back with a hint when there is no local copy', async () => {
  const dock = makeDock({ project: project() });
  const context = loadDockContext(dock, {
    renderCommandDockItems: () => context.calls.push(['render']),
  });

  await context.toggleCommandDockWorkLocally(true);
  assert.equal(dock.project.workLocally, true);
  assert.equal(context.saveCount, 1);
  assert.equal(context.toasts.length, 0);
  assert.equal(dock.workLocallyInput.checked, true);
  assert.equal(dock.workLocallyInput.disabled, false);
  assert.ok(context.calls.some((call) => call[0] === 'render'));

  await context.toggleCommandDockWorkLocally(false);
  assert.equal(dock.project.workLocally, false);
  assert.equal(dock.workLocallyInput.checked, false);

  dock.project = project({ localProjectPath: '' });
  dock.workLocallyInput.checked = true; // what the browser does on click, before the handler runs
  await context.toggleCommandDockWorkLocally(true);
  assert.ok(!dock.project.workLocally);
  assert.equal(dock.workLocallyInput.checked, false);
  assert.equal(context.toasts.length, 1);
  assert.match(context.toasts[0].message, /no local copy/i);
  assert.equal(context.saveCount, 2);

  dock.project = null;
  await context.toggleCommandDockWorkLocally(true);
  assert.equal(context.toasts.length, 1);
});

test('the checkbox is part of the dock bar and styled for both themes of the dock', () => {
  const css = fs.readFileSync(require('node:path').join(__dirname, '../industry.css'), 'utf8');
  const modern = fs.readFileSync(require('node:path').join(__dirname, '../modern-workspace.css'), 'utf8');
  assert.match(dockSource, /bar\.append\(context, input, pending, workLocally, hint, expand\);/);
  assert.match(dockSource, /workLocallyInput\.addEventListener\("change"/);
  assert.match(css, /\.cmd-work-locally \{/);
  assert.match(css, /\.cmd-work-locally\.is-checked \{/);
  assert.match(css, /\.cmd-work-locally\.is-disabled \{/);
  assert.match(modern, /\.cmd-work-locally/);
});
