import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class GlobalPagesUiTests(unittest.TestCase):
    """The Notes tab is now a notebook of standalone notion-like pages."""

    @staticmethod
    def _block(text: str, start_marker: str, end_marker: str) -> str:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
        return text[start:end]

    def test_global_pages_state_and_helpers(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("let globalPages = [];", script)
        self.assertIn("let activeGlobalPageId = null;", script)
        self.assertIn("function normalizeGlobalPage(raw) {", script)
        self.assertIn("function createGlobalPage({ title = \"Untitled\", html = \"\", kind = \"\" } = {}) {", script)
        self.assertIn("function getGlobalPageById(id) {", script)
        self.assertIn("function buildGlobalPagesData() {", script)
        self.assertIn("function loadGlobalPages() {", script)
        self.assertIn("function saveGlobalPages({", script)
        self.assertIn("function readGlobalPagesData(raw = {}) {", script)
        self.assertIn("function migrateLegacyNotesToPages(source = {}) {", script)
        self.assertIn("function renderGlobalPagesView() {", script)
        self.assertIn("function createGlobalPageCard(page, searchQuery = \"\") {", script)
        self.assertIn("function getGlobalPageSearchText(page) {", script)
        self.assertIn("function globalPageMatchesSearch(page, query) {", script)
        self.assertIn("function createGlobalPageSearchSnippet(text, query, fallbackLength = 140) {", script)
        self.assertIn("function promptCreateGlobalPage(kind = \"\") {", script)
        self.assertIn("function deleteGlobalPage(page) {", script)
        self.assertIn("function openGlobalPage(globalPage) {", script)
        self.assertIn("function plainTextToPageHtml(text) {", script)
        self.assertIn("function pageHtmlToPlainText(html) {", script)
        self.assertIn("function escapeHtml(value) {", script)

    def test_pages_searches_titles_and_body_text(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        search_block = self._block(
            script,
            "function getGlobalPageSearchText(page) {",
            "function renderGlobalPagesView() {",
        )
        self.assertIn('const title = String(page?.title || "");', search_block)
        self.assertIn('const body = pageHtmlToPlainText(page?.page?.html || "");', search_block)
        self.assertIn("return `${title}\\n${body}`;", search_block)
        self.assertIn("getGlobalPageSearchText(page).toLowerCase().includes(q)", search_block)

        render_block = self._block(
            script,
            "function renderGlobalPagesView() {",
            "function createGlobalPageCard(page, searchQuery = \"\") {",
        )
        self.assertIn("pages.filter((p) => globalPageMatchesSearch(p, query));", render_block)
        self.assertIn("createGlobalPageCard(page, query)", render_block)

    def test_page_search_results_highlight_matches(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        card_block = self._block(
            script,
            "function createGlobalPageCard(page, searchQuery = \"\") {",
            "function renderChecklistsView() {",
        )
        self.assertIn("title.appendChild(highlightText(titleText, query));", card_block)
        self.assertIn("const previewSnippet = createGlobalPageSearchSnippet(previewText, query);", card_block)
        self.assertIn('preview.appendChild(highlightText(previewSnippet || "Empty page", query));', card_block)

    def test_storage_is_versioned_pages(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        build_block = self._block(
            script,
            "function buildGlobalPagesData() {",
            "function loadGlobalPages() {",
        )
        self.assertIn("version: 2,", build_block)
        self.assertIn("pages: serializeGlobalPagesForStore(),", build_block)
        self.assertIn("scratchpad: scratchpadHtml,", build_block)


    def test_active_page_persistence_routing(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        persist_block = self._block(
            script,
            "async function persistActivePage() {",
            "function queuePageSave() {",
        )
        self.assertIn(
            "if (pageNav.globalPage) return saveGlobalPages({ silent: true });",
            persist_block,
        )
        self.assertIn("return save({ silent: true });", persist_block)
        # Page edits flow through persistActivePage, not save() directly.
        self.assertIn("persist: persistActivePage,", script)

    def test_global_page_editor_branch(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        render_block = self._block(
            script,
            "function renderPageView() {",
            "function renderPageBreadcrumb(project, subpage) {",
        )
        self.assertIn("if (globalPage) {", render_block)
        self.assertIn('pageEditorOwnerKey = `page_global_${globalPage.id || "x"}`;', render_block)

    def test_startup_loads_global_pages(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("loadGlobalPages(),", script)
        self.assertIn("globalPages = Array.isArray(loadedNotes) ? loadedNotes : [];", script)

    def test_pages_markup_and_label(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        self.assertIn('data-tab="notes">Pages</button>', html)
        self.assertIn('id="globalPagesList"', html)
        self.assertIn('id="globalPagesNewBtn"', html)
        # The old inline notes textarea editor is gone.
        self.assertNotIn('id="notesTextarea"', html)

    def test_pages_styles_exist(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".global-pages {", css)
        self.assertIn(".global-pages-list {", css)
        self.assertIn(".global-page-card {", css)
        self.assertIn(".global-page-card-title {", css)


if __name__ == "__main__":
    unittest.main()
