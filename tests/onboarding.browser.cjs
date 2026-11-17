// Run with Playwright on NODE_PATH and PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH if needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const extract = name => {
  const match = source.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, name);
  return match[0];
};
const block = source.slice(source.indexOf('let currentOnboardingStep = 1;'), source.indexOf('function showAppLoader()'));
const pluginStart = source.indexOf('// ===================== AUTOCAD PLUGIN SETUP PROMPT');
const pluginBlock = source.slice(pluginStart, source.indexOf('// =====================', pluginStart + 10));

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined });
  try {
    const context = await browser.newContext({ bypassCSP: true });
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    async function boot(settings = {}) {
      await page.goto('about:blank');
      await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ''));
      await page.addStyleTag({ content: fs.readFileSync(path.join(root, 'styles.css'), 'utf8') });
      await page.addScriptTag({ content: `
        let userSettings = { userName: '', discipline: ['Electrical'], activeDiscipline: 'Electrical',
          apiKey: '', onboardingComplete: false, showSetupHelp: true, ...${JSON.stringify(settings)} };
        let db = [], globalPages = [], timesheetDb = { weeks: {} }, checklistsDb = { checklists: [] },
          projectDataLoadError = '', currentTimesheetWeek = new Date();
        let saves = [], keyTests = [], renders = [], toasts = [], failSave = false, deferSave = false, releaseSave;
        const toast = message => toasts.push(message);
        const val = id => document.getElementById(id).value;
        let pluginBundles = [{ bundle_name: 'ElectricalCommands.bundle', state: 'not_installed', asset: { name: 'ACIES.zip' } }],
          autocadVersions = [{ year: 2026 }], failPluginList = false, installFailure = null, installs = [],
          deferInstall = false, releaseInstall, commandDialogs = 0;
        const fetchBundleStatuses = async () => failPluginList ? null : pluginBundles;
        const createActivityId = () => 'plugin-test';
        const beginActivity = () => 'plugin-test', updateActivity = () => {}, completeActivity = () => {}, failActivity = () => {};
        const ensureBundlesRendered = async () => {};
        const openPluginCommandsDialog = async () => { commandDialogs++; };
        const refreshActiveDisciplineDependentUi = () => renders.push('discipline');
        const renderGlobalPagesView = () => renders.push('pages');
        const renderChecklistTabs = () => renders.push('checklistTabs');
        const renderChecklistsView = () => renders.push('checklists');
        const renderTemplates = () => renders.push('templates');
        const renderTimesheets = () => renders.push('timesheets');
        const render = () => { renders.push('projects'); document.getElementById('emptyState').style.display = 'block'; };
        const updateTimesheetsDuplicateIndicator = () => renders.push('timesheetIndicator');
        const getWeekEntries = () => [], formatWeekKey = () => '';
        window.pywebview = { api: {
          get_installed_autocad_versions: async () => ({ status: 'success', versions: autocadVersions }),
          install_single_bundle: async asset => {
            installs.push(asset.name);
            if (deferInstall) await new Promise(resolve => releaseInstall = resolve);
            if (installFailure) return installFailure;
            pluginBundles.find(bundle => bundle.asset?.name === asset.name).state = 'installed';
            return { status: 'success' };
          },
          save_user_settings: async settings => {
            saves.push(JSON.parse(JSON.stringify(settings)));
            if (deferSave) await new Promise(resolve => releaseSave = resolve);
            return { status: failSave ? 'error' : 'success' };
          },
          validate_google_ai_api_key: async key => {
            keyTests.push(key);
            if (key === 'offline') throw new Error('offline');
            return key === 'valid-test-key' ? { status: 'success' } : { status: 'error', message: 'Google rejected this key.' };
          }
        } };
        ${['normalizeDisciplineList', 'normalizeConfiguredDisciplineList', 'closeDlg', 'persistUserSettingsLocally', 'hideSetupHelpBanner',
          'startSetupHelp', 'getDeclarativeClickAction', 'handleDeclarativeClick', 'normalizeBundleCoreName'].map(extract).join('\n')}
        const normalizeWorkroomCadDiscipline = (value, fallback) => ['Electrical', 'Mechanical', 'Plumbing'].includes(value) ? value : fallback;
        ${block}
        ${pluginBlock}
        document.addEventListener('click', handleDeclarativeClick, true);
        hideMainApp(); showOnboardingModal();
      ` });
      assert.deepEqual(errors, [], 'onboarding boot has no script errors');
    }
    const next = () => page.locator('#onboardingNextBtn').click();
    const skip = () => page.locator('#onboardingDlg [data-click-action="skipOnboarding"]');
    async function toPlugins(discipline = 'Mechanical') {
      await next();
      await page.locator('#onboarding_userName').fill('Test Engineer');
      await next();
      await page.locator('input[name="onboarding_discipline_checkbox"][value="Electrical"]').uncheck();
      await page.locator(`input[name="onboarding_discipline_checkbox"][value="${discipline}"]`).check();
      await next();
      assert.equal(await page.locator('#onboardingStep4').isVisible(), true);
      assert.match(await page.locator('#onboardingStep4').textContent(), /Recommended for AutoCAD users/);
      assert.match(await page.locator('#onboardingStep4').textContent(), /Tools → AutoCAD Plugins/);
    }
    async function toAi(discipline = 'Mechanical') {
      await toPlugins(discipline);
      await next();
    }

    await boot();
    await next();
    await page.locator('#onboarding_userName').fill('Partial Profile');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    assert.deepEqual(await page.evaluate(() => ({ name: saves[0].userName, done: saves[0].onboardingComplete,
      help: saves[0].showSetupHelp, newUser: isNewUser(), visible: document.querySelector('main').style.display })),
    { name: 'Partial Profile', done: true, help: false, newUser: false, visible: 'block' });
    assert.ok(await page.evaluate(() => renders.includes('projects') && renders.includes('templates')));
    console.log('PASS: Escape saves partial progress and initializes the app.');

    await boot();
    await skip().focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    assert.equal(await page.evaluate(() => saves.length), 1);
    assert.equal(await page.evaluate(() => isNewUser()), false);
    console.log('PASS: keyboard Skip saves a durable first-run choice even without a name.');

    await boot();
    await next();
    await next();
    assert.equal(await page.evaluate(() => currentOnboardingStep), 2, 'blank name stays on profile step');
    await page.locator('#onboarding_userName').fill('Test Engineer');
    await next();
    await page.locator('#onboardingPrevBtn').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => currentOnboardingStep), 2);
    await page.locator('#onboarding_userName').press('Enter');
    assert.equal(await page.evaluate(() => currentOnboardingStep), 3);
    console.log('PASS: Enter respects Previous and still advances from text fields.');

    await boot();
    await toAi();
    await next();
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    const saved = await page.evaluate(() => saves[0]);
    assert.deepEqual(saved.discipline, ['Mechanical']);
    assert.equal(saved.activeDiscipline, 'Mechanical');
    assert.equal(saved.apiKey, '');
    assert.equal(saved.showSetupHelp, false);
    assert.equal(await page.evaluate(() => keyTests.length), 0);
    await boot(saved);
    assert.equal(await page.locator('#onboarding_userName').inputValue(), 'Test Engineer');
    assert.equal(await page.locator('input[value="Mechanical"][name="onboarding_discipline_checkbox"]').isChecked(), true);
    assert.equal(await page.evaluate(() => isNewUser()), false);
    console.log('PASS: optional AI, Mechanical work context, saved preferences, and returning-user prefill.');

    await boot({ userName: 'Existing User', apiKey: 'saved-key', discipline: ['Plumbing'], activeDiscipline: 'Plumbing' });
    assert.equal(await page.locator('#onboarding_apiKey').inputValue(), 'saved-key');
    await page.evaluate(() => { document.getElementById('onboardingDlg').close(); startSetupHelp(); });
    assert.equal(await page.locator('#onboarding_userName').inputValue(), 'Existing User');
    assert.equal(await page.locator('#onboarding_apiKey').inputValue(), 'saved-key');
    assert.equal(await page.locator('input[value="Plumbing"][name="onboarding_discipline_checkbox"]').isChecked(), true);

    await boot();
    await toAi('Plumbing');
    await page.locator('#onboarding_apiKey').fill('bad-key');
    await next();
    await page.waitForFunction(() => !onboardingBusy);
    assert.equal(await page.evaluate(() => saves.length), 0);
    assert.equal(await page.evaluate(() => userSettings.userName), '');
    assert.match(await page.locator('#onboardingApiKeyStatus').textContent(), /rejected/);
    await page.locator('#onboarding_apiKey').fill('valid-test-key');
    await page.locator('[data-click-action="testOnboardingApiKey"]').click();
    await page.waitForFunction(() => !onboardingBusy);
    assert.match(await page.locator('#onboardingApiKeyStatus').textContent(), /accepted/);
    await next();
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    assert.deepEqual(await page.evaluate(() => keyTests), ['bad-key', 'valid-test-key']);
    assert.equal(await page.evaluate(() => saves[0].activeDiscipline), 'Plumbing');
    assert.equal(await page.evaluate(() => saves[0].apiKey), 'valid-test-key');
    console.log('PASS: rejected keys cannot finish; tested keys save without a duplicate request.');

    await boot();
    await toAi();
    await page.locator('#onboarding_apiKey').fill('offline');
    await next();
    await page.waitForFunction(() => !onboardingBusy);
    assert.match(await page.locator('#onboardingApiKeyStatus').textContent(), /Could not reach Google/);
    await skip().click();
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    assert.equal(await page.evaluate(() => saves[0].apiKey), '');
    assert.equal(await page.evaluate(() => saves[0].userName), 'Test Engineer');
    console.log('PASS: network failure allows saving the profile without an untested key.');

    await boot();
    await page.evaluate(() => failSave = true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !onboardingBusy);
    assert.equal(await page.locator('#onboardingDlg').evaluate(node => node.open), true);
    assert.equal(await page.evaluate(() => userSettings.onboardingComplete), false);
    assert.equal(await page.evaluate(() => isNewUser()), true);
    assert.equal(await skip().isEnabled(), true);
    await page.evaluate(() => { failSave = false; deferSave = true; void skipOnboarding(); void skipOnboarding(); });
    assert.equal(await page.evaluate(() => saves.length), 2, 'one failed save and one pending retry');
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => saves.length), 2);
    assert.equal(await skip().isDisabled(), true);
    await page.evaluate(() => releaseSave());
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    assert.equal(await page.evaluate(() => userSettings.onboardingComplete), true);
    assert.deepEqual(errors, []);
    console.log('PASS: save failures retain setup; retries and Escape cannot start overlapping saves.');

    const install = () => page.locator('#onboardingInstallPluginsBtn');
    const pluginStatus = () => page.locator('#onboardingPluginStatus').textContent();
    await boot();
    await toPlugins();
    await page.evaluate(() => deferInstall = true);
    await install().click();
    await page.waitForFunction(() => installs.length === 1);
    assert.match(await pluginStatus(), /Installing ACIES Commands/);
    assert.equal(await install().isDisabled(), true);
    assert.equal(await page.locator('#onboardingNextBtn').isDisabled(), true);
    assert.equal(await skip().isDisabled(), true);
    await page.keyboard.press('Escape');
    await page.evaluate(() => { void installOnboardingPlugins(); releaseInstall(); });
    await page.waitForFunction(() => !onboardingBusy);
    assert.deepEqual(await page.evaluate(() => installs), ['ACIES.zip']);
    assert.match(await pluginStatus(), /Installed 1 plugin/);
    assert.equal(await install().textContent(), 'Plugins installed');
    assert.equal(await install().isDisabled(), true);
    assert.equal(await page.evaluate(() => commandDialogs), 0, 'command settings do not cover onboarding');
    assert.equal(await page.evaluate(() => saves.length), 0, 'installation keeps onboarding open');
    await next();
    await page.locator('#onboardingPrevBtn').click();
    assert.equal(await install().isDisabled(), true, 'navigation does not enable reinstall');
    await next();
    await next();
    await page.waitForFunction(() => !document.getElementById('onboardingDlg').open);
    assert.equal(await page.locator('#pluginSetupBanner').isVisible(), false);
    console.log('PASS: installs from onboarding with inline progress, prevents duplicate installs and permits completing setup.');

    await boot();
    await toPlugins();
    await page.evaluate(() => installFailure = { status: 'error', code: 'autocad_running', message: 'Close AutoCAD and try again.' });
    await install().click();
    await page.waitForFunction(() => !onboardingBusy);
    assert.match(await pluginStatus(), /Close AutoCAD/);
    assert.equal(await install().isEnabled(), true);
    await page.evaluate(() => installFailure = null);
    await install().click();
    await page.waitForFunction(() => !onboardingBusy);
    assert.match(await pluginStatus(), /Installed 1 plugin/);
    console.log('PASS: AutoCAD running errors stay in onboarding and allow retry.');

    await boot();
    await toPlugins();
    await page.evaluate(() => {
      pluginBundles.push({ bundle_name: 'ElectricalCommands.PlotCommands.bundle', state: 'not_installed', asset: { name: 'Plot.zip' } });
      const originalInstall = window.pywebview.api.install_single_bundle;
      window.pywebview.api.install_single_bundle = async asset => {
        if (asset.name === 'Plot.zip') {
          installs.push(asset.name);
          return { status: 'error', message: 'Download failed.' };
        }
        return originalInstall(asset);
      };
      window.restorePluginInstall = () => { window.pywebview.api.install_single_bundle = originalInstall; };
    });
    await install().click();
    await page.waitForFunction(() => !onboardingBusy);
    assert.match(await pluginStatus(), /Installed 1 plugin.*1 plugin failed.*Download failed/);
    assert.equal(await install().isEnabled(), true);
    await page.evaluate(() => window.restorePluginInstall());
    await install().click();
    await page.waitForFunction(() => !onboardingBusy);
    assert.deepEqual(await page.evaluate(() => installs), ['ACIES.zip', 'Plot.zip', 'Plot.zip']);
    assert.equal(await install().isDisabled(), true);
    console.log('PASS: partial installs show failures and retry only the missing plugins.');

    for (const scenario of ['no-autocad', 'offline', 'already-installed', 'no-download']) {
      await boot();
      await toPlugins();
      await page.evaluate(scenario => {
        if (scenario === 'no-autocad') autocadVersions = [];
        if (scenario === 'offline') failPluginList = true;
        if (scenario === 'already-installed') pluginBundles[0].state = 'installed';
        if (scenario === 'no-download') pluginBundles[0].asset = null;
      }, scenario);
      await install().click();
      await page.waitForFunction(() => !onboardingBusy);
      assert.match(await pluginStatus(), {
        'no-autocad': /AutoCAD was not detected/,
        offline: /Could not install plugins/,
        'already-installed': /already installed/,
        'no-download': /No plugin downloads/,
      }[scenario]);
      assert.equal(await page.evaluate(() => installs.length), 0);
      assert.equal(await page.locator('#onboardingNextBtn').isEnabled(), true);
      await next();
      assert.equal(await page.locator('#onboardingStep5').isVisible(), true);
    }
    assert.deepEqual(errors, []);
    console.log('PASS: missing AutoCAD, unavailable downloads and existing installs do not block continuing setup.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
