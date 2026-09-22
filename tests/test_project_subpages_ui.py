import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class ProjectSubpagesUiTests(unittest.TestCase):
    @staticmethod
    def _block(text: str, start_marker: str, end_marker: str) -> str:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
        return text[start:end]

    def test_subpage_normalization_repairs_invalid_tree_data(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        normalize_block = self._block(
            script,
            "function normalizeProjectSubpages(rawSubpages = []) {",
            "function getProjectSubpages(project) {",
        )

        self.assertIn("const ids = new Set(subpages.map((subpage) => subpage.id));", normalize_block)
        self.assertIn("!ids.has(subpage.parentId)", normalize_block)
        self.assertIn("subpage.parentId === subpage.id", normalize_block)
        self.assertIn("subpage.parentId = null;", normalize_block)
        self.assertIn("const hasAncestorCycle = (subpage) => {", normalize_block)
        self.assertIn("if (hasAncestorCycle(subpage)) subpage.parentId = null;", normalize_block)

    def test_inline_child_links_show_direct_subpages_without_depth_cap(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        links_block = self._block(
            script,
            "function renderPageChildLinks(project, activeSubpage = null) {",
            "function queuePageTitleSave() {",
        )

        self.assertIn('const container = document.getElementById("pageChildLinks");', links_block)
        self.assertIn("const groups = getProjectSubpagesByParent(project);", links_block)
        self.assertIn('const parentKey = activeSubpage?.id || "";', links_block)
        self.assertIn("const children = groups.get(parentKey) || [];", links_block)
        self.assertIn("const childCount = (groups.get(child.id) || []).length;", links_block)
        self.assertIn("onclick: () => openProjectPage(project, child),", links_block)
        self.assertNotIn("renderChildren", links_block)
        self.assertNotIn("projectSubpageExpandedIds", links_block)
        self.assertNotIn("MAX", links_block)
        self.assertNotIn("depth < ", links_block)

    def test_inline_child_links_wire_add_button_and_delete_icon(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        links_block = self._block(
            script,
            "function renderPageChildLinks(project, activeSubpage = null) {",
            "function queuePageTitleSave() {",
        )

        self.assertIn('createTabDeleteIcon("Delete subpage"', links_block)
        self.assertIn("deleteProjectSubpage(project, child)", links_block)
        self.assertIn('className: "page-child-link page-child-link-add"', links_block)
        self.assertIn("onclick: () => createProjectSubpageFromSlash(),", links_block)

    def test_legacy_child_link_renderer_does_not_mutate_react_owned_subtree(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        links_block = self._block(
            script,
            "function renderPageChildLinks(project, activeSubpage = null) {",
            "function queuePageTitleSave() {",
        )

        ownership_guard = "if (getProjectPagesEditorRoot()?.contains(container)) return;"
        self.assertIn(ownership_guard, links_block)
        self.assertLess(links_block.index(ownership_guard), links_block.index('container.innerHTML = "";'))

    def test_tree_sidebar_controls_are_removed(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertNotIn("function renderProjectPageTree(project, activeSubpage = null) {", script)
        self.assertNotIn("function createProjectSubpageTreeRow(", script)
        self.assertNotIn("function createProjectSubpageParentSelect(", script)
        self.assertNotIn("function getProjectSubpageParentOptions(", script)
        self.assertNotIn("function moveProjectSubpage(", script)
        self.assertNotIn("projectSubpageExpandedIds", script)

    def test_slash_page_command_creates_child_under_active_project_page(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        page_block = self._block(
            script,
            "function createProjectSubpageFromSlash() {",
            "function handlePageSlashBeforeInput(event) {",
        )

        self.assertIn("const { project, subpage } = pageNav;", page_block)
        self.assertIn("if (!project) return;", page_block)
        self.assertIn("pageEditorTarget.html = serializePageHtml(editor);", page_block)
        self.assertIn("parentId: subpage?.id || null", page_block)
        self.assertIn("subpages.push(child);", page_block)
        self.assertNotIn("projectSubpageExpandedIds", page_block)
        self.assertIn("openProjectPage(project, child);", page_block)
        self.assertNotIn("openDeliverablePage", page_block)

    def test_delete_project_subpage_removes_subtree(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        delete_block = self._block(
            script,
            "function deleteProjectSubpage(project, subpage) {",
            "function handlePageSlashBeforeInput(event) {",
        )

        self.assertIn("const descendants = getProjectSubpageDescendantIds(project, subpage.id);", delete_block)
        self.assertIn("if (!await flushPageSave()) return;", delete_block)
        self.assertIn("const removeIds = new Set([subpage.id, ...descendants]);", delete_block)
        self.assertIn(
            "pages.splice(0, pages.length, ...pages.filter((page) => !removeIds.has(page.id)));",
            delete_block,
        )
        self.assertIn(
            "openProjectPage(project, getProjectSubpageById(project, subpage.parentId));",
            delete_block,
        )

    def test_editor_routes_root_and_subpage_titles_and_assets(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        render_block = self._block(
            script,
            "function renderPageView() {",
            "function renderPageBreadcrumb(project, subpage) {",
        )
        title_block = self._block(
            script,
            "function queuePageTitleSave() {",
            "function ensurePageViewReady() {",
        )

        self.assertIn("const activeSubpage = subpage ? getProjectSubpageById(project, subpage.id) : null;", render_block)
        self.assertIn("const target = activeSubpage || project;", render_block)
        self.assertIn('`proj_${project.id || "x"}_subpage_${activeSubpage.id || "x"}`', render_block)
        self.assertIn("titleEl.textContent = (activeSubpage ? activeSubpage.title : project.name) || \"\";", render_block)
        self.assertIn("else if (subpage) subpage.title = value || \"Untitled\";", title_block)
        self.assertIn("else if (project) project.name = value;", title_block)

    def test_markup_and_styles_for_inline_child_links(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="pageChildLinks"', html)
        self.assertNotIn('id="projectPageTree"', html)
        self.assertNotIn('id="projectPageTreeList"', html)
        self.assertNotIn('id="projectPageAddRootSubpageBtn"', html)
        self.assertIn(".page-view-body {", css)
        self.assertIn(".page-child-links {", css)
        self.assertIn(".page-child-link {", css)
        self.assertIn(".page-child-link-add {", css)
        self.assertNotIn(".project-page-tree {", css)
        self.assertNotIn(".project-page-tree-row {", css)
        self.assertNotIn(".project-page-parent-select {", css)


if __name__ == "__main__":
    unittest.main()
