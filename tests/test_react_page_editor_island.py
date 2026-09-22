import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = REPO_ROOT / "index.html"
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
EDITOR_MAIN_PATH = REPO_ROOT / "project-pages-editor" / "src" / "main.jsx"
EDITOR_STYLE_PATH = REPO_ROOT / "project-pages-editor" / "src" / "styles.css"
EDITOR_PACKAGE_PATH = REPO_ROOT / "project-pages-editor" / "package.json"
ROOT_SPEC_PATH = REPO_ROOT / "ACIES Scheduler.spec"
BUILD_SPEC_PATH = REPO_ROOT / "build-config" / "ACIES Scheduler.spec"
BUILD_SCRIPT_PATH = REPO_ROOT / "build-config" / "build.ps1"


class ReactPageEditorIslandTests(unittest.TestCase):
    def test_index_loads_project_pages_editor_bundle(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('id="projectPagesEditorRoot"', html)
        self.assertIn(
            "project-pages-editor/dist/project-pages-editor-project-pages-editor.css",
            html,
        )
        self.assertIn(
            "project-pages-editor/dist/project-pages-editor.js",
            html,
        )
        # The bundle must be parsed before script.js so window.ProjectPagesEditor
        # exists by the time the host mounts it. Cache-busters change per release,
        # so match the tag rather than a pinned version.
        self.assertLess(
            html.index("project-pages-editor/dist/project-pages-editor.js"),
            html.index('<script src="script.js?v='),
        )

    def test_script_bridges_existing_page_state_to_react_editor(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("function setProjectPagesEditorDocument(context) {", script)
        self.assertIn("window.ProjectPagesEditor.mount(root, {});", script)
        self.assertIn("window.ProjectPagesEditor.setDocument({", script)
        self.assertIn("function queueProjectPagesEditorSave(html", script)
        self.assertIn("pageEditorTarget.html = next;", script)
        self.assertIn("if (window.ProjectPagesEditor?.flushSave) {", script)
        self.assertIn("await window.ProjectPagesEditor.flushSave();", script)
        self.assertIn("window.ProjectPagesEditor.unmount();", script)

    def test_react_editor_package_uses_tiptap_and_exposes_global_api(self):
        package_json = EDITOR_PACKAGE_PATH.read_text(encoding="utf-8")
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('"@tiptap/react"', package_json)
        self.assertIn('"@tiptap/starter-kit"', package_json)
        self.assertIn('"@tiptap/extension-image"', package_json)
        self.assertIn('"@tiptap/extension-task-list"', package_json)
        self.assertIn("function mount(container, options = {}) {", main)
        self.assertIn("function setDocument(pageContext) {", main)
        self.assertIn("async function flushSave() {", main)
        self.assertIn("window.ProjectPagesEditor = ProjectPagesEditorApi;", main)
        self.assertIn("export { flushSave, mount, setDocument, unmount, createSaveQueue };", main)

    def test_react_editor_keeps_legacy_html_storage_contract(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("stripTransientPageHtml(editor.getHTML())", main)
        self.assertIn('img.removeAttribute("src");', main)
        self.assertIn('if (img.dataset.asset) img.removeAttribute("src");', script)
        self.assertIn("if (pageNav.globalPage) return saveGlobalPages({ silent: true });", script)
        self.assertIn("return save({ silent: true });", script)

    def test_page_title_does_not_reconcile_browser_managed_contenteditable_children(self):
        main = EDITOR_MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn("const titleElementRef = useRef(null);", main)
        self.assertIn('const titleValueRef = useRef(context.title || "");', main)
        self.assertIn("ref={titleElementRef}", main)
        self.assertIn("titleValueRef.current = value;", main)
        self.assertNotIn("const [title, setTitle]", main)
        self.assertNotIn("setTitle(value);", main)

    def test_desktop_build_packages_editor_bundle(self):
        root_spec = ROOT_SPEC_PATH.read_text(encoding="utf-8")
        build_spec = BUILD_SPEC_PATH.read_text(encoding="utf-8")
        build_script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("project-pages-editor\\\\\\\\dist", root_spec)
        self.assertIn("'project-pages-editor', 'dist'", build_spec)
        self.assertIn("Project Pages editor frontend", build_script)
        self.assertIn(
            'project-pages-editor\\dist\\project-pages-editor.js',
            build_script,
        )

    def test_react_command_menu_labels_get_full_row_width(self):
        css = EDITOR_STYLE_PATH.read_text(encoding="utf-8")

        self.assertIn(".project-pages-menu .page-slash-menu-item {", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto;", css)


if __name__ == "__main__":
    unittest.main()
