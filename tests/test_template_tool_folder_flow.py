import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _ensure_google_genai_stub():
    try:
        from google import genai as _genai  # noqa: F401
        from google.genai import types as _types  # noqa: F401
        return
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


def _ensure_webview_stub():
    try:
        import webview  # noqa: F401
        return
    except Exception:
        webview_module = types.ModuleType("webview")
        webview_module.windows = []
        webview_module.FOLDER_DIALOG = "folder"
        webview_module.OPEN_DIALOG = "open"
        webview_module.FileDialog = types.SimpleNamespace(SAVE="save")
        webview_module.create_window = lambda *args, **kwargs: None
        webview_module.start = lambda *args, **kwargs: None
        sys.modules["webview"] = webview_module


def _ensure_dotenv_stub():
    try:
        from dotenv import load_dotenv as _load_dotenv  # noqa: F401
        return
    except Exception:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: False
        sys.modules["dotenv"] = dotenv_module


def _ensure_requests_stub():
    try:
        import requests  # noqa: F401
        return
    except Exception:
        requests_module = types.ModuleType("requests")
        requests_module.get = lambda *args, **kwargs: None
        sys.modules["requests"] = requests_module


def _ensure_pydantic_stub():
    try:
        from pydantic import BaseModel as _BaseModel, Field as _Field  # noqa: F401
        return
    except Exception:
        pydantic_module = types.ModuleType("pydantic")

        class BaseModel:
            pass

        def Field(*args, **kwargs):
            if args:
                return args[0]
            return kwargs.get("default")

        pydantic_module.BaseModel = BaseModel
        pydantic_module.Field = Field
        sys.modules["pydantic"] = pydantic_module


def _ensure_pil_stub():
    try:
        from PIL import Image as _image  # noqa: F401
        return
    except Exception:
        pil_module = types.ModuleType("PIL")
        pil_image_module = types.ModuleType("PIL.Image")
        pil_module.Image = pil_image_module
        sys.modules["PIL"] = pil_module
        sys.modules["PIL.Image"] = pil_image_module


def _ensure_openpyxl_stub():
    try:
        import openpyxl  # noqa: F401
        from openpyxl.worksheet.copier import WorksheetCopy as _WorksheetCopy  # noqa: F401
        return
    except Exception:
        openpyxl_module = types.ModuleType("openpyxl")
        worksheet_module = types.ModuleType("openpyxl.worksheet")
        copier_module = types.ModuleType("openpyxl.worksheet.copier")

        class WorksheetCopy:
            pass

        copier_module.WorksheetCopy = WorksheetCopy
        worksheet_module.copier = copier_module
        openpyxl_module.worksheet = worksheet_module

        sys.modules["openpyxl"] = openpyxl_module
        sys.modules["openpyxl.worksheet"] = worksheet_module
        sys.modules["openpyxl.worksheet.copier"] = copier_module


_ensure_google_genai_stub()
_ensure_webview_stub()
_ensure_dotenv_stub()
_ensure_requests_stub()
_ensure_pydantic_stub()
_ensure_pil_stub()
_ensure_openpyxl_stub()

import main as main_module
from main import Api


class TemplateToolFolderFlowTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_update_word_file_via_com_uses_isolated_word_instance(self):
        calls = []

        class FakeDoc:
            def __init__(self):
                self.saved = False
                self.close_args = []

            def Save(self):
                self.saved = True

            def Close(self, should_save):
                self.close_args.append(should_save)

        class FakeWord:
            def __init__(self):
                self.Visible = None
                self.DisplayAlerts = None
                self.doc = FakeDoc()
                self.opened_path = None
                self.quit_called = False
                self.Documents = types.SimpleNamespace(Open=self._open)

            def _open(self, file_path):
                self.opened_path = file_path
                return self.doc

            def Quit(self):
                self.quit_called = True

        fake_word = FakeWord()
        fake_win32com = types.ModuleType("win32com")
        fake_client = types.ModuleType("win32com.client")

        def fake_dispatch(*args, **kwargs):
            calls.append(("Dispatch", args, kwargs))
            raise AssertionError("Dispatch should not be used for Word automation")

        def fake_dispatch_ex(name):
            calls.append(("DispatchEx", name))
            return fake_word

        fake_client.Dispatch = fake_dispatch
        fake_client.DispatchEx = fake_dispatch_ex
        fake_win32com.client = fake_client

        original_win32com = sys.modules.get("win32com")
        original_win32com_client = sys.modules.get("win32com.client")

        def restore_modules():
            if original_win32com is None:
                sys.modules.pop("win32com", None)
            else:
                sys.modules["win32com"] = original_win32com
            if original_win32com_client is None:
                sys.modules.pop("win32com.client", None)
            else:
                sys.modules["win32com.client"] = original_win32com_client

        self.addCleanup(restore_modules)
        sys.modules["win32com"] = fake_win32com
        sys.modules["win32com.client"] = fake_client

        main_module._update_word_file_via_com(r"C:\Temp\template.doc", {})

        self.assertEqual([("DispatchEx", "Word.Application")], calls)
        self.assertEqual(r"C:\Temp\template.doc", fake_word.opened_path)
        self.assertFalse(fake_word.Visible)
        self.assertEqual(0, fake_word.DisplayAlerts)
        self.assertTrue(fake_word.doc.saved)
        self.assertEqual([False], fake_word.doc.close_args)
        self.assertTrue(fake_word.quit_called)

    def _make_template_record(self, temp_dir, filename="PCC.doc"):
        source_path = Path(temp_dir) / filename
        source_path.write_bytes(b"template-bytes")
        return {
            "id": "tpl_plan_check",
            "name": "Plan Check Comments",
            "discipline": "General",
            "fileType": "doc",
            "sourcePath": str(source_path),
        }

    def test_find_template_by_key_resolves_plan_check_alias(self):
        template_record = {
            "id": "tpl_plan_check",
            "name": "Comments Response",
            "fileType": "doc",
            "sourcePath": r"C:\Templates\PCC.doc",
        }

        with patch.object(self.api, "get_templates", return_value={"templates": [template_record]}):
            template, key = self.api._find_template_by_key("PCC")

        self.assertEqual("planCheck", key)
        self.assertEqual(template_record, template)

    def test_find_project_root_by_id_returns_nearest_six_digit_ancestor(self):
        with tempfile.TemporaryDirectory(prefix="acies-template-root-") as temp_dir:
            root_path = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            nested_path = root_path / "Survey" / "2026-03-10 E (JH)"
            nested_path.mkdir(parents=True)

            result = self.api._find_project_root_by_id(str(nested_path))

        self.assertEqual(os.path.normpath(str(root_path)), result)

    def test_copy_template_to_folder_returns_project_root_output_metadata_for_nested_destination(self):
        with tempfile.TemporaryDirectory(prefix="acies-template-copy-") as temp_dir:
            root_path = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            destination_folder = root_path / "Survey" / "2026-03-10 E (JH)"
            destination_folder.mkdir(parents=True)
            template_record = self._make_template_record(temp_dir)

            with patch.object(self.api, "get_templates", return_value={"templates": [template_record]}), patch.object(
                main_module,
                "_apply_template_context",
            ) as apply_mock, patch.object(
                self.api,
                "open_directory_strict",
                return_value={"status": "success"},
            ), patch.object(
                self.api,
                "open_path",
                return_value={"status": "success"},
            ):
                result = self.api.copy_template_to_folder(
                    "tpl_plan_check",
                    str(destination_folder),
                    None,
                    {"projectName": "BAC Kent, WA"},
                    {"templateKey": "planCheck"},
                )

            expected_filename = "Plan Check Comments.doc"
            expected_path = destination_folder / expected_filename

            self.assertEqual("success", result["status"])
            self.assertEqual(expected_filename, result["filename"])
            self.assertTrue(expected_path.exists())
            self.assertEqual(
                os.path.normpath(str(root_path)),
                os.path.normpath(result["outputFolderPath"]),
            )
            self.assertEqual(
                os.path.normpath(str(expected_path)),
                os.path.normpath(result["outputFilePath"]),
            )
            apply_mock.assert_called_once()

    def test_copy_template_to_folder_uses_default_name_and_destination_when_project_name_missing(self):
        with tempfile.TemporaryDirectory(prefix="acies-template-copy-") as temp_dir:
            destination_folder = Path(temp_dir) / "SurveyOutput"
            destination_folder.mkdir()
            template_record = self._make_template_record(temp_dir)

            with patch.object(self.api, "get_templates", return_value={"templates": [template_record]}), patch.object(
                main_module,
                "_apply_template_context",
            ), patch.object(
                self.api,
                "open_directory_strict",
                return_value={"status": "success"},
            ), patch.object(
                self.api,
                "open_path",
                return_value={"status": "success"},
            ):
                result = self.api.copy_template_to_folder(
                    "tpl_plan_check",
                    str(destination_folder),
                    None,
                    {},
                    {"templateKey": "planCheck"},
                )

            expected_path = destination_folder / "Plan Check Comments.doc"

            self.assertEqual("success", result["status"])
            self.assertEqual("Plan Check Comments.doc", result["filename"])
            self.assertTrue(expected_path.exists())
            self.assertEqual(
                os.path.normpath(str(destination_folder)),
                os.path.normpath(result["outputFolderPath"]),
            )
            self.assertEqual(
                os.path.normpath(str(expected_path)),
                os.path.normpath(result["outputFilePath"]),
            )

    def test_copy_template_to_folder_timestamps_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="acies-template-conflict-") as temp_dir:
            destination_folder = Path(temp_dir) / "SurveyOutput"
            destination_folder.mkdir()
            template_record = self._make_template_record(temp_dir)
            (destination_folder / "Plan Check Comments.doc").write_bytes(b"existing")

            with patch.object(self.api, "get_templates", return_value={"templates": [template_record]}), patch.object(
                main_module,
                "_apply_template_context",
            ), patch.object(
                self.api,
                "open_directory_strict",
                return_value={"status": "success"},
            ), patch.object(
                self.api,
                "open_path",
                return_value={"status": "success"},
            ):
                result = self.api.copy_template_to_folder(
                    "tpl_plan_check",
                    str(destination_folder),
                    None,
                    {},
                    {"templateKey": "planCheck"},
                )

            self.assertEqual("success", result["status"])
            self.assertRegex(
                result["filename"],
                r"^Plan Check Comments - \d{4}-\d{2}-\d{2} \d{4}( \(\d+\))?\.doc$",
            )
            self.assertTrue((destination_folder / result["filename"]).exists())

    def test_copy_template_to_folder_does_not_attempt_to_open_outputs(self):
        with tempfile.TemporaryDirectory(prefix="acies-template-warning-") as temp_dir:
            destination_folder = Path(temp_dir) / "SurveyOutput"
            destination_folder.mkdir()
            template_record = self._make_template_record(temp_dir)

            with patch.object(self.api, "get_templates", return_value={"templates": [template_record]}), patch.object(
                main_module,
                "_apply_template_context",
            ), patch.object(
                self.api,
                "open_directory_strict",
                return_value={"status": "error", "message": "folder open failed"},
            ) as open_folder_mock, patch.object(
                self.api,
                "open_path",
                return_value={"status": "error", "message": "file open failed"},
            ) as open_file_mock:
                result = self.api.copy_template_to_folder(
                    "tpl_plan_check",
                    str(destination_folder),
                    None,
                    {},
                    {"templateKey": "planCheck", "openOutputs": True},
                )

            self.assertEqual("success", result["status"])
            self.assertIn("outputFolderPath", result)
            self.assertIn("outputFilePath", result)
            self.assertNotIn("openFolderError", result)
            self.assertNotIn("openFileError", result)
            self.assertNotIn("warnings", result)
            open_folder_mock.assert_not_called()
            open_file_mock.assert_not_called()

    def test_select_template_output_folder_uses_provided_default_directory(self):
        with tempfile.TemporaryDirectory(prefix="acies-template-output-folder-") as temp_dir:
            default_dir = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            default_dir.mkdir(parents=True)
            captured = {}

            class FakeWindow:
                def create_file_dialog(self, dialog_type, **kwargs):
                    captured["dialog_type"] = dialog_type
                    captured["kwargs"] = kwargs
                    return (str(default_dir),)

            with patch.object(main_module.webview, "windows", [FakeWindow()]), patch.object(
                main_module.webview,
                "FileDialog",
                types.SimpleNamespace(FOLDER="folder"),
            ):
                result = self.api.select_template_output_folder(str(default_dir))

            self.assertEqual("success", result["status"])
            self.assertEqual(str(default_dir), result["path"])
            self.assertEqual("folder", captured["dialog_type"])
            self.assertEqual(os.path.normpath(str(default_dir)), os.path.normpath(captured["kwargs"]["directory"]))

    def test_select_template_output_folder_rejects_a_disposed_window(self):
        calls = []

        class FakeWindow:
            native = types.SimpleNamespace(Disposing=False, IsDisposed=True)

            def create_file_dialog(self, *args, **kwargs):
                calls.append((args, kwargs))
                return ("should-not-be-returned",)

        with patch.object(main_module.webview, "windows", [FakeWindow()]), patch.object(
            main_module.webview,
            "FileDialog",
            types.SimpleNamespace(FOLDER="folder"),
        ):
            result = self.api.select_template_output_folder()

        self.assertEqual("error", result["status"])
        self.assertIn("closing or unavailable", result["message"])
        self.assertEqual([], calls)

    def test_select_template_output_folder_rejects_new_dialogs_during_shutdown(self):
        calls = []

        class FakeWindow:
            def create_file_dialog(self, *args, **kwargs):
                calls.append((args, kwargs))
                return ("should-not-be-returned",)

        self.api.begin_shutdown()
        with patch.object(main_module.webview, "windows", [FakeWindow()]), patch.object(
            main_module.webview,
            "FileDialog",
            types.SimpleNamespace(FOLDER="folder"),
        ):
            result = self.api.select_template_output_folder()

        self.assertEqual("error", result["status"])
        self.assertIn("closing or unavailable", result["message"])
        self.assertEqual([], calls)

    def test_select_files_uses_provided_default_directory(self):
        with tempfile.TemporaryDirectory(prefix="acies-select-files-") as temp_dir:
            default_dir = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            default_dir.mkdir(parents=True)
            selected_file = default_dir / "panel.xlsx"
            selected_file.write_text("", encoding="utf-8")
            captured = {}

            class FakeWindow:
                def create_file_dialog(self, dialog_type, **kwargs):
                    captured["dialog_type"] = dialog_type
                    captured["kwargs"] = kwargs
                    return (str(selected_file),)

            with patch.object(main_module.webview, "windows", [FakeWindow()]), patch.object(
                main_module.webview,
                "FileDialog",
                types.SimpleNamespace(SAVE="save", OPEN="open"),
            ):
                result = self.api.select_files(
                    {
                        "allow_multiple": False,
                        "file_types": ["Excel Files (*.xlsx;*.xls)"],
                        "default_directory": str(default_dir),
                    }
                )

            self.assertEqual("success", result["status"])
            self.assertEqual([str(selected_file)], list(result["paths"]))
            self.assertEqual("open", captured["dialog_type"])
            self.assertEqual(os.path.normpath(str(default_dir)), os.path.normpath(captured["kwargs"]["directory"]))
            self.assertEqual(False, captured["kwargs"]["allow_multiple"])
            self.assertEqual(("Excel Files (*.xlsx;*.xls)",), captured["kwargs"]["file_types"])


class NarrativeOutputFolderTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="acies-narrative-folder-")
        self.addCleanup(self.temp_dir.cleanup)
        self.project_root = Path(self.temp_dir.name) / "260243 Sample Clinic"
        self.project_root.mkdir()
        self.pdf_root = self.project_root / "PDF"

    def _assert_picker_directory(self, expected, default_dir=None, template_key="narrative"):
        chosen = self.project_root / "Chosen output"
        with patch.object(self.api, "_create_file_dialog", return_value=(str(chosen),)) as dialog:
            result = self.api.select_template_output_folder(
                str(default_dir or self.project_root), template_key
            )
        self.assertEqual("success", result["status"])
        self.assertEqual(str(chosen), result["path"])
        self.assertEqual(os.path.normpath(str(expected)),
                         os.path.normpath(dialog.call_args.kwargs["directory"]))

    def test_newest_issue_date_wins_over_recently_modified_older_issue(self):
        older = self.pdf_root / "2026-08-16 MEP IFP"
        newest = self.pdf_root / "2026.10.12 MEP RFI 03"
        undated = self.pdf_root / "Working"
        for folder in (older, newest, undated):
            folder.mkdir(parents=True)
        os.utime(newest, (1000, 1000))
        os.utime(older, (2000, 2000))
        os.utime(undated, (3000, 3000))
        (older / "2027-01-01 Nested archive").mkdir()
        (self.pdf_root / "2027-02-01 Not a folder.pdf").write_bytes(b"%PDF-1.4\n")
        self._assert_picker_directory(newest)

    def test_undated_folders_use_modification_time(self):
        older = self.pdf_root / "Previous"
        newest = self.pdf_root / "Latest"
        for folder, modified in ((older, 2000), (newest, 3000)):
            folder.mkdir(parents=True)
            os.utime(folder, (modified, modified))
        self._assert_picker_directory(newest)

    def test_empty_pdf_folder_is_the_default(self):
        self.pdf_root.mkdir()
        self._assert_picker_directory(self.pdf_root)

    def test_missing_pdf_folder_keeps_project_root(self):
        self._assert_picker_directory(self.project_root)

    def test_nested_project_file_path_resolves_case_insensitive_pdf_folder(self):
        pdf_root = self.project_root / "pdf"
        newest = pdf_root / "2026-10-12 MEP IFP"
        newest.mkdir(parents=True)
        project_file = self.project_root / "Electrical" / "Plans.dwg"
        project_file.parent.mkdir()
        project_file.write_bytes(b"")
        self._assert_picker_directory(newest, default_dir=project_file)
        self._assert_picker_directory(newest, default_dir=pdf_root)

    def test_other_template_tools_keep_their_supplied_default(self):
        (self.pdf_root / "2026-10-12 MEP IFP").mkdir(parents=True)
        for template_key in (None, "planCheck"):
            with self.subTest(template_key=template_key):
                self._assert_picker_directory(self.project_root, template_key=template_key)

    def test_dialog_fallback_keeps_resolved_narrative_directory(self):
        newest = self.pdf_root / "2026-10-12 MEP IFP"
        newest.mkdir(parents=True)
        with patch.object(self.api, "_create_file_dialog", side_effect=TypeError), patch.object(
            self.api, "select_folder", return_value={"status": "cancelled", "path": None}
        ) as fallback:
            result = self.api.select_template_output_folder(str(self.project_root), "narrative")
        fallback.assert_called_once_with(str(newest))
        self.assertEqual("cancelled", result["status"])


if __name__ == "__main__":
    unittest.main()
