import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"
MAIN_PY_PATH = REPO_ROOT / "main.py"
EDITOR_MAIN_PATH = REPO_ROOT / "project-pages-editor" / "src" / "main.jsx"
EDITOR_STYLE_PATH = REPO_ROOT / "project-pages-editor" / "src" / "styles.css"


class PageImportantItemsUiTests(unittest.TestCase):
    @staticmethod
    def _block(text: str, start_marker: str, end_marker: str) -> str:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
        return text[start:end]

    # --- editor extension -------------------------------------------------
    def test_editor_registers_important_global_attribute_extension(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'import { Extension, Node, mergeAttributes } from "@tiptap/core";', main
        )
        self.assertIn('import { Plugin, PluginKey } from "@tiptap/pm/state";', main)
        self.assertIn(
            'import { Decoration, DecorationSet } from "@tiptap/pm/view";', main
        )
        self.assertIn(
            'const IMPORTANT_BLOCK_TYPES = ["paragraph", "heading"];', main
        )
        self.assertIn("const PageImportant = Extension.create({", main)
        self.assertIn('name: "pageImportant",', main)
        self.assertIn("addGlobalAttributes() {", main)
        self.assertIn(
            'element.getAttribute("data-important") === "true"', main
        )
        self.assertIn('{ "data-important": "true", class: "page-important" }', main)
        self.assertIn("keepOnSplit: false,", main)
        self.assertIn("      PageImportant,", main)

    def test_important_commands_target_nearest_block(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        finder = self._block(
            main,
            "function findImportantBlock($from) {",
            "function buildImportantFlagDom(view, getPos) {",
        )
        self.assertIn("if (IMPORTANT_BLOCK_TYPES.includes(node.type.name)) {", finder)
        self.assertIn("return { node, pos: $from.before(depth) };", finder)
        self.assertIn("toggleImportant:", main)
        self.assertIn("setImportant:", main)
        self.assertIn(
            'tr.setNodeAttribute(block.pos, "important", !block.node.attrs.important);',
            main,
        )
        self.assertIn('"Mod-Alt-i": () => this.editor.commands.toggleImportant(),', main)

    def test_editor_renders_clickable_widget_decoration(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        widget_block = self._block(
            main,
            "function buildImportantFlagDom(view, getPos) {",
            "const PageImportant = Extension.create({",
        )
        self.assertIn("Decoration.widget(pos + 1, buildImportantFlagDom, {", main)
        self.assertIn("side: -1,", main)
        self.assertIn('key: "page-important-flag",', main)
        self.assertIn("ignoreSelection: true,", main)
        self.assertIn("stopEvent: () => true,", main)
        self.assertIn('flag.className = "page-important-flag";', widget_block)
        self.assertIn('flag.setAttribute("contenteditable", "false");', widget_block)
        self.assertIn(
            'view.dispatch(view.state.tr.setNodeAttribute(blockPos, "important", false));',
            widget_block,
        )

    def test_slash_command_registered_before_image_entry(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        registry = self._block(
            main, "const SLASH_COMMANDS = [", "function commandMatches("
        )
        self.assertIn(
            # Workspace pages have their own rollup on the Pages tab, so the
            # command is no longer project-only.
            '{ id: "important", label: "Important", shortcut: "!!", group: "block" },',
            registry,
        )
        # "/im" substring-matches both entries; Important must rank first.
        self.assertLess(
            registry.index('id: "important"'), registry.index('id: "image"')
        )
        execute_block = self._block(
            main,
            "function executeSlashCommand(command) {",
            "function applyColorChoice(value) {",
        )
        self.assertIn(
            'else if (command.id === "important") chain.toggleImportant().run();',
            execute_block,
        )

    def test_editor_styles_flag_and_line(self):
        css = EDITOR_STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn('.project-pages-editor-content [data-important="true"] {', css)
        self.assertIn(".project-pages-editor-content .page-important-flag {", css)
        self.assertIn(".project-pages-editor-content .page-important-flag:hover {", css)
        self.assertIn("@keyframes pageImportantPulse {", css)

    # --- host rollup ------------------------------------------------------
    def test_host_collects_important_lines_from_project_and_subpages(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "const PROJECT_IMPORTANT_SELECTOR = '[data-important=\"true\"]';", script
        )
        self.assertIn('const PROJECT_IMPORTANT_MARKER = "data-important";', script)
        self.assertIn("const projectImportantItemsCache = new Map();", script)
        self.assertIn("function extractImportantPageLines(html, source) {", script)
        self.assertIn("function getProjectImportantCacheKey(project) {", script)
        self.assertIn("function getProjectImportantItems(project) {", script)
        self.assertIn("function getProjectImportantCount(project) {", script)

        extract_block = self._block(
            script,
            "function extractImportantPageLines(html, source) {",
            "function getProjectImportantCacheKey(project) {",
        )
        self.assertIn(
            "if (!raw || raw.indexOf(PROJECT_IMPORTANT_MARKER) === -1) return [];",
            extract_block,
        )
        self.assertIn(
            'new DOMParser().parseFromString(raw, "text/html")', extract_block
        )
        self.assertIn(
            "doc.querySelectorAll(PROJECT_IMPORTANT_SELECTOR)", extract_block
        )
        self.assertIn("subpageId: source.subpageId || null,", extract_block)
        # Attached-email chips live inside the flagged block; their subject and
        # remove button must not be read as part of the important line.
        self.assertIn("text: readImportantNodeText(node),", extract_block)
        reader_block = self._block(
            script,
            "function readImportantNodeText(node) {",
            "function extractImportantPageLines(html, source) {",
        )
        self.assertIn('node.querySelector(".page-email")', reader_block)
        self.assertIn('String(target.textContent || "").replace(/\\s+/g, " ").trim()', reader_block)

        items_block = self._block(
            script,
            "function getProjectImportantItems(project) {",
            "function getProjectImportantCount(project) {",
        )
        self.assertIn("if (cached && cached.key === key) return cached.items;", items_block)
        self.assertIn("if (!isCanvasPage(project.page)) {", items_block)
        self.assertIn("getProjectSubpages(project).forEach((subpage) => {", items_block)
        self.assertIn("if (isCanvasPage(subpage.page)) return;", items_block)

        key_block = self._block(
            script,
            "function getProjectImportantCacheKey(project) {",
            "function getProjectImportantItems(project) {",
        )
        self.assertIn('String(project?.page?.updatedAt || "")', key_block)
        self.assertIn('String(project?.page?.html || "").length', key_block)
        self.assertIn('String(subpage?.page?.updatedAt || "")', key_block)

    # --- deliverable card button -----------------------------------------
    def test_deliverable_card_exposes_important_action(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("const ALERT_ICON_PATH =", script)
        actions_block = self._block(
            script,
            "function createDeliverableCardTopActions(deliverable, project, card) {",
            "let openDeliverableActionsDropdown = null;",
        )
        self.assertIn('className: "deliverable-card-important-action"', actions_block)
        self.assertIn("iconPath: ALERT_ICON_PATH", actions_block)
        self.assertIn(
            "const importantItems = getProjectImportantItems(project);", actions_block
        )
        self.assertIn("if (importantItems.length) {", actions_block)
        self.assertIn("pendingImportantPageScroll = true;", actions_block)
        self.assertIn("openProjectPage(project, subpage);", actions_block)
        self.assertIn(
            "importantBtn.dataset.importantCount = String(importantItems.length);",
            actions_block,
        )
        # Notes stays explicit; important alerts remain before More.
        self.assertIn('className: "deliverable-card-open-page-action"', actions_block)
        self.assertLess(
            actions_block.index('className: "deliverable-card-important-action"'),
            actions_block.index("rightActions.appendChild(createDeliverableActionsDropdown("),
        )

    def test_scroll_to_first_important_is_threaded_through_editor_context(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        self.assertIn("let pendingImportantPageScroll = false;", script)
        self.assertIn("const focusImportant = pendingImportantPageScroll;", script)
        self.assertIn("      focusImportant,", script)
        # openProjectPage keeps its signature; the one-shot carries the intent.
        self.assertIn("function openProjectPage(project, subpage = null) {", script)
        close_block = self._block(
            script, "function closePageView(", "function pageGoBack() {"
        )
        self.assertIn("pendingImportantPageScroll = false;", close_block)

        self.assertIn("if (context.focusImportant) {", main)
        self.assertIn(
            "const target = editor.view.dom.querySelector('[data-important=\"true\"]');",
            main,
        )
        self.assertIn(
            'target.scrollIntoView({ block: "center", behavior: "auto" });', main
        )
        self.assertIn('target.classList.add("is-important-focused");', main)

    def test_host_styles_important_button(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(
            ".deliverable-card-action-btn.deliverable-card-important-action {", css
        )
        self.assertIn(
            ".deliverable-card-action-btn.deliverable-card-important-action::after {",
            css,
        )
        self.assertIn("content: attr(data-important-count);", css)

    def test_removed_prior_art_identifiers_are_not_reintroduced(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")
        for removed in (
            "const PAGE_ITEM_TAGS = {",
            "function insertPageItem(tag) {",
            "function togglePageItem(box) {",
            "function extractPageTaggedItems(html) {",
            "function renderPageItemsRollupView() {",
            'setProjectsViewMode("rollup")',
        ):
            self.assertNotIn(removed, script)
        for removed_css in (".page-item {", ".page-item-badge {", ".page-item-text {"):
            self.assertNotIn(removed_css, css)

    # --- workspace (non-project) pages -----------------------------------
    def test_pages_tab_lists_important_items_from_workspace_pages(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        items_block = self._block(
            script,
            "function getGlobalPageImportantItems(page) {",
            "function openGlobalPageAtImportant(page) {",
        )
        self.assertIn("if (!page || isCanvasPage(page.page)) return [];", items_block)
        self.assertIn("extractImportantPageLines(page.page?.html, {", items_block)

        view_block = self._block(
            script, "function renderGlobalPagesView() {", "function createGlobalPagesImportantList(pages) {"
        )
        self.assertIn("const importantList = createGlobalPagesImportantList(visible);", view_block)

        list_block = self._block(
            script,
            "function createGlobalPagesImportantList(pages) {",
            "function createGlobalPageCard(page, searchQuery = \"\") {",
        )
        self.assertIn('className: "global-pages-important"', list_block)
        self.assertIn("onclick: () => openGlobalPageAtImportant(page),", list_block)

        card_block = self._block(
            script, "function createGlobalPageCard(page, searchQuery = \"\") {", "function renderChecklistsView() {"
        )
        self.assertIn('className: "global-page-important-badge"', card_block)

        css = STYLES_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".global-pages-important {", css)
        self.assertIn(".global-pages-important-row {", css)
        self.assertIn(".global-page-important-badge {", css)

    def test_workspace_page_open_scrolls_to_first_important_line(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        opener = self._block(
            script, "function openGlobalPageAtImportant(page) {", "function getProjectSubpageAncestors("
        )
        self.assertIn("pendingImportantPageScroll = true;", opener)
        self.assertIn("void openGlobalPage(page);", opener)
        render_block = self._block(script, "function renderPageView() {", "  if (!project) return;")
        self.assertIn("const focusImportant = pendingImportantPageScroll;", render_block)
        self.assertIn("        focusImportant,\n", render_block)
        # Reopening the already-loaded page keeps its documentKey, so the editor
        # also honors the request on every new context.
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        self.assertIn("if (!editor || !context.focusImportant) return undefined;", main)
        self.assertIn("  }, [context, editor]);", main)

    def test_email_only_important_line_is_named_by_subject(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        reader = self._block(
            script,
            "function readImportantNodeText(node) {",
            "function extractImportantPageLines(html, source) {",
        )
        self.assertIn('node.querySelectorAll(".page-email[data-email-label]")', reader)
        self.assertIn('const emails = `Email: ${subjects.join(", ")}`;', reader)
        self.assertIn("return text ? `${text} · ${emails}` : emails;", reader)

    def test_pdf_renderer_preserves_important_lines(self):
        main_py = MAIN_PY_PATH.read_text(encoding="utf-8")
        self.assertIn('attr_map.get("data-important", "").lower() == "true"', main_py)
        self.assertIn('<b class="pdf-important-flag">! </b>', main_py)
        self.assertIn(".page-important {", main_py)
        self.assertIn(".pdf-important-flag {", main_py)


if __name__ == "__main__":
    unittest.main()
