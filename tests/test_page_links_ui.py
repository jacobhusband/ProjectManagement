import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class PageLinksUiTests(unittest.TestCase):
    """Obsidian-style "[[" page links to standalone Pages-tab pages."""

    @staticmethod
    def _block(text: str, start_marker: str, end_marker: str) -> str:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
        return text[start:end]

    def test_markup_and_styles_exist(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="pageLinkMenu"', html)
        self.assertIn('class="page-slash-menu page-link-menu"', html)
        self.assertIn('role="listbox"', html)

        self.assertIn(".page-wiki-link {", css)
        self.assertIn(".page-wiki-link.is-broken {", css)
        self.assertIn(".page-link-create .page-slash-menu-label {", css)

    def test_slash_registry_has_link_to_page_command(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        registry = self._block(
            script,
            "const PAGE_SLASH_COMMANDS = Object.freeze([",
            "const PAGE_IMAGE_MIN_PERCENT = 10;",
        )

        self.assertIn('id: "pageref"', registry)
        self.assertIn('label: "Link to page"', registry)
        self.assertIn('aliases: ["page link", "link to page", "wiki", "wikilink", "mention"]', registry)
        self.assertIn('action: { type: "pageLink" }', registry)

    def test_execute_routes_pagelink_action_into_bracket_flow(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        execute_block = self._block(
            script,
            "function executePageSlashCommand(command, options = {}) {",
            "function createProjectSubpageFromSlash() {",
        )
        slash_open_block = self._block(
            script,
            "function openPageLinkMenuFromSlash() {",
            "function updatePageLinkMenuFromCaret() {",
        )

        self.assertIn('command.action.type === "pageLink"', execute_block)
        self.assertIn("openPageLinkMenuFromSlash();", execute_block)
        # The slash command reuses the same "[[" anchored flow.
        self.assertIn('document.execCommand("insertText", false, "[[");', slash_open_block)
        self.assertIn("updatePageLinkMenuFromCaret();", slash_open_block)

    def test_bracket_detection_reads_query_until_closing_bracket(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        range_block = self._block(
            script,
            "function getPageLinkRangeFromCaret(editor) {",
            "function closePageLinkMenu() {",
        )

        self.assertIn("getRangeTextBeforeCaretInSlashBlock(range, editor)", range_block)
        self.assertIn('const openIndex = textBefore.lastIndexOf("[[");', range_block)
        self.assertIn("if (openIndex < 0) return null;", range_block)
        self.assertIn("const query = textBefore.slice(openIndex + 2);", range_block)
        # A closing bracket or newline cancels the link; titles may contain spaces.
        self.assertIn("if (/[[\\]\\n]/.test(query)) return null;", range_block)
        self.assertIn("range.startOffset - query.length - 2", range_block)

    def test_matches_filter_by_title_and_offer_create_when_missing(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        matches_block = self._block(
            script,
            "function getPageLinkMatches(query = \"\") {",
            "function getPageLinkRangeFromCaret(editor) {",
        )

        self.assertIn('pages.filter((page) => String(page.title || "").toLowerCase().includes(q))', matches_block)
        self.assertIn('rows = matched.slice(0, 8).map((page) => ({ type: "page", page }))', matches_block)
        self.assertIn('String(page.title || "").trim().toLowerCase() === q', matches_block)
        self.assertIn('if (q && !exists) rows.push({ type: "create", title: query.trim() });', matches_block)

    def test_keyboard_navigation_handles_arrows_enter_and_escape(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        keydown_block = self._block(
            script,
            "function handlePageLinkKeydown(event) {",
            "function choosePageLinkMatch(match) {",
        )

        self.assertIn("if (!pageLinkState.open) return false;", keydown_block)
        self.assertIn('event.key === "Escape"', keydown_block)
        self.assertIn("closePageLinkMenu();", keydown_block)
        self.assertIn('event.key === "ArrowDown" || event.key === "ArrowUp"', keydown_block)
        self.assertIn('event.key === "Enter" || event.key === "Tab"', keydown_block)
        self.assertIn("choosePageLinkMatch(matches[pageLinkState.selectedIndex] || matches[0]);", keydown_block)

    def test_choose_routes_to_insert_or_create(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        choose_block = self._block(
            script,
            "function choosePageLinkMatch(match) {",
            "function deletePageLinkQuery() {",
        )

        self.assertIn('if (match.type === "create") {', choose_block)
        self.assertIn("createGlobalPageAndLink(match.title);", choose_block)
        self.assertIn("insertPageWikiLink(match.page);", choose_block)

    def test_insert_creates_atomic_anchor_with_page_id(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        insert_block = self._block(
            script,
            "function insertPageWikiLink(page) {",
            "function createGlobalPageAndLink(title) {",
        )

        self.assertIn("deletePageLinkQuery();", insert_block)
        self.assertIn('anchor.className = "page-wiki-link";', insert_block)
        self.assertIn("anchor.dataset.pageId = page.id;", insert_block)
        self.assertIn('anchor.setAttribute("contenteditable", "false");', insert_block)
        self.assertIn("placePageCaretAfterNode(editor, trailing);", insert_block)
        self.assertIn("queuePageSave();", insert_block)

    def test_create_new_page_then_links_it(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        create_block = self._block(
            script,
            "function createGlobalPageAndLink(title) {",
            "function hydratePageWikiLinks(editor) {",
        )

        self.assertIn('createGlobalPage({ title: String(title || "").trim() || "Untitled" })', create_block)
        self.assertIn("globalPages.push(page);", create_block)
        self.assertIn("saveGlobalPages({ silent: true });", create_block)
        self.assertIn("insertPageWikiLink(page);", create_block)

    def test_hydration_resyncs_titles_and_flags_broken_links(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        hydrate_block = self._block(
            script,
            "function hydratePageWikiLinks(editor) {",
            "// --- Navigation state & rendering ---",
        )

        self.assertIn('editor.querySelectorAll("a.page-wiki-link[data-page-id]")', hydrate_block)
        self.assertIn("const page = getGlobalPageById(link.dataset.pageId);", hydrate_block)
        self.assertIn("link.textContent = page.title || \"Untitled\";", hydrate_block)
        self.assertIn('link.classList.add("is-broken");', hydrate_block)
        self.assertIn('link.classList.remove("is-broken");', hydrate_block)

    def test_render_page_view_hydrates_links_in_both_branches(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        render_block = self._block(
            script,
            "function renderPageView() {",
            "function renderPageBreadcrumb(project, subpage) {",
        )

        # Once for the global-page branch, once for the project/subpage branch.
        self.assertEqual(render_block.count("hydratePageWikiLinks(editor);"), 2)

    def test_serialize_strips_transient_link_state(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        serialize_block = self._block(
            script,
            "function serializePageHtml(editor) {",
            "// Route page persistence",
        )

        self.assertIn('clone.querySelectorAll("a.page-wiki-link").forEach((link) => {', serialize_block)
        self.assertIn('link.classList.remove("is-broken");', serialize_block)
        self.assertIn('link.removeAttribute("title");', serialize_block)

    def test_editor_wires_link_input_keydown_and_click(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        ready_block = self._block(
            script,
            "function ensurePageViewReady() {",
            "init();",
        )

        # Live "[[" detection runs on input.
        self.assertIn("updatePageLinkMenuFromCaret();", ready_block)
        # Link picker keys are consumed before the slash menu's.
        self.assertIn("if (handlePageLinkKeydown(e)) return;", ready_block)
        self.assertLess(
            ready_block.index("if (handlePageLinkKeydown(e)) return;"),
            ready_block.index("if (handlePageSlashKeydown(e)) return;"),
        )
        # Clicking a wiki link opens the target Pages-tab page.
        self.assertIn('const wiki = e.target?.closest?.("a.page-wiki-link[data-page-id]");', ready_block)
        self.assertIn("const target = getGlobalPageById(wiki.dataset.pageId);", ready_block)
        self.assertIn("if (target) openGlobalPage(target);", ready_block)


if __name__ == "__main__":
    unittest.main()
