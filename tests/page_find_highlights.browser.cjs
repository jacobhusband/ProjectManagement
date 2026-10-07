// NODE_PATH can point at the bundled runtime, as in notes_editor.browser.cjs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script.js'), 'utf8');
function extract(name) {
  const match = source.match(new RegExp(`^function ${name}\\([\\s\\S]*?^}\\r?$`, 'm'));
  assert.ok(match, `${name} exists`);
  return match[0];
}

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ path: path.join(root, 'project-pages-editor/dist/project-pages-editor.js') });
    await page.addScriptTag({ content: [
      source.match(/^const PAGE_FIND_MATCH_SELECTOR = .*;\r?$/m)[0],
      source.slice(source.indexOf('const PAGE_FIND_HIGHLIGHT_NAME ='), source.indexOf('function getPageFindRoots()')),
      ...['unwrapPageFindHighlights', 'sanitizeStoredPageHtml', 'normalizeHtmlForProjectPagesEditor',
        'getPageFindTextBlock', 'collectPageFindTextParts', 'getPageFindRanges',
        'createPageFindDomRange', 'highlightPageFindMatchesInRoot', 'pageFindCssHighlightsAvailable',
        'clearPageFindCssHighlights', 'renderPageFindHighlights'].map(extract),
      'function flattenLegacyPageItems() {} function normalizePageChecklistItems() {} function hydratePageWikiLinks() {}',
      'let pageFindState = { matches: [] };',
    ].join('\n') });

    const result = await page.evaluate(() => {
      const original = '<p>PRO<mark class="page-find-match" data-page-find-match="true"><strong>VI</strong></mark>DE ' +
        '<mark data-page-find-match="true"><a href="https://example.com">DOOR</a></mark> POWER ' +
        '<mark class="page-find-match">C</mark>IRCUIT ' +
        '<mark data-color="#ffe066" style="background-color:#ffe066">Important</mark> <mark>Reminder</mark></p>';
      const normalized = normalizeHtmlForProjectPagesEditor(original);
      const sanitized = sanitizeStoredPageHtml(original);
      const holder = document.createElement('div');
      holder.innerHTML = normalized;
      const text = holder.textContent;
      const serialized = holder.innerHTML;
      const intentional = Array.from(holder.querySelectorAll('mark')).map(node => node.textContent);
      // Search paints ranges without modifying HTML or losing inline formatting.
      const found = highlightPageFindMatchesInRoot(holder, 'DOOR');
      pageFindState.matches = found.matches;
      renderPageFindHighlights();
      const unchangedDuringSearch = holder.innerHTML === serialized;
      clearPageFindCssHighlights();
      const searchCleared = !CSS.highlights.has('page-find-match');
      const fragmented = '<p>' + '<mark>C</mark>OOR<mark>D</mark>INATE <mark>VER</mark>IFY '.repeat(20) +
        '<mark style="background-color:yellow">Keep color</mark></p>';
      holder.innerHTML = fragmented;
      const fragmentText = holder.textContent;
      unwrapPageFindHighlights(holder);
      const repaired = holder.innerHTML;
      const sameText = holder.textContent === fragmentText;
      const fewLetters = '<p><mark>C</mark>ircuit <mark>D</mark>oor</p>';
      const wholeWords = '<p>' + '<mark>Important reminder</mark> '.repeat(30) + '</p>';
      return { normalized, sanitized, intentional, text, found: found.matches.length,
        unchangedDuringSearch, searchCleared, repaired, sameText,
        fewLettersPreserved: normalizeHtmlForProjectPagesEditor(fewLetters) === fewLetters,
        wholeWordsPreserved: normalizeHtmlForProjectPagesEditor(wholeWords) === wholeWords };
    });
    assert.deepEqual(result.intentional, ['Important', 'Reminder']);
    assert.ok(result.normalized.includes('<strong>VI</strong>'));
    assert.ok(result.normalized.includes('<a href="https://example.com">DOOR</a>'));
    assert.ok(!result.sanitized.includes('page-find-match'));
    assert.equal(result.text, 'PROVIDE DOOR POWER CIRCUIT Important Reminder');
    assert.equal(result.found, 1);
    assert.ok(result.unchangedDuringSearch && result.searchCleared);
    assert.ok(result.sameText);
    assert.ok(!result.repaired.includes('<mark>'));
    assert.ok(result.repaired.includes('<mark style="background-color:yellow">Keep color</mark>'));
    assert.ok(result.fewLettersPreserved && result.wholeWordsPreserved);

    // Exercise the real Tiptap import and save path: search metadata must be
    // removed before the schema has a chance to convert it into a bare mark.
    await page.evaluate(() => {
      window.saved = '';
      ProjectPagesEditor.mount(document.getElementById('root'));
      window.openPage = (html) => ProjectPagesEditor.setDocument({
        documentKey: String(Math.random()), kind: 'global', title: 'Power',
        html: normalizeHtmlForProjectPagesEditor(html),
        onHtmlChange: html => { window.saved = html; },
      });
      openPage('<p>PRO<mark class="page-find-match">VI</mark>DE DOOR POWER</p>');
    });
    await page.locator('#pageEditor').waitFor();
    await page.evaluate(() => ProjectPagesEditor.flushSave());
    assert.equal(await page.evaluate(() => saved), '<p>PROVIDE DOOR POWER</p>');
    await page.evaluate(() => openPage(saved));
    await page.waitForFunction(() => document.querySelector('#pageEditor')?.textContent === 'PROVIDE DOOR POWER');
    assert.equal(await page.locator('#pageEditor mark').count(), 0);
    console.log('Page find browser checks passed: legacy repair, formatting preservation, temporary search, Tiptap save and reopen.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
