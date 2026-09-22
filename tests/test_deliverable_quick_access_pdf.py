import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _ensure_optional_dependency_stubs():
    try:
        from google import genai as _genai  # noqa: F401
        from google.genai import types as _types  # noqa: F401
    except Exception:
        google_module = sys.modules.get("google")
        if google_module is None:
            google_module = types.ModuleType("google")
            google_module.__path__ = []
            sys.modules["google"] = google_module
        genai_module = types.ModuleType("google.genai")
        genai_types_module = types.ModuleType("google.genai.types")
        genai_module.types = genai_types_module
        google_module.genai = genai_module
        sys.modules["google.genai"] = genai_module
        sys.modules["google.genai.types"] = genai_types_module

    try:
        import webview  # noqa: F401
    except Exception:
        webview_module = types.ModuleType("webview")
        webview_module.windows = []
        webview_module.create_window = lambda *args, **kwargs: None
        webview_module.start = lambda *args, **kwargs: None
        sys.modules["webview"] = webview_module

    try:
        from dotenv import load_dotenv as _load_dotenv  # noqa: F401
    except Exception:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: False
        sys.modules["dotenv"] = dotenv_module


_ensure_optional_dependency_stubs()

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from main import Api

SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


def _make_pdf(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / name
    file_path.write_bytes(b"%PDF-1.4\n")
    return file_path


class DeliverableQuickAccessPdfBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="acies-quick-access-pdf-")
        self.addCleanup(self._temp_dir.cleanup)
        self.project_root = Path(self._temp_dir.name) / "260243 Sample Clinic"
        self.pdf_root = self.project_root / "PDF"

    def _project(self):
        return {
            "path": str(self.project_root),
            "localProjectPath": "",
            "id": "260243",
            "name": "Sample Clinic",
        }

    def test_opens_newest_issue_folder_pdf_for_active_discipline(self):
        _make_pdf(
            self.pdf_root / "2026.05.02 MEP DD90",
            "260243 Sample Clinic Electrical.pdf",
        )
        newest = _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Plumbing.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(self._project(), "Electrical", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newest), result["path"])
        self.assertEqual("2026.08.16 MEP IFP", result["folderName"])
        self.assertEqual("2026-08-16", result["issuedOn"])

    def test_discipline_selects_the_matching_file_in_the_folder(self):
        folder = self.pdf_root / "2026.08.16 MEP IFP"
        _make_pdf(folder, "260243 Sample Clinic Electrical.pdf")
        mechanical = _make_pdf(folder, "260243 Sample Clinic Mechanical.pdf")

        result = self.api.find_latest_deliverable_pdf(self._project(), "Mechanical", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(mechanical), result["path"])
        self.assertEqual("Mechanical", result["discipline"])

    def test_matching_deliverable_folder_beats_a_newer_unrelated_issue(self):
        ifp = _make_pdf(
            self.pdf_root / "2026.05.02 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFC",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(
            self._project(), "Electrical", "IFP")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(ifp), result["path"])
        self.assertTrue(result["matchedDeliverable"])

    def test_numbered_deliverable_matches_zero_padded_folder(self):
        expected = _make_pdf(
            self.pdf_root / "2026.03.04 RFI 03",
            "260243 Sample Clinic Electrical.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.07.01 RFI 07",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(
            self._project(), "Electrical", "RFI #3")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_falls_back_to_an_older_issue_when_the_newest_skipped_the_discipline(self):
        expected = _make_pdf(
            self.pdf_root / "2026.05.02 MEP DD90",
            "260243 Sample Clinic Plumbing.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(self._project(), "Plumbing", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_local_project_copy_is_used_when_the_server_path_is_missing(self):
        local_root = Path(self._temp_dir.name) / "Local Projects" / "260243 Sample Clinic"
        expected = _make_pdf(
            local_root / "PDF" / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        project = self._project()
        project["path"] = str(self.project_root)  # never created on disk
        project["localProjectPath"] = str(local_root)

        result = self.api.find_latest_deliverable_pdf(project, "Electrical", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_missing_pdf_folder_reports_an_actionable_error(self):
        self.project_root.mkdir(parents=True, exist_ok=True)

        result = self.api.find_latest_deliverable_pdf(self._project(), "Electrical", "")

        self.assertEqual("error", result["status"])
        self.assertIn("PDF folder", result["message"])

    def test_missing_discipline_pdf_reports_an_actionable_error(self):
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(self._project(), "Plumbing", "")

        self.assertEqual("error", result["status"])
        self.assertIn("Plumbing", result["message"])

    def test_unknown_discipline_is_rejected_before_touching_disk(self):
        result = self.api.find_latest_deliverable_pdf(self._project(), "General", "")

        self.assertEqual("error", result["status"])
        self.assertIn("Electrical", result["message"])

    def test_open_latest_deliverable_pdf_opens_the_resolved_file(self):
        expected = _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        with patch.object(self.api, "open_path", return_value={"status": "success"}) as opener:
            result = self.api.open_latest_deliverable_pdf(
                self._project(), "Electrical", "IFP")

        self.assertEqual("success", result["status"])
        opener.assert_called_once_with(str(expected))

    def test_open_latest_deliverable_pdf_surfaces_open_failures(self):
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        with patch.object(
            self.api, "open_path", return_value={"status": "error", "message": "boom"}
        ):
            result = self.api.open_latest_deliverable_pdf(
                self._project(), "Electrical", "IFP")

        self.assertEqual("error", result["status"])
        self.assertEqual("boom", result["message"])


class ArchSetQuickAccessBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="acies-quick-access-arch-")
        self.addCleanup(self._temp_dir.cleanup)
        self.project_root = Path(self._temp_dir.name) / "260243 Sample Clinic"
        self.arch_root = self.project_root / "Arch"

    def _project(self):
        return {
            "path": str(self.project_root),
            "localProjectPath": "",
            "id": "260243",
            "name": "Sample Clinic",
        }

    def test_dated_file_name_wins_over_an_older_dated_set(self):
        _make_pdf(self.arch_root, "Sample Clinic ARCH 2026-05-02.pdf")
        newest = _make_pdf(self.arch_root, "Sample Clinic ARCH 2026-08-16.pdf")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newest), result["path"])
        self.assertEqual("2026-08-16", result["issuedOn"])

    def test_dated_subfolder_supplies_the_date_when_the_file_has_none(self):
        _make_pdf(self.arch_root / "2026.05.02 ARCH DD", "A-Set.pdf")
        newest = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newest), result["path"])
        self.assertEqual("2026-08-16", result["issuedOn"])
        self.assertEqual("2026.08.16 ARCH IFP", result["folderName"])

    def test_dated_set_beats_an_undated_one_regardless_of_mtime(self):
        dated = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")
        undated = _make_pdf(self.arch_root / "Plans", "A-100 Floor Plan.pdf")
        os.utime(undated, (2_000_000_000, 2_000_000_000))
        os.utime(dated, (1_000_000_000, 1_000_000_000))

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(dated), result["path"])

    def test_undated_sets_fall_back_to_the_newest_file(self):
        older = _make_pdf(self.arch_root / "Plans", "A-100 Floor Plan.pdf")
        newer = _make_pdf(self.arch_root / "Plans", "A-200 Reflected Ceiling.pdf")
        os.utime(older, (1_000_000_000, 1_000_000_000))
        os.utime(newer, (2_000_000_000, 2_000_000_000))

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newer), result["path"])
        self.assertEqual("", result["issuedOn"])

    def test_archived_subtrees_are_skipped(self):
        _make_pdf(self.arch_root / "Archive" / "2026.09.01 ARCH", "A-Set.pdf")
        expected = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_non_pdf_files_are_ignored(self):
        (self.arch_root / "Plans").mkdir(parents=True, exist_ok=True)
        (self.arch_root / "Plans" / "A-100.dwg").write_bytes(b"dwg")
        (self.arch_root / "Plans" / "backgrounds.zip").write_bytes(b"zip")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("error", result["status"])
        self.assertIn("No PDF", result["message"])

    def test_project_id_ancestor_resolves_the_sibling_arch_folder(self):
        expected = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")
        electrical = self.project_root / "Electrical"
        electrical.mkdir(parents=True, exist_ok=True)

        project = self._project()
        project["path"] = str(electrical)

        result = self.api.find_latest_arch_set(project)

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_missing_arch_folder_reports_an_actionable_error(self):
        self.project_root.mkdir(parents=True, exist_ok=True)

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("error", result["status"])
        self.assertIn("Arch folder", result["message"])

    def test_open_latest_arch_set_opens_the_resolved_file(self):
        expected = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        with patch.object(self.api, "open_path", return_value={"status": "success"}) as opener:
            result = self.api.open_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        opener.assert_called_once_with(str(expected))

    def test_open_latest_arch_set_surfaces_open_failures(self):
        _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        with patch.object(
            self.api, "open_path", return_value={"status": "error", "message": "boom"}
        ):
            result = self.api.open_latest_arch_set(self._project())

        self.assertEqual("error", result["status"])
        self.assertEqual("boom", result["message"])


class IssueDateParsingTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_leading_stamp_is_read_from_issue_folder_names(self):
        parsed = self.api._parse_deliverable_pdf_issue_date("2026.08.16 MEP IFP")
        self.assertEqual("2026-08-16", parsed.isoformat())

    def test_impossible_dates_are_rejected(self):
        self.assertIsNone(self.api._parse_deliverable_pdf_issue_date("2026.13.40 MEP IFP"))

    def test_implausible_years_are_rejected(self):
        self.assertIsNone(self.api._search_issue_date("Set 1234-05-06"))

    def test_bare_project_numbers_are_not_read_as_dates(self):
        self.assertIsNone(self.api._search_issue_date("260243 Sample Clinic Arch"))

    def test_embedded_stamp_is_found_anywhere_in_a_name(self):
        parsed = self.api._search_issue_date("Sample Clinic ARCH 2026-08-16")
        self.assertEqual("2026-08-16", parsed.isoformat())


class DeliverableQuickAccessPdfUiTests(unittest.TestCase):
    def test_quick_access_dropdown_is_wired_into_the_card_action_row(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "const DELIVERABLE_QUICK_ACCESS_ACTIONS = Object.freeze([",
            'id: "openLatestPdf"',
            "getLabel: () => `Open Latest ${getActiveWorkroomDiscipline()} Set`",
            'id: "openLatestArchSet"',
            'label: "Open Latest Arch Set"',
            "function getDeliverableQuickAccessActionLabel(action) {",
            "function createDeliverableQuickAccessDropdown(deliverable, project, card) {",
            "async function runDeliverableQuickAccessOpen({",
            "function openLatestDeliverablePdf(project, deliverable) {",
            "function openLatestArchSet(project) {",
            'methodName: "open_latest_deliverable_pdf"',
            'methodName: "open_latest_arch_set"',
            "const discipline = getActiveWorkroomDiscipline();",
            "quickAccessDropdown.classList.add(\"deliverable-card-quick-access-action\");",
            # Pin moved into the card's More menu in the 2026-09-05 UX pass.
            "leftActions.append(statusDropdown, toolDropdown, quickAccessDropdown);",
            'dropdown.classList.contains("deliverable-card-quick-access-action");',
        ):
            self.assertIn(expected, text)

    def test_quick_access_menu_has_styles(self):
        text = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".deliverable-quick-access-menu {", text)


if __name__ == "__main__":
    unittest.main()
