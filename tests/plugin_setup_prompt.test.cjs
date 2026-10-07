const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// The prompt is one self-contained block of script.js; run that exact block.
const source = fs.readFileSync(path.join(__dirname, '../script.js'), 'utf8');
const start = source.indexOf('// ===================== AUTOCAD PLUGIN SETUP PROMPT');
const end = source.indexOf('// =====================', start + 10);
assert.ok(start > 0 && end > start, 'plugin setup block not found in script.js');
const promptBlock = source.slice(start, end);
const normalizeName = source.match(/^function normalizeBundleCoreName\([\s\S]*?^}\r?$/m)[0];

const asset = (name) => ({ name: `ElectricalCommands.${name}-v0.2.1.zip`, browser_download_url: `https://example/${name}.zip` });
const bundle = (name, state = 'not_installed', withAsset = true) => ({
  name: `ElectricalCommands.${name}`,
  bundle_name: `ElectricalCommands.${name}.bundle`,
  state,
  asset: withAsset ? asset(name) : undefined,
});
const FRESH = () => [bundle('CleanCADCommands'), bundle('PlotCommands'), bundle('T24Commands')];

function makeEnv(overrides = {}) {
  const dom = {};
  const el = (id) => (dom[id] ||= { id, style: {}, textContent: '', disabled: false });
  const log = { activities: [], installs: [], toasts: [], saves: 0, rendered: 0, discoveries: 0 };
  const env = {
    userSettings: { showPluginSetupPrompt: true, autocadPath: '' },
    document: { getElementById: el },
    console,
    toast: (m) => log.toasts.push(m),
    createActivityId: (p) => `${p}_1`,
    beginActivity: (a) => { log.activities.push({ ...a, status: 'running' }); return a.activityId; },
    updateActivity: (id, p) => { Object.assign(log.activities[0], p); },
    completeActivity: (id, p) => { Object.assign(log.activities[0], p, { status: 'success' }); },
    failActivity: (id, p) => { Object.assign(log.activities[0], p, { status: 'error' }); },
    persistUserSettingsLocally: async () => { log.saves += 1; return true; },
    ensureBundlesRendered: async () => { log.rendered += 1; },
    fetchBundleStatuses: async () => FRESH(),
    window: {},
    ...overrides,
  };
  env.window.pywebview = {
    api: {
      get_installed_autocad_versions: async () => { log.discoveries += 1; return { status: 'success', versions: [{ year: 2025, path: 'x' }] }; },
      install_single_bundle: async (a) => { log.installs.push(a.name); return { status: 'success', pluginsFolderPath: 'C:\\Plugins' }; },
      ...(overrides.api || {}),
    },
  };
  const context = vm.createContext(env);
  vm.runInContext(normalizeName + '\n' + promptBlock, context);
  const read = (name) => vm.runInContext(name, context);
  return { context, dom, el, log, read };
}

// ---------------------------------------------------------------- who is offered the plugins

test('offers the plugins when AutoCAD is present and no ACIES plugin is installed', () => {
  const { context } = makeEnv();
  const plan = context.getPluginSetupPromptPlan({ bundles: FRESH(), autocadInstalled: true, settings: { showPluginSetupPrompt: true } });
  assert.equal(plan.show, true);
  assert.deepEqual(plan.installable.map((b) => b.name), FRESH().map((b) => b.name));
});

test('stays quiet without AutoCAD, when asked not to ask, or when any ACIES plugin is already there', () => {
  const { context } = makeEnv();
  const plan = (over) => context.getPluginSetupPromptPlan({ bundles: FRESH(), autocadInstalled: true, settings: {}, ...over });
  assert.equal(plan({ autocadInstalled: false }).show, false);
  assert.equal(plan({ settings: { showPluginSetupPrompt: false } }).show, false);
  assert.equal(plan({ bundles: [bundle('CleanCADCommands', 'installed'), bundle('PlotCommands')] }).show, false);
  assert.equal(plan({ bundles: [bundle('CleanCADCommands', 'update_available'), bundle('PlotCommands')] }).show, false);
  assert.equal(plan({ bundles: undefined }).show, false);
});

test("another vendor's installed bundle does not count as an ACIES plugin", () => {
  const { context } = makeEnv();
  const other = { name: 'Vendor.Tools', bundle_name: 'Vendor.Tools.bundle', state: 'installed' };
  const plan = context.getPluginSetupPromptPlan({ bundles: [other, ...FRESH()], autocadInstalled: true, settings: {} });
  assert.equal(plan.show, true);
  assert.equal(plan.installable.length, 3);
});

test('offers nothing that cannot be downloaded (GitHub unreachable leaves no asset)', () => {
  const { context } = makeEnv();
  const bundles = [bundle('CleanCADCommands', 'not_installed', false), bundle('PlotCommands', 'not_published', false)];
  assert.equal(context.getPluginSetupPromptPlan({ bundles, autocadInstalled: true, settings: {} }).show, false);
  const mixed = [bundle('CleanCADCommands', 'not_installed', false), bundle('PlotCommands')];
  assert.deepEqual(
    context.getPluginSetupPromptPlan({ bundles: mixed, autocadInstalled: true, settings: {} }).installable.map((b) => b.name),
    ['ElectricalCommands.PlotCommands']
  );
});

// ---------------------------------------------------------------- showing the banner

test('shows the banner with the plugin count when the plan says so', async () => {
  const { context, el, log } = makeEnv();
  await context.maybeShowPluginSetupBanner();
  assert.equal(el('pluginSetupBanner').style.display, 'block');
  assert.equal(el('pluginSetupInstallBtn').textContent, 'Install 3 plugins');
  assert.match(el('pluginSetupBannerText').textContent, /all 3/);
  assert.equal(log.discoveries, 1);
});

test('a plugin count of one reads naturally', async () => {
  const { context, el } = makeEnv({ fetchBundleStatuses: async () => [bundle('CleanCADCommands')] });
  await context.maybeShowPluginSetupBanner();
  assert.equal(el('pluginSetupInstallBtn').textContent, 'Install plugin');
  assert.match(el('pluginSetupBannerText').textContent, /Installing it/);
});

test('a chosen AutoCAD path counts as AutoCAD being present without asking the registry', async () => {
  const { context, el, log } = makeEnv({ userSettings: { showPluginSetupPrompt: true, autocadPath: 'C:\\AutoCAD\\accoreconsole.exe' } });
  await context.maybeShowPluginSetupBanner();
  assert.equal(el('pluginSetupBanner').style.display, 'block');
  assert.equal(log.discoveries, 0);
});

test('no banner when the plugin list could not be loaded, or AutoCAD is not installed', async () => {
  const failed = makeEnv({ fetchBundleStatuses: async () => null });
  await failed.context.maybeShowPluginSetupBanner();
  assert.equal(failed.el('pluginSetupBanner').style.display, undefined);

  const noAcad = makeEnv({ api: { get_installed_autocad_versions: async () => ({ status: 'success', versions: [] }) } });
  await noAcad.context.maybeShowPluginSetupBanner();
  assert.equal(noAcad.el('pluginSetupBanner').style.display, undefined);
});

test('two triggers at once (launch and end of onboarding) look only once', async () => {
  const { context, log } = makeEnv();
  await Promise.all([context.maybeShowPluginSetupBanner(), context.maybeShowPluginSetupBanner()]);
  assert.equal(log.discoveries, 1);
});

// ---------------------------------------------------------------- installing

test('installs every offered plugin in one tracked activity and refreshes the Tools tab', async () => {
  const { context, el, log, read } = makeEnv();
  await context.maybeShowPluginSetupBanner();
  await context.installFirstRunPlugins();

  assert.deepEqual(log.installs, FRESH().map((b) => b.asset.name));
  assert.equal(log.activities.length, 1);
  const activity = log.activities[0];
  assert.equal(activity.status, 'success');
  assert.match(activity.message, /Installed 3 plugins\. They load the next time AutoCAD starts\./);
  assert.equal(activity.openFolderPath, 'C:\\Plugins');
  assert.equal(el('pluginSetupBanner').style.display, 'none');
  assert.equal(log.rendered, 1);
  assert.equal(read('pluginSetupPromptHandled'), true);
  assert.equal(read('pluginSetupInstalling'), false);
});

test('stops at the first plugin when AutoCAD is open and keeps the offer for another try', async () => {
  const env = makeEnv();
  const attempts = [];
  env.context.window.pywebview.api.install_single_bundle = async (a) => {
    attempts.push(a.name);
    return { status: 'error', code: 'autocad_running', message: 'AutoCAD is currently running. Close it.' };
  };
  await env.context.maybeShowPluginSetupBanner();
  await env.context.installFirstRunPlugins();

  assert.equal(attempts.length, 1, 'remaining plugins are not attempted');
  const activity = env.log.activities[0];
  assert.equal(activity.status, 'error');
  assert.match(activity.message, /AutoCAD is currently running/);
  assert.equal(env.el('pluginSetupBanner').style.display, 'block');
  assert.equal(env.el('pluginSetupInstallBtn').disabled, false);
  assert.equal(env.el('pluginSetupInstallBtn').textContent, 'Install 3 plugins');
  assert.equal(env.read('pluginSetupPromptHandled'), false);
  assert.equal(env.log.rendered, 0);
});

test('one failing plugin does not stop the others and is reported', async () => {
  const env = makeEnv();
  const tried = [];
  env.context.window.pywebview.api.install_single_bundle = async (a) => {
    tried.push(a.name);
    return a.name.includes('PlotCommands')
      ? { status: 'error', message: 'Download failed.' }
      : { status: 'success', pluginsFolderPath: 'C:\\Plugins' };
  };
  await env.context.maybeShowPluginSetupBanner();
  await env.context.installFirstRunPlugins();

  assert.equal(tried.length, 3);
  const activity = env.log.activities[0];
  assert.equal(activity.status, 'success');
  assert.match(activity.message, /Installed 2 plugins/);
  assert.match(activity.message, /1 plugin failed: PlotCommands: Download failed\./);
  assert.equal(env.el('pluginSetupBanner').style.display, 'none');
});

test('when nothing installs the activity fails and the banner stays', async () => {
  const env = makeEnv();
  env.context.window.pywebview.api.install_single_bundle = async () => ({ status: 'error', message: 'Download failed.' });
  await env.context.maybeShowPluginSetupBanner();
  await env.context.installFirstRunPlugins();

  assert.equal(env.log.activities[0].status, 'error');
  assert.match(env.log.activities[0].message, /Download failed\./);
  assert.equal(env.el('pluginSetupBanner').style.display, 'block');
  assert.equal(env.log.rendered, 0);
});

test('a thrown bridge error is reported like any other failure', async () => {
  const env = makeEnv({ fetchBundleStatuses: async () => [bundle('CleanCADCommands')] });
  env.context.window.pywebview.api.install_single_bundle = async () => { throw new Error('bridge down'); };
  await env.context.maybeShowPluginSetupBanner();
  await env.context.installFirstRunPlugins();
  assert.match(env.log.activities[0].message, /bridge down/);
});

test('a second click while installing does nothing', async () => {
  const env = makeEnv();
  let release;
  const gate = new Promise((r) => { release = r; });
  env.context.window.pywebview.api.install_single_bundle = async (a) => { env.log.installs.push(a.name); await gate; return { status: 'success' }; };
  await env.context.maybeShowPluginSetupBanner();
  const first = env.context.installFirstRunPlugins();
  const second = env.context.installFirstRunPlugins();
  release();
  await Promise.all([first, second]);
  assert.equal(env.log.activities.length, 1);
  assert.equal(env.log.installs.length, 3);
});

// ---------------------------------------------------------------- dismissing

test('"Not right now" hides the banner and saves nothing, so it returns next launch', async () => {
  const env = makeEnv();
  await env.context.maybeShowPluginSetupBanner();
  await env.context.dismissPluginSetup('later');
  assert.equal(env.el('pluginSetupBanner').style.display, 'none');
  assert.equal(env.log.saves, 0);
  assert.equal(env.context.userSettings.showPluginSetupPrompt, true);
  await env.context.maybeShowPluginSetupBanner();
  assert.equal(env.el('pluginSetupBanner').style.display, 'none', 'not shown again in the same session');
});

test('"Do not ask again" is saved and the prompt never returns', async () => {
  const env = makeEnv();
  await env.context.maybeShowPluginSetupBanner();
  await env.context.dismissPluginSetup('never');
  assert.equal(env.el('pluginSetupBanner').style.display, 'none');
  assert.equal(env.context.userSettings.showPluginSetupPrompt, false);
  assert.equal(env.log.saves, 1);
  assert.match(env.log.toasts[0], /Tools tab/);

  const later = makeEnv({ userSettings: { showPluginSetupPrompt: false, autocadPath: '' } });
  await later.context.maybeShowPluginSetupBanner();
  assert.equal(later.el('pluginSetupBanner').style.display, undefined);
});

test('the declared click actions and settings default exist', () => {
  for (const name of ['installFirstRunPlugins', 'dismissPluginSetupLater', 'dismissPluginSetupNever']) {
    assert.ok(source.includes(`${name}: () =>`), `${name} is registered as a click action`);
  }
  const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
  for (const name of ['installFirstRunPlugins', 'dismissPluginSetupLater', 'dismissPluginSetupNever']) {
    assert.ok(html.includes(`data-click-action="${name}"`), `${name} is wired in index.html`);
  }
  assert.ok(/showPluginSetupPrompt: true,/.test(source));
});
