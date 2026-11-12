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
          googleAuthState = { signedIn: false }, projectDataLoadError = '', currentTimesheetWeek = new Date();
        let saves = [], keyTests = [], renders = [], toasts = [], failSave = false, deferSave = false, releaseSave;
        const toast = message => toasts.push(message);
        const val = id => document.getElementById(id).value;
        const maybeShowPluginSetupBanner = async () => {};
        const refreshActiveDisciplineDependentUi = () => renders.push('discipline');
        const renderGoogleAuthUi = () => renders.push('account');
        const renderGlobalPagesView = () => renders.push('pages');
        const renderChecklistTabs = () => renders.push('checklistTabs');
        const renderChecklistsView = () => renders.push('checklists');
        const renderTemplates = () => renders.push('templates');
        const renderTimesheets = () => renders.push('timesheets');
        const render = () => { renders.push('projects'); document.getElementById('emptyState').style.display = 'block'; };
        const updateTimesheetsDuplicateIndicator = () => renders.push('timesheetIndicator');
        const getWeekEntries = () => [], formatWeekKey = () => '';
        window.pywebview = { api: {
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
          'startSetupHelp', 'getDeclarativeClickAction', 'handleDeclarativeClick'].map(extract).join('\n')}
        const normalizeWorkroomCadDiscipline = (value, fallback) => ['Electrical', 'Mechanical', 'Plumbing'].includes(value) ? value : fallback;
        ${block}
        document.addEventListener('click', handleDeclarativeClick, true);
        hideMainApp(); showOnboardingModal();
      ` });
      assert.deepEqual(errors, [], 'onboarding boot has no script errors');
    }
    const next = () => page.locator('#onboardingNextBtn').click();
    const skip = () => page.locator('#onboardingDlg [data-click-action="skipOnboarding"]');
    async function toAi(discipline = 'Mechanical') {
      await next();
      await page.locator('#onboarding_userName').fill('Test Engineer');
      await next();
      await page.locator('input[name="onboarding_discipline_checkbox"][value="Electrical"]').uncheck();
      await page.locator(`input[name="onboarding_discipline_checkbox"][value="${discipline}"]`).check();
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
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
