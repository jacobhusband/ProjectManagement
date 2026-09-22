const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');

function extract(name) {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\r?$`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0];
}

for (const [name, endpoint, state] of [
  ['save', 'save_tasks', 'db'],
  ['persistUserSettingsLocally', 'save_user_settings', 'userSettings'],
  ['saveGlobalPages', 'save_notes', 'pages'],
  ['saveTimesheets', 'save_timesheets', 'timesheetDb'],
  ['saveTemplates', 'save_templates', 'templatesDb'],
  ['saveChecklists', 'save_checklists', 'checklistsDb'],
]) {
  test(`${name} persists locally without a cloud runtime`, async () => {
    let saved;
    const context = vm.createContext({
      window: { pywebview: { api: { [endpoint]: async payload => {
        saved = payload;
        return { status: 'success' };
      } } } },
      db: [{ id: 'project', deliverables: [] }],
      userSettings: { userName: 'Reviewer' },
      pages: { version: 2, pages: [], scratchpad: 'keep me' },
      timesheetDb: { weeks: {}, expenses: { week: { projects: ['expense'] } } },
      templatesDb: { templates: ['template'] },
      checklistsDb: { checklists: ['checklist'] },
      syncPinnedProjectOrders() {},
      syncProjectAttachmentFields() {},
      getProjectDeliverables: project => project.deliverables,
      console: { warn() {} },
      toast() {},
      projectDataLoadError: '',
      projectSaveInFlight: null,
      projectSaveFollowUp: null,
    });
    context.buildGlobalPagesData = () => context.pages;
    const helpers = name === 'save' ? `${extract('queueProjectSave')}\n` : '';
    vm.runInContext(`${extract('normalizeIsoTimestamp')}\n${helpers}${extract(name)}`, context);
    assert.equal(await context[name](), true);
    assert.equal(saved, context[state]);
    if (['timesheetDb', 'templatesDb', 'checklistsDb'].includes(state)) {
      assert.ok(saved.lastModified);
    }
    context.window.pywebview.api[endpoint] = async () => ({ status: 'error', message: 'disk unavailable' });
    assert.equal(await context[name]({ silent: true }), false);
  });
}
