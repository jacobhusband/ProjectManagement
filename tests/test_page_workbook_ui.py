import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_PATH = REPO_ROOT / "project-pages-editor" / "src" / "main.jsx"
EDITOR_STYLE_PATH = REPO_ROOT / "project-pages-editor" / "src" / "styles.css"
PROTECTION_PATH = REPO_ROOT / "project-pages-editor" / "src" / "workbookProtection.js"
SCRIPT_PATH = REPO_ROOT / "script.js"


class PageWorkbookUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.editor = EDITOR_PATH.read_text(encoding="utf-8")
        cls.styles = EDITOR_STYLE_PATH.read_text(encoding="utf-8")
        cls.protection = PROTECTION_PATH.read_text(encoding="utf-8")
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_excel_slash_command_and_serialized_node_exist(self):
        self.assertIn('id: "excel", label: "Excel workbook"', self.editor)
        self.assertIn('name: "pageWorkbook"', self.editor)
        self.assertIn('tag: "div.page-workbook[data-page-file]"', self.editor)
        self.assertIn('"data-page-file": fileRef', self.editor)
        self.assertIn('"data-file-name": fileName', self.editor)
        self.assertIn('"data-file-storage": storageType', self.editor)
        self.assertIn("PageWorkbook,", self.editor)

    def test_workbook_dialog_and_card_actions_are_wired(self):
        self.assertIn("function WorkbookDialog(", self.editor)
        self.assertIn("Add Excel workbook", self.editor)
        self.assertIn("Workbook name is required.", self.editor)
        self.assertIn("insertContentAt(anchor.position,", self.editor)
        self.assertIn('data-workbook-action": "open"', self.editor)
        self.assertIn('data-workbook-action": "delete"', self.editor)
        self.assertIn("Unavailable on this device", self.editor)
        self.assertIn("context.onOpenPageFile?.(fileRef)", self.editor)
        self.assertIn("context.onDeletePageFile?.(fileRef)", self.editor)
        self.assertIn(".page-workbook-dialog-backdrop", self.styles)
        self.assertIn(".page-workbook.is-unavailable", self.styles)

    def test_backspace_is_protected_and_undo_rehydrates_restored_cards(self):
        self.assertIn("function selectionWouldDeleteWorkbook(state, key)", self.protection)
        self.assertIn('key !== "Backspace" && key !== "Delete"', self.protection)
        self.assertIn("selectionWouldDeleteWorkbook(view.state, event.key)", self.editor)
        self.assertIn("Use the workbook card's Delete or Remove link button.", self.editor)
        self.assertIn('scheduleWorkbookHydration();', self.editor)
        self.assertIn('card.dataset.workbookHydrated = "true";', self.editor)
        self.assertIn('.setMeta("addToHistory", false)', self.editor)

    def test_dialog_can_link_existing_workbook_by_picker_or_path(self):
        self.assertIn("Link existing", self.editor)
        self.assertIn('id="pageWorkbookPath"', self.editor)
        self.assertIn("chooseExistingWorkbook", self.editor)
        self.assertIn("context.onChooseWorkbookFile", self.editor)
        self.assertIn("context.onLinkWorkbook", self.editor)
        self.assertIn("Removing this link will not delete the original file.", self.editor)
        self.assertIn(".page-workbook-path-field", self.styles)

    def test_workbook_card_uses_legible_theme_colors(self):
        self.assertNotIn("var(--glass-bg", self.styles)
        self.assertIn("background: var(--bg-secondary, #fff);", self.styles)
        self.assertIn("color: var(--text, #1a2420);", self.styles)
        self.assertIn("color: var(--text-secondary, #3d5248);", self.styles)
        self.assertIn("background: var(--bg-tertiary, #eef3f0);", self.styles)

    def test_bridge_and_cascade_cleanup_cover_managed_workbooks(self):
        self.assertIn("create_page_workbook(ownerKey", self.script)
        self.assertIn("link_page_workbook(path", self.script)
        self.assertIn("Excel Files (*.xlsx;*.xlsm;*.xls;*.xlsb;*.csv)", self.script)
        self.assertIn("get_page_file_info(fileRef)", self.script)
        self.assertIn("open_page_file(fileRef)", self.script)
        self.assertIn("delete_page_file(fileRef)", self.script)
        self.assertIn("function getPageWorkbookRefs(pageTarget)", self.script)
        self.assertIn("async function deleteManagedPageWorkbooks(pageTargets)", self.script)
        self.assertIn("globalPageTrash.push(entry);", self.script)
        self.assertIn("...getProjectSubpages(project)", self.script)
        self.assertIn("const removed = pages.filter((page) => removeIds.has(page.id));", self.script)


if __name__ == "__main__":
    unittest.main()
