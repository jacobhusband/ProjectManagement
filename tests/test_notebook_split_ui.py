import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = REPO_ROOT / "index.html"
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


def get_css_block(css: str, selector: str) -> str:
    pattern = re.compile(rf"{re.escape(selector)}\s*\{{(.*?)\}}", re.S)
    match = pattern.search(css)
    if not match:
        raise AssertionError(f"CSS selector {selector!r} not found")
    return match.group(1)


class NotebookSplitUiTests(unittest.TestCase):
    def test_main_nav_has_pages_tools_timesheets_tabs(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('data-tab="notes">Pages</button>', html)
        self.assertNotIn('data-tab="checklists">Checklists</button>', html)
        self.assertNotIn('data-tab="texts"', html)
        self.assertNotIn('id="texts-panel"', html)

        notes_idx = html.index('data-tab="notes"')
        tools_idx = html.index('data-tab="tools"')
        self.assertLess(notes_idx, tools_idx)

    def test_notes_panel_is_independent(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('id="notes-panel"', html)
        self.assertNotIn('id="checklists-panel"', html)

        self.assertIn('id="notesSearch"', html)
        self.assertIn('id="notesHelpBtn"', html)
        self.assertIn('id="globalPagesList"', html)

    def test_panels_include_empty_state_blocks(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('id="notesEmptyState"', html)
        self.assertIn('id="globalPagesList"', html)
        self.assertIn('id="notesEmptyStateCreateBtn"', html)

    def test_help_topics_lists_notes(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('data-help-topic="notes"', html)
        self.assertNotIn('data-help-topic="notebook"', html)

    def test_script_drops_mode_aware_layer_in_favor_of_per_page_renderers(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertNotIn("activeNotebookType", script)
        self.assertNotIn("ensureActiveNotebookSelection", script)
        self.assertNotIn("syncNotebookSearchUi", script)
        self.assertNotIn("handleNotebookSearchInput", script)
        self.assertNotIn("renderTextsView", script)

        self.assertIn("function renderGlobalPagesView()", script)
        self.assertIn("function createTabDeleteIcon(", script)
        self.assertIn("function promptCreateGlobalPage(kind = \"\")", script)

    def test_script_wires_per_page_search_and_help(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('document.getElementById("notesSearch")', script)
        self.assertIn('notesSearchQuery = String(', script)
        self.assertIn('openHelp("notes")', script)

    def test_help_topics_constant_lists_notes(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'const HELP_TOPICS = ["projects", "deliverables", "notes", "tools", "timesheets", "misc"];',
            script,
        )

    def test_tab_init_routes_to_per_page_renderers(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('if (tab === "notes") {', script)
        self.assertIn('renderGlobalPagesView();', script)

    def test_styles_use_split_panel_selectors_and_full_height_sidebar(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertNotIn('#texts-panel', css)
        full_height_block = get_css_block(
            css, "#notes-panel .full-height,\n#checklists-panel .full-height"
        )
        self.assertIn(
            "height: clamp(700px, calc(100vh - var(--header-height) - 3.5rem), 920px);",
            full_height_block,
        )

        single_section_block = get_css_block(
            css, ".notebook-sidebar.single-section .notebook-sidebar-section"
        )
        self.assertIn("flex: 1 1 100%;", single_section_block)

    def test_styles_define_empty_state_and_hover_only_delete_icon(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        empty_state_block = get_css_block(css, ".notebook-empty-state")
        self.assertIn("display: flex;", empty_state_block)
        self.assertIn("flex-direction: column;", empty_state_block)
        self.assertIn("text-align: center;", empty_state_block)

        delete_icon_block = get_css_block(
            css,
            ".notes-nav-list .tab-delete-icon,\n.checklists-nav-list .tab-delete-icon",
        )
        self.assertIn("opacity: 0;", delete_icon_block)

        hover_reveal_block = get_css_block(
            css,
            ".notes-nav-list .inner-tab-btn:hover .tab-delete-icon,\n"
            ".checklists-nav-list .inner-tab-btn:hover .tab-delete-icon,\n"
            ".notes-nav-list .inner-tab-btn:focus-within .tab-delete-icon,\n"
            ".checklists-nav-list .inner-tab-btn:focus-within .tab-delete-icon,\n"
            ".notes-nav-list .inner-tab-btn.active .tab-delete-icon,\n"
            ".checklists-nav-list .inner-tab-btn.active .tab-delete-icon",
        )
        self.assertIn("opacity:", hover_reveal_block)


if __name__ == "__main__":
    unittest.main()
