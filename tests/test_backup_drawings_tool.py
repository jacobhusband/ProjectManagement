import os
import shutil
import stat
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


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = REPO_ROOT / "index.html"
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class BackupDrawingsBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def _settings(self, disciplines=None):
        return {"discipline": disciplines or ["Electrical"]}

    def _write_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_backup_project_drawings_copies_configured_disciplines_and_xrefs(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "Sheets" / "power.dwg", "power")
            self._write_file(project_root / "Mechanical" / "hvac.dwg", "hvac")
            self._write_file(project_root / "Xrefs" / "arch.dwg", "arch")

            with patch.object(self.api, "get_user_settings", return_value=self._settings(["Electrical", "Mechanical"])), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ):
                result = self.api.backup_project_drawings(str(project_root))

            archive_root = project_root / "Archive"
            archive_path = archive_root / "20260319_150812"

            self.assertEqual("success", result["status"])
            self.assertEqual(os.path.normpath(str(archive_root)), os.path.normpath(result["archiveRootPath"]))
            self.assertEqual(os.path.normpath(str(archive_path)), os.path.normpath(result["archivePath"]))
            self.assertEqual(["Electrical", "Mechanical", "Xrefs"], result["copiedFolders"])
            self.assertEqual([], result["missingSourceFolders"])
            self.assertEqual(3, result["copiedFileCount"])
            self.assertTrue((archive_path / "Electrical" / "Sheets" / "power.dwg").exists())
            self.assertTrue((archive_path / "Mechanical" / "hvac.dwg").exists())
            self.assertTrue((archive_path / "Xrefs" / "arch.dwg").exists())

    def test_backup_project_drawings_preserves_workroom_resolution_details(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            self._write_file(project_root / "Xrefs" / "arch.dwg", "arch")

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ), patch.object(
                self.api,
                "_resolve_copy_project_source_path",
                return_value={
                    "status": "success",
                    "path": os.path.normpath(str(project_root)),
                    "resolvedFromWorkroom": True,
                    "resolutionMode": "project_id_ancestor",
                    "workroomProjectPath": os.path.normpath(str(project_root / "Electrical")),
                },
            ):
                result = self.api.backup_project_drawings(None, {"source": "workroom"})

            self.assertEqual("success", result["status"])
            self.assertTrue(result["resolvedFromWorkroom"])
            self.assertEqual("project_id_ancestor", result["resolutionMode"])
            self.assertEqual(
                os.path.normpath(str(project_root / "Electrical")),
                os.path.normpath(result["workroomProjectPath"]),
            )

    def test_backup_project_drawings_accepts_projects_tab_launch_context_project_path(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            self._write_file(project_root / "Xrefs" / "arch.dwg", "arch")

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ):
                result = self.api.backup_project_drawings(
                    None,
                    {
                        "source": "projects-tab",
                        "projectPath": str(project_root),
                        "projectName": "BofA - Eastport Plaza",
                    },
                )

            self.assertEqual("success", result["status"])
            self.assertFalse(result["resolvedFromWorkroom"])
            self.assertEqual("launch_context_project_path", result["resolutionMode"])
            self.assertEqual(
                os.path.normpath(str(project_root)),
                os.path.normpath(result["resolvedProjectRootPath"]),
            )

    def test_resolve_copy_project_source_path_accepts_projects_tab_launch_context(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-source-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            project_root.mkdir(parents=True)

            result = self.api._resolve_copy_project_source_path(
                None,
                {
                    "source": "projects-tab",
                    "projectPath": str(project_root),
                    "projectName": "BofA - Eastport Plaza",
                },
                self._settings(),
            )

        self.assertEqual("success", result["status"])
        self.assertFalse(result["resolvedFromWorkroom"])
        self.assertEqual("launch_context_project_path", result["resolutionMode"])
        self.assertEqual(os.path.normpath(str(project_root)), os.path.normpath(result["path"]))

    def test_backup_project_drawings_surfaces_manual_selection_required_for_workroom_resolution(self):
        with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
            self.api,
            "_resolve_copy_project_source_path",
            return_value={
                "status": "error",
                "code": "manual_selection_required",
                "message": "Could not auto-resolve project folder from Project Workroom. Please select it manually.",
            },
        ):
            result = self.api.backup_project_drawings(None, {"source": "workroom"})

        self.assertEqual("error", result["status"])
        self.assertEqual("manual_selection_required", result["code"])

    def test_backup_project_drawings_reports_missing_folders_without_creating_placeholders(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")

            with patch.object(self.api, "get_user_settings", return_value=self._settings(["Electrical", "Mechanical"])), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ):
                result = self.api.backup_project_drawings(str(project_root))

            archive_path = project_root / "Archive" / "20260319_150812"
            self.assertEqual("success", result["status"])
            self.assertEqual(["Mechanical", "Xrefs"], result["missingSourceFolders"])
            self.assertFalse((archive_path / "Mechanical").exists())
            self.assertFalse((archive_path / "Xrefs").exists())
            self.assertTrue((archive_path / "Electrical" / "power.dwg").exists())

    def test_backup_project_drawings_removes_empty_timestamp_folder_when_nothing_is_backed_up(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            project_root.mkdir(parents=True)

            with patch.object(self.api, "get_user_settings", return_value=self._settings(["Electrical", "Mechanical"])), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ):
                result = self.api.backup_project_drawings(str(project_root))

            archive_path = project_root / "Archive" / "20260319_150812"
            self.assertEqual("error", result["status"])
            self.assertEqual("nothing_to_backup", result["code"])
            self.assertFalse(archive_path.exists())

    def test_backup_project_drawings_tracks_failed_files_without_losing_successful_copies(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "good.dwg", "good")
            self._write_file(project_root / "Electrical" / "bad.dwg", "bad")
            self._write_file(project_root / "Xrefs" / "xref.dwg", "xref")

            original_copy2 = shutil.copy2

            def flaky_copy2(src, dst, *args, **kwargs):
                if os.path.basename(src).lower() == "bad.dwg":
                    raise PermissionError("locked by AutoCAD")
                return original_copy2(src, dst, *args, **kwargs)

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ), patch.object(main_module.shutil, "copy2", side_effect=flaky_copy2):
                result = self.api.backup_project_drawings(str(project_root))

            archive_path = project_root / "Archive" / "20260319_150812"
            self.assertEqual("success", result["status"])
            self.assertEqual(1, result["failedFileCount"])
            self.assertEqual(2, result["copiedFileCount"])
            self.assertTrue((archive_path / "Electrical" / "good.dwg").exists())
            self.assertFalse((archive_path / "Electrical" / "bad.dwg").exists())
            self.assertTrue((archive_path / "Xrefs" / "xref.dwg").exists())
            self.assertIn("locked by AutoCAD", result["failedFiles"][0]["error"])

    def test_backup_project_drawings_uses_unique_suffix_when_timestamp_folder_already_exists(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            self._write_file(project_root / "Xrefs" / "arch.dwg", "arch")
            (project_root / "Archive" / "20260319_150812").mkdir(parents=True)

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ):
                result = self.api.backup_project_drawings(str(project_root))

            archive_path = project_root / "Archive" / "20260319_150812 (2)"
            self.assertEqual("success", result["status"])
            self.assertEqual(os.path.normpath(str(archive_path)), os.path.normpath(result["archivePath"]))
            self.assertTrue((archive_path / "Electrical" / "power.dwg").exists())

    def test_backup_project_drawings_cancellation_removes_incomplete_archive(self):
        with tempfile.TemporaryDirectory(prefix="acies-backup-drawings-cancel-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "one.dwg", "one")
            self._write_file(project_root / "Electrical" / "two.dwg", "two")
            activity_id = "archive_activity"
            original_copy2 = shutil.copy2

            def cancel_after_first_copy(src, dst, *args, **kwargs):
                result = original_copy2(src, dst, *args, **kwargs)
                self.api.cancel_activity(activity_id)
                return result

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260319_150812",
            ), patch.object(main_module.shutil, "copy2", side_effect=cancel_after_first_copy):
                result = self.api.backup_project_drawings(
                    str(project_root),
                    activity_id=activity_id,
                )

            archive_path = project_root / "Archive" / "20260319_150812"
            self.assertEqual("cancelled", result["status"])
            self.assertFalse(archive_path.exists())


class CopyProjectLocallyBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def _settings(self, disciplines=None):
        return {"discipline": disciplines or ["Electrical"]}

    def _write_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_binary_file(self, path, size_bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size_bytes)

    def test_preview_copy_project_locally_returns_direct_subfolders_with_default_flags(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-preview-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            for folder_name in ["Specs", "Mechanical", "Electrical", "Arch", "Xrefs", "Documents", "RFI"]:
                (project_root / folder_name).mkdir(parents=True, exist_ok=True)
            (project_root / "Electrical" / "Sheets").mkdir(parents=True, exist_ok=True)

            docs_root = Path(temp_dir) / "DocumentsRoot"
            with patch.object(self.api, "get_user_settings", return_value=self._settings(["Electrical", "Mechanical"])), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.preview_copy_project_locally(str(project_root))

            self.assertEqual("success", result["status"])
            self.assertFalse(result["localProjectExists"])
            self.assertEqual(
                os.path.normpath(str(docs_root / "Local Projects" / project_root.name)),
                os.path.normpath(result["localProjectPath"]),
            )
            folder_names = [entry["name"] for entry in result["folderOptions"]]
            self.assertEqual(
                ["Arch", "Documents", "Electrical", "Mechanical", "RFI", "Xrefs", "Specs"],
                folder_names,
            )
            selection_lookup = {
                entry["name"]: bool(entry["selectedByDefault"])
                for entry in result["folderOptions"]
            }
            self.assertTrue(selection_lookup["Arch"])
            self.assertTrue(selection_lookup["Electrical"])
            self.assertTrue(selection_lookup["Mechanical"])
            self.assertTrue(selection_lookup["Xrefs"])
            self.assertTrue(selection_lookup["Documents"])
            self.assertTrue(selection_lookup["RFI"])
            self.assertFalse(selection_lookup["Specs"])
            folder_lookup = {entry["name"]: entry for entry in result["folderOptions"]}
            self.assertTrue(folder_lookup["Electrical"]["hasChildFolders"])
            self.assertFalse(folder_lookup["Specs"]["hasChildFolders"])
            self.assertTrue(
                all(entry["childrenLoaded"] is False for entry in result["folderOptions"])
            )

    def test_preview_copy_project_locally_reports_recursive_sizes_and_labels(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-size-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_binary_file(project_root / "Electrical" / "Sheets" / "power.dwg", 1024 * 1024)
            self._write_binary_file(project_root / "Electrical" / "Reports" / "load.txt", 512 * 1024)
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.preview_copy_project_locally(str(project_root))

            electrical_entry = next(
                entry for entry in result["folderOptions"] if entry["name"] == "Electrical"
            )
            self.assertEqual("success", result["status"])
            self.assertEqual(1572864, electrical_entry["sizeBytes"])
            self.assertEqual("1.5 MB", electrical_entry["sizeLabel"])
            self.assertEqual("available", electrical_entry["sizeStatus"])

    def test_preview_copy_project_locally_child_folders_returns_one_additional_level(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-child-preview-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_binary_file(project_root / "Electrical" / "root.txt", 256 * 1024)
            self._write_binary_file(project_root / "Electrical" / "Sheets" / "power.dwg", 1024 * 1024)
            self._write_binary_file(project_root / "Electrical" / "Reports" / "load.txt", 512 * 1024)
            self._write_binary_file(project_root / "Electrical" / "Sheets" / "Details" / "detail.dwg", 256 * 1024)
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.preview_copy_project_locally_child_folders(
                    str(project_root),
                    "Electrical",
                )

            self.assertEqual("success", result["status"])
            self.assertEqual("Electrical", result["parentFolderName"])
            self.assertEqual(256 * 1024, result["parentDirectFilesSizeBytes"])
            self.assertEqual("0.2 MB", result["parentDirectFilesSizeLabel"])
            child_names = [entry["name"] for entry in result["childFolderOptions"]]
            self.assertEqual(["Reports", "Sheets"], child_names)
            sheets_entry = next(
                entry for entry in result["childFolderOptions"] if entry["name"] == "Sheets"
            )
            self.assertEqual(
                os.path.normpath(str(project_root / "Electrical" / "Sheets")),
                os.path.normpath(sheets_entry["path"]),
            )
            self.assertEqual(
                os.path.normpath(os.path.join("Electrical", "Sheets")),
                os.path.normpath(sheets_entry["relativePath"]),
            )

    def test_preview_copy_project_locally_preserves_workroom_resolution_details(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-workroom-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_resolve_copy_project_source_path",
                return_value={
                    "status": "success",
                    "path": os.path.normpath(str(project_root)),
                    "resolvedFromWorkroom": True,
                    "resolutionMode": "project_id_ancestor",
                    "workroomProjectPath": os.path.normpath(str(project_root / "Electrical")),
                },
            ), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.preview_copy_project_locally(None, {"source": "workroom"})

            self.assertEqual("success", result["status"])
            self.assertTrue(result["resolvedFromWorkroom"])
            self.assertEqual("project_id_ancestor", result["resolutionMode"])
            self.assertEqual(
                os.path.normpath(str(project_root / "Electrical")),
                os.path.normpath(result["workroomProjectPath"]),
            )

    def test_preview_copy_project_locally_child_folders_preserves_workroom_resolution_details(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-child-workroom-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "Sheets" / "power.dwg", "power")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                self.api,
                "_resolve_copy_project_source_path",
                return_value={
                    "status": "success",
                    "path": os.path.normpath(str(project_root)),
                    "resolvedFromWorkroom": True,
                    "resolutionMode": "project_id_ancestor",
                    "workroomProjectPath": os.path.normpath(str(project_root / "Electrical")),
                },
            ), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.preview_copy_project_locally_child_folders(
                    None,
                    "Electrical",
                    {"source": "workroom"},
                )

            self.assertEqual("success", result["status"])
            self.assertTrue(result["resolvedFromWorkroom"])
            self.assertEqual("project_id_ancestor", result["resolutionMode"])
            self.assertEqual(
                os.path.normpath(str(project_root / "Electrical")),
                os.path.normpath(result["workroomProjectPath"]),
            )

    def test_copy_project_locally_existing_local_project_keeps_current_short_circuit(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-existing-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            docs_root = Path(temp_dir) / "DocumentsRoot"
            local_project_path = docs_root / "Local Projects" / project_root.name
            local_project_path.mkdir(parents=True, exist_ok=True)

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(str(project_root))

            self.assertEqual("error", result["status"])
            self.assertEqual("local_project_exists", result["code"])
            self.assertEqual(
                os.path.normpath(str(local_project_path)),
                os.path.normpath(result["localProjectPath"]),
            )

    def test_copy_project_locally_selected_folders_only_copies_selected_subfolders(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-selected-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            self._write_file(project_root / "Specs" / "spec.txt", "spec")
            self._write_file(project_root / "Xrefs" / "arch.dwg", "xref")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(
                    str(project_root), None, ["Electrical", "Specs"]
                )

            local_project_path = docs_root / "Local Projects" / project_root.name
            self.assertEqual("success", result["status"])
            self.assertEqual(["Electrical", "Specs"], result["copiedFolders"])
            self.assertTrue((local_project_path / "Electrical" / "power.dwg").exists())
            self.assertTrue((local_project_path / "Specs" / "spec.txt").exists())
            self.assertFalse((local_project_path / "Arch").exists())
            self.assertFalse((local_project_path / "Xrefs").exists())
            self.assertFalse((local_project_path / "Documents").exists())
            self.assertFalse((local_project_path / "RFI").exists())

    def test_copy_project_locally_subset_requests_copy_selected_children_and_parent_root_files(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-subset-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Arch" / "root-note.txt", "root")
            self._write_file(project_root / "Arch" / "Plans" / "plan.dwg", "plan")
            self._write_file(project_root / "Arch" / "Details" / "detail.dwg", "detail")
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(
                    str(project_root),
                    None,
                    None,
                    [
                        {
                            "name": "Arch",
                            "mode": "subset",
                            "selectedChildNames": ["Plans"],
                            "includeParentRootFiles": True,
                        },
                        {"name": "Electrical", "mode": "all"},
                    ],
                )

            local_project_path = docs_root / "Local Projects" / project_root.name
            self.assertEqual("success", result["status"])
            self.assertEqual(["Arch", "Electrical"], result["copiedFolders"])
            self.assertTrue((local_project_path / "Arch" / "root-note.txt").exists())
            self.assertTrue((local_project_path / "Arch" / "Plans" / "plan.dwg").exists())
            self.assertFalse((local_project_path / "Arch" / "Details").exists())
            self.assertTrue((local_project_path / "Electrical" / "power.dwg").exists())

    def test_copy_project_locally_subset_requests_report_missing_selected_child_folders_without_aborting(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-subset-missing-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Arch" / "root-note.txt", "root")
            self._write_file(project_root / "Arch" / "Plans" / "plan.dwg", "plan")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(
                    str(project_root),
                    None,
                    None,
                    [
                        {
                            "name": "Arch",
                            "mode": "subset",
                            "selectedChildNames": ["Plans", "Details"],
                            "includeParentRootFiles": True,
                        }
                    ],
                )

            local_project_path = docs_root / "Local Projects" / project_root.name
            self.assertEqual("success", result["status"])
            self.assertEqual(["Arch"], result["copiedFolders"])
            self.assertEqual(
                [os.path.join("Arch", "Details")],
                result["missingServerFolders"],
            )
            self.assertTrue((local_project_path / "Arch" / "root-note.txt").exists())
            self.assertTrue((local_project_path / "Arch" / "Plans" / "plan.dwg").exists())
            self.assertFalse((local_project_path / "Arch" / "Details").exists())

    def test_copy_project_locally_reports_missing_selected_folders_without_aborting(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-missing-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(
                    str(project_root), None, ["Electrical", "Xrefs"]
                )

            local_project_path = docs_root / "Local Projects" / project_root.name
            self.assertEqual("success", result["status"])
            self.assertEqual(["Electrical"], result["copiedFolders"])
            self.assertEqual(["Xrefs"], result["missingServerFolders"])
            self.assertEqual(1, result["copiedFileCount"])
            self.assertTrue((local_project_path / "Electrical" / "power.dwg").exists())

    def test_copy_project_locally_without_selected_folders_preserves_default_folder_behavior(self):
        with tempfile.TemporaryDirectory(prefix="acies-copy-project-local-defaults-") as temp_dir:
            project_root = Path(temp_dir) / "260243 BofA - Eastport Plaza"
            self._write_file(project_root / "Electrical" / "power.dwg", "power")
            docs_root = Path(temp_dir) / "DocumentsRoot"

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(str(project_root))

            local_project_path = docs_root / "Local Projects" / project_root.name
            self.assertEqual("success", result["status"])
            self.assertEqual(["Electrical"], result["copiedFolders"])
            self.assertEqual(
                ["Arch", "Xrefs", "Documents", "RFI"],
                result["missingServerFolders"],
            )
            self.assertTrue((local_project_path / "Arch").exists())
            self.assertTrue((local_project_path / "Electrical" / "power.dwg").exists())
            self.assertTrue((local_project_path / "Xrefs").exists())
            self.assertTrue((local_project_path / "Documents").exists())
            self.assertTrue((local_project_path / "RFI").exists())


class LocalProjectManagerBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        # Comparisons record sync baselines; keep them out of the real app data.
        metadata_dir = tempfile.TemporaryDirectory(prefix="acies-sync-metadata-")
        self.addCleanup(metadata_dir.cleanup)
        metadata_patch = patch.object(
            main_module, "SYNC_METADATA_FILE", os.path.join(metadata_dir.name, "sync_metadata.json")
        )
        metadata_patch.start()
        self.addCleanup(metadata_patch.stop)

    def _settings(self, disciplines=None):
        return {"discipline": disciplines or ["Electrical"]}

    def _write_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_list_local_project_manager_projects_lists_local_folders_with_modified_values(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-list-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            local_root = docs_root / "Local Projects"
            self._write_file(
                local_root / "260243 BofA - Eastport Plaza" / "Electrical" / "power.dwg",
                "power",
            )
            self._write_file(
                local_root / "260244 BofA - Westport Plaza" / "Arch" / "plan.dwg",
                "plan",
            )

            with patch.object(main_module, "_get_windows_documents_dir", return_value=str(docs_root)):
                result = self.api.list_local_project_manager_projects()

            self.assertEqual("success", result["status"])
            self.assertEqual(
                os.path.normpath(str(local_root)),
                os.path.normpath(result["localRootPath"]),
            )
            project_names = [entry["name"] for entry in result["projects"]]
            self.assertEqual(
                ["260243 BofA - Eastport Plaza", "260244 BofA - Westport Plaza"],
                project_names,
            )
            self.assertTrue(all(entry["lastModifiedAt"] for entry in result["projects"]))

    def test_list_local_project_manager_projects_excludes_local_archive_folder(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-list-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            local_root = docs_root / "Local Projects"
            self._write_file(
                local_root / "260243 BofA - Eastport Plaza" / "Electrical" / "power.dwg",
                "power",
            )
            self._write_file(
                local_root / "0 Archive" / "260243 BofA - Eastport Plaza" / "backup.dwg",
                "backup",
            )

            with patch.object(main_module, "_get_windows_documents_dir", return_value=str(docs_root)):
                result = self.api.list_local_project_manager_projects()

            self.assertEqual("success", result["status"])
            self.assertEqual(
                ["260243 BofA - Eastport Plaza"],
                [entry["name"] for entry in result["projects"]],
            )

    def test_preview_local_project_manager_sync_returns_newer_and_missing_candidates_and_blocked_entries(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-preview-") as temp_dir:
            local_project = Path(temp_dir) / "DocumentsRoot" / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            newer_local = local_project / "Electrical" / "newer.dwg"
            newer_server = server_project / "Electrical" / "newer.dwg"
            missing_local = local_project / "Electrical" / "missing.txt"
            older_local = local_project / "Electrical" / "older.txt"
            older_server = server_project / "Electrical" / "older.txt"
            collision_local = local_project / "Collision.txt"

            self._write_file(newer_local, "local-newer")
            self._write_file(newer_server, "server-older")
            self._write_file(missing_local, "local-only")
            self._write_file(older_local, "local-older")
            self._write_file(older_server, "server-newer")
            self._write_file(collision_local, "collision")
            (server_project / "Collision.txt").mkdir(parents=True, exist_ok=True)

            os.utime(newer_server, (1000, 1000))
            os.utime(newer_local, (2000, 2000))
            os.utime(older_local, (1000, 1000))
            os.utime(older_server, (2000, 2000))

            with patch.object(self.api, "get_user_settings", return_value=self._settings()):
                result = self.api.preview_local_project_manager_sync(
                    str(local_project),
                    str(server_project),
                )

            self.assertEqual("success", result["status"])
            candidate_lookup = {
                entry["relativePath"]: entry for entry in result["candidateFiles"]
            }
            self.assertEqual("local_newer", candidate_lookup[os.path.join("Electrical", "newer.dwg")]["reason"])
            self.assertEqual("server_missing", candidate_lookup[os.path.join("Electrical", "missing.txt")]["reason"])
            self.assertEqual(
                "Electrical",
                candidate_lookup[os.path.join("Electrical", "newer.dwg")]["rootFolder"],
            )
            self.assertEqual(
                "managed",
                candidate_lookup[os.path.join("Electrical", "newer.dwg")]["scopeType"],
            )
            self.assertEqual(
                "newer",
                candidate_lookup[os.path.join("Electrical", "newer.dwg")]["changeType"],
            )
            self.assertEqual(
                "Newer than server",
                candidate_lookup[os.path.join("Electrical", "newer.dwg")]["directionLabel"],
            )
            self.assertEqual(
                "missing",
                candidate_lookup[os.path.join("Electrical", "missing.txt")]["changeType"],
            )
            self.assertEqual(
                "Missing on server",
                candidate_lookup[os.path.join("Electrical", "missing.txt")]["directionLabel"],
            )
            self.assertNotIn(os.path.join("Electrical", "older.txt"), candidate_lookup)
            blocked_lookup = {
                entry["relativePath"]: entry for entry in result["blockedEntries"]
            }
            self.assertEqual("file_directory_conflict", blocked_lookup["Collision.txt"]["reason"])

    def test_local_project_manager_non_managed_roots_are_additive_only(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-additive-only-") as temp_dir:
            local_project = Path(temp_dir) / "DocumentsRoot" / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            arch_local = local_project / "Arch" / "plans.dwg"
            arch_server = server_project / "Arch" / "plans.dwg"
            local_only = local_project / "Documents" / "local-only.txt"
            server_only = server_project / "RFI" / "server-only.txt"

            self._write_file(arch_local, "local-arch")
            self._write_file(arch_server, "server-arch")
            self._write_file(local_only, "local-only")
            self._write_file(server_only, "server-only")

            os.utime(arch_local, (2000, 2000))
            os.utime(arch_server, (1000, 1000))

            with patch.object(self.api, "get_user_settings", return_value=self._settings()):
                sync_preview = self.api.preview_local_project_manager_sync(
                    str(local_project),
                    str(server_project),
                )
                copy_preview = self.api.preview_local_project_manager_copy_to_local(
                    str(local_project),
                    str(server_project),
                )

            self.assertEqual("success", sync_preview["status"])
            self.assertEqual("success", copy_preview["status"])

            sync_lookup = {
                entry["relativePath"]: entry for entry in sync_preview["candidateFiles"]
            }
            copy_lookup = {
                entry["relativePath"]: entry for entry in copy_preview["candidateFiles"]
            }

            # Since 2026-06-10 newer files outside the managed folders are offered too
            # (see test_newer_file_outside_managed_folder_is_detected); "additive only"
            # means sync never deletes there.
            arch_entry = sync_lookup[os.path.join("Arch", "plans.dwg")]
            self.assertEqual("additive_only", arch_entry["scopeType"])
            self.assertEqual("newer", arch_entry["changeType"])
            self.assertNotIn(os.path.join("Arch", "plans.dwg"), copy_lookup)
            self.assertEqual(
                "additive_only",
                sync_lookup[os.path.join("Documents", "local-only.txt")]["scopeType"],
            )
            self.assertEqual(
                "missing",
                sync_lookup[os.path.join("Documents", "local-only.txt")]["changeType"],
            )
            self.assertEqual(
                "server_missing",
                sync_lookup[os.path.join("Documents", "local-only.txt")]["reason"],
            )
            self.assertEqual(
                "additive_only",
                copy_lookup[os.path.join("RFI", "server-only.txt")]["scopeType"],
            )
            self.assertEqual(
                "missing",
                copy_lookup[os.path.join("RFI", "server-only.txt")]["changeType"],
            )
            self.assertEqual(
                "local_missing",
                copy_lookup[os.path.join("RFI", "server-only.txt")]["reason"],
            )

    def test_local_project_manager_uses_all_configured_disciplines_as_managed_roots(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-managed-roots-") as temp_dir:
            local_project = Path(temp_dir) / "DocumentsRoot" / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            mechanical_local = local_project / "Mechanical" / "hvac.dwg"
            mechanical_server = server_project / "Mechanical" / "hvac.dwg"

            self._write_file(mechanical_local, "local-mech")
            self._write_file(mechanical_server, "server-mech")
            os.utime(mechanical_local, (2000, 2000))
            os.utime(mechanical_server, (1000, 1000))

            with patch.object(
                self.api,
                "get_user_settings",
                return_value=self._settings(["Electrical", "Mechanical"]),
            ):
                result = self.api.preview_local_project_manager_sync(
                    str(local_project),
                    str(server_project),
                )

            self.assertEqual("success", result["status"])
            self.assertIn("Mechanical", result["managedRootNames"])
            candidate_lookup = {
                entry["relativePath"]: entry for entry in result["candidateFiles"]
            }
            self.assertEqual(
                "managed",
                candidate_lookup[os.path.join("Mechanical", "hvac.dwg")]["scopeType"],
            )
            self.assertEqual(
                "Mechanical",
                candidate_lookup[os.path.join("Mechanical", "hvac.dwg")]["rootFolder"],
            )

    def test_preview_local_project_manager_copy_to_local_returns_server_newer_candidates(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-copy-to-local-") as temp_dir:
            local_project = Path(temp_dir) / "DocumentsRoot" / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            newer_local = local_project / "Electrical" / "older-local.dwg"
            newer_server = server_project / "Electrical" / "older-local.dwg"
            missing_local = server_project / "Electrical" / "missing-local.txt"

            self._write_file(newer_local, "local-older")
            self._write_file(newer_server, "server-newer")
            self._write_file(missing_local, "server-only")

            os.utime(newer_local, (1000, 1000))
            os.utime(newer_server, (2000, 2000))

            with patch.object(self.api, "get_user_settings", return_value=self._settings()):
                result = self.api.preview_local_project_manager_copy_to_local(
                    str(local_project),
                    str(server_project),
                )

            self.assertEqual("success", result["status"])
            candidate_lookup = {
                entry["relativePath"]: entry for entry in result["candidateFiles"]
            }
            self.assertEqual(
                "server_newer",
                candidate_lookup[os.path.join("Electrical", "older-local.dwg")]["reason"],
            )
            self.assertEqual(
                "local_missing",
                candidate_lookup[os.path.join("Electrical", "missing-local.txt")]["reason"],
            )

    def test_apply_local_project_manager_copy_to_local_copies_selected_paths_and_creates_local_backup(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-copy-to-local-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            local_project = docs_root / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            selected_relative_path = os.path.join("Electrical", "Sheets", "power.dwg")
            self._write_file(local_project / selected_relative_path, "local-old")
            self._write_file(server_project / selected_relative_path, "server-new")

            os.utime(local_project / selected_relative_path, (1000, 1000))
            os.utime(server_project / selected_relative_path, (2000, 2000))

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260414_101500",
            ):
                result = self.api.apply_local_project_manager_copy_to_local(
                    str(local_project),
                    str(server_project),
                    [selected_relative_path],
                )

            backup_path = (
                docs_root
                / "Local Projects"
                / "0 Archive"
                / "260243 BofA - Eastport Plaza"
                / "20260414_101500"
                / selected_relative_path
            )
            self.assertEqual("success", result["status"])
            self.assertEqual(1, result["copiedFileCount"])
            self.assertTrue(result["backupCreated"])
            self.assertEqual("server-new", (local_project / selected_relative_path).read_text(encoding="utf-8"))
            self.assertTrue(backup_path.exists())
            self.assertEqual("local-old", backup_path.read_text(encoding="utf-8"))

    def test_apply_local_project_manager_sync_copies_selected_paths_and_reports_blocked_entries(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-apply-") as temp_dir:
            local_project = Path(temp_dir) / "DocumentsRoot" / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            selected_relative_path = os.path.join("Electrical", "Sheets", "power.dwg")
            blocked_relative_path = os.path.join("Blocked", "detail.dwg")
            self._write_file(local_project / selected_relative_path, "power")
            self._write_file(local_project / blocked_relative_path, "detail")
            self._write_file(server_project / "Blocked", "server-file")

            with patch.object(self.api, "get_user_settings", return_value=self._settings()):
                result = self.api.apply_local_project_manager_sync(
                    str(local_project),
                    str(server_project),
                    [selected_relative_path, blocked_relative_path],
                )

            self.assertEqual("success", result["status"])
            self.assertEqual(1, result["copiedFileCount"])
            self.assertTrue((server_project / selected_relative_path).exists())
            self.assertEqual(1, len(result["blockedEntries"]))
            self.assertEqual(blocked_relative_path, result["blockedEntries"][0]["relativePath"])

    def test_preview_copy_project_locally_replacement_reports_newer_and_local_only_files(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-replace-preview-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            local_project = docs_root / "Local Projects" / server_project.name
            shared_relative_path = os.path.join("Electrical", "shared.dwg")
            equal_relative_path = os.path.join("Electrical", "equal.dwg")
            local_only_relative_path = os.path.join("Documents", "local-only.txt")

            self._write_file(server_project / shared_relative_path, "server-old")
            self._write_file(local_project / shared_relative_path, "local-new")
            self._write_file(server_project / equal_relative_path, "same")
            self._write_file(local_project / equal_relative_path, "same")
            self._write_file(local_project / local_only_relative_path, "local-only")

            os.utime(server_project / shared_relative_path, (1000, 1000))
            os.utime(local_project / shared_relative_path, (2000, 2000))
            os.utime(server_project / equal_relative_path, (2000, 2000))
            os.utime(local_project / equal_relative_path, (2000, 2000))

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.preview_copy_project_locally_replacement(
                    str(server_project),
                    None,
                    ["Electrical"],
                )

            self.assertEqual("success", result["status"])
            self.assertTrue(result["localProjectExists"])
            self.assertEqual(
                [shared_relative_path],
                [entry["relativePath"] for entry in result["newerLocalFiles"]],
            )
            self.assertEqual(
                [local_only_relative_path],
                [entry["relativePath"] for entry in result["localOnlyFiles"]],
            )
            self.assertEqual(2, result["selectedServerFileCount"])
            self.assertEqual([], result["blockedEntries"])

    def test_copy_project_locally_replace_existing_backs_up_deletes_and_recreates_local_project(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-replace-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            local_project = docs_root / "Local Projects" / server_project.name
            selected_relative_path = os.path.join("Electrical", "power.dwg")
            stale_relative_path = os.path.join("Documents", "local-only.txt")

            self._write_file(server_project / selected_relative_path, "server-power")
            self._write_file(local_project / selected_relative_path, "local-old-power")
            self._write_file(local_project / stale_relative_path, "local-only")

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ), patch.object(
                self.api,
                "_build_backup_drawings_timestamp",
                return_value="20260414_101500",
            ):
                result = self.api.copy_project_locally(
                    str(server_project),
                    None,
                    ["Electrical"],
                    None,
                    True,
                )

            backup_root = (
                docs_root
                / "Local Projects"
                / "0 Archive"
                / server_project.name
                / "20260414_101500"
            )
            self.assertEqual("success", result["status"])
            self.assertTrue(result["replacedExistingLocal"])
            self.assertTrue(result["backupCreated"])
            self.assertEqual("server-power", (local_project / selected_relative_path).read_text(encoding="utf-8"))
            self.assertFalse((local_project / stale_relative_path).exists())
            self.assertEqual(
                "local-old-power",
                (backup_root / selected_relative_path).read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "local-only",
                (backup_root / stale_relative_path).read_text(encoding="utf-8"),
            )

    @unittest.skipUnless(os.name == "nt", "Windows read-only directory behavior")
    def test_copy_project_locally_replace_existing_removes_read_only_directory(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-readonly-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            server_project = Path(temp_dir) / "ServerRoot" / "251013 BofA - Rocklin"
            local_project = docs_root / "Local Projects" / server_project.name
            selected_relative_path = os.path.join("Electrical", "power.dwg")
            read_only_directory = local_project / "Electrical" / "Calculations"

            self._write_file(server_project / selected_relative_path, "server-power")
            self._write_file(read_only_directory / "load.txt", "local-calculation")
            os.chmod(read_only_directory, stat.S_IREAD)

            with patch.object(self.api, "get_user_settings", return_value=self._settings()), patch.object(
                main_module,
                "_get_windows_documents_dir",
                return_value=str(docs_root),
            ):
                result = self.api.copy_project_locally(
                    str(server_project),
                    None,
                    ["Electrical"],
                    None,
                    True,
                )

            self.assertEqual("success", result["status"])
            self.assertEqual(
                "server-power",
                (local_project / selected_relative_path).read_text(encoding="utf-8"),
            )
            self.assertFalse((local_project / "Electrical" / "Calculations").exists())

    def test_compare_project_timestamps_uses_shared_engine_and_ignores_archive_folders(self):
        with tempfile.TemporaryDirectory(prefix="acies-local-project-manager-compare-") as temp_dir:
            docs_root = Path(temp_dir) / "DocumentsRoot"
            local_project = docs_root / "Local Projects" / "260243 BofA - Eastport Plaza"
            server_project = Path(temp_dir) / "ServerRoot" / "260243 BofA - Eastport Plaza"
            local_newer = local_project / "Electrical" / "local-newer.dwg"
            server_newer_local = local_project / "Electrical" / "server-newer.dwg"
            server_newer_server = server_project / "Electrical" / "server-newer.dwg"
            local_newer_server = server_project / "Electrical" / "local-newer.dwg"

            self._write_file(local_newer, "local-newer")
            self._write_file(local_newer_server, "server-older")
            self._write_file(server_newer_local, "local-older")
            self._write_file(server_newer_server, "server-newer")
            self._write_file(local_project / "0 Archive" / "ignore-me.dwg", "local-archive")
            self._write_file(server_project / "Archive" / "ignore-me.dwg", "server-archive")

            os.utime(local_newer, (2000, 2000))
            os.utime(local_newer_server, (1000, 1000))
            os.utime(server_newer_local, (1000, 1000))
            os.utime(server_newer_server, (2000, 2000))

            with patch.object(main_module, "_get_windows_documents_dir", return_value=str(docs_root)):
                result = self.api.compare_project_timestamps(
                    str(local_project),
                    str(server_project),
                )

            self.assertEqual("success", result["status"])
            self.assertEqual("mixed", result["summary"])
            self.assertEqual("sync-to-server", result["recommendation"])
            self.assertEqual(1, result["managedLocalToServerNewerCount"])
            self.assertEqual(1, result["managedServerToLocalNewerCount"])
            self.assertEqual(
                [os.path.join("Electrical", "local-newer.dwg")],
                [entry["relativePath"] for entry in result["newerLocalFiles"]],
            )
            self.assertEqual(
                [os.path.join("Electrical", "server-newer.dwg")],
                [entry["relativePath"] for entry in result["newerServerFiles"]],
            )


class BackupDrawingsUiTests(unittest.TestCase):
    def test_backup_drawings_markup_exists(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('id="toolBackupDrawings"', html)
        self.assertIn("Archive", html)
        self.assertIn("Archive\\current-datetime", html)

    def test_backup_drawings_script_wiring_exists(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('"toolBackupDrawings"', text)
        self.assertIn("const generalToolOrder = [", text)
        self.assertIn('"toolPublishDwgs",', text)
        self.assertIn('"toolManageLayers",', text)
        self.assertIn('"toolCleanXrefs",', text)
        self.assertIn('"toolCopyProjectLocally",', text)
        self.assertIn('"toolBackupDrawings",', text)
        self.assertIn("const hasContextProjectPath = hasLaunchContextProjectPath(launchContext);", text)
        self.assertIn('toolId: "toolBackupDrawings"', text)
        self.assertIn('message: "Select project folder..."', text)
        self.assertIn('message: "Resolving project folder..."', text)
        self.assertIn('message: "Creating archive backup..."', text)
        self.assertIn("completeActivity(activityId, {", text)
        self.assertIn('openFolderPath: String(result?.archivePath || "").trim(),', text)
        self.assertIn("getLaunchContextProjectRoot(launchContext) || null", text)
        self.assertIn("window.pywebview.api.backup_project_drawings(", text)
        self.assertIn("result?.missingSourceFolders", text)
        self.assertNotIn('window.updateToolStatus("toolBackupDrawings", "DONE");', text)
        self.assertNotIn("await window.pywebview.api.open_path(result.archivePath);", text)


class LocalProjectManagerUiTests(unittest.TestCase):
    def test_local_project_manager_dialog_markup_exists(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        normalized_html = " ".join(html.split())

        self.assertIn('id="copyProjectLocallyDlg"', html)
        self.assertIn('id="copyProjectLocallyFolderList"', html)
        self.assertIn('id="localProjectManagerActivePanel"', html)
        self.assertIn('id="localProjectManagerComparisonBanner"', html)
        self.assertIn('id="localProjectManagerServerPathFallback"', html)
        self.assertIn('id="localProjectManagerBlockedSection"', html)
        self.assertIn('id="localProjectManagerBlockedList"', html)
        self.assertIn('id="localProjectManagerSyncBtn"', html)
        self.assertIn('id="localProjectManagerCopyToServerBtn"', html)
        self.assertIn("Work Locally", normalized_html)
        self.assertIn("Copy Local Changes to Server", normalized_html)
        self.assertNotIn('id="localProjectManagerCopyTabBtn"', html)
        self.assertNotIn('id="localProjectManagerSyncTabBtn"', html)
        self.assertIn("Select Project Folder", normalized_html)
        self.assertIn("Copy Selected Folders Locally", normalized_html)
        self.assertEqual(0, html.count('role="tabpanel"'))
        self.assertNotIn('id="copyProjectLocallyConfirmBtn"', html)
        self.assertNotIn('id="localProjectManagerSyncConfirmBtn"', html)
        self.assertNotIn('id="localProjectManagerManualServerPath"', html)
        self.assertNotIn('id="copyProjectLocallyChooseFolderBtn"', html)
        self.assertNotIn('id="copyProjectLocallyOpenExistingBtn"', html)
        self.assertNotIn('id="copyProjectLocallySelectDefaultsBtn"', html)
        self.assertNotIn('id="copyProjectLocallyCopyPanel"', html)
        self.assertNotIn('id="copyProjectLocallySyncPanel"', html)
        self.assertNotIn('id="localProjectManagerCopyToLocalRecommendationList"', html)
        self.assertNotIn('id="localProjectManagerSyncRecommendationList"', html)
        self.assertEqual(0, html.count('id="toolCopyProjectLocally"'))
        self.assertEqual(1, html.count('id="toolBackupDrawings"'))

    def test_local_project_manager_script_uses_copy_and_sync_flows(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'className: "copy-project-locally-row copy-project-locally-parent-row"',
            text,
        )
        self.assertIn('className: "custom-check copy-project-locally-checkbox"', text)
        self.assertIn('"data-copy-project-expand-btn": "true"', text)
        self.assertIn('"data-copy-project-child-checkbox": "true"', text)
        self.assertIn('"data-local-project-manager-direction-checkbox": directionKey', text)
        self.assertIn('"data-local-project-manager-folder-checkbox": direction,', text)
        self.assertIn('"data-local-project-manager-expand": direction,', text)
        self.assertIn('dialog.dataset.localProjectManagerAction = "copy";', text)
        self.assertIn('dialog.dataset.localProjectManagerAction = "sync";', text)
        self.assertNotIn('dialog.dataset.localProjectManagerAction = "copy-to-local";', text)
        self.assertNotIn('textContent: "Default"', text)
        self.assertIn("window.pywebview.api.preview_copy_project_locally(", text)
        self.assertIn("window.pywebview.api.preview_copy_project_locally_child_folders(", text)
        self.assertIn("preview_local_project_manager_copy_to_local", text)
        self.assertIn("preview_local_project_manager_sync", text)
        self.assertIn("preview_copy_project_locally_replacement", text)
        self.assertIn("window.pywebview.api.apply_local_project_manager_copy_to_local(", text)
        self.assertIn("window.pywebview.api.apply_local_project_manager_sync(", text)
        self.assertIn("if (entry.id === \"toolCopyProjectLocally\") {", text)
        self.assertIn("void runLocalProjectManager(launchContext);", text)
        self.assertIn('toolId: "toolCopyProjectLocally"', text)
        self.assertIn('message: "Copying selected folders..."', text)
        self.assertIn('message: "Copying server files to local..."', text)
        self.assertIn('message: "Copying local changes to server..."', text)
        self.assertIn("completeActivity(activityId, {", text)
        self.assertIn(
            "const managerResult = await openCopyProjectLocallyDialog(",
            text,
        )
        self.assertIn("const hasContextProjectPath = hasLaunchContextProjectPath(launchContext);", text)
        self.assertIn("getLaunchContextProjectRoot(copyProjectLocallyDialogState.launchContext) || null", text)
        self.assertIn("const launchProjectPath = getLaunchContextProjectRoot(launchContext);", text)
        self.assertIn("selectionPayload.selectedFolderRequests", text)
        self.assertIn("buildLocalProjectManagerCombinedConfirmPayload()", text)
        self.assertIn("serverSelectedRelativePaths", text)
        self.assertIn("localSelectedRelativePaths", text)
        self.assertIn("openLocalProjectManagerCopyToServerReview()", text)
        self.assertIn("buildLocalProjectManagerCopyToServerReviewPayload()", text)
        self.assertIn('"Replace on server"', text)
        self.assertIn('"Add to server"', text)
        self.assertIn('"Newer local files"', text)
        self.assertIn('"Local-only files"', text)
        self.assertIn("Back Up and Replace Local Project", text)
        self.assertIn("existing local project will be replaced", text)
        self.assertIn("managerResult.replaceExistingLocal === true", text)
        self.assertIn("replaceExistingLocal:", text)
        self.assertIn('copyProjectLocallyDialogState.syncReviewVisible === true', text)
        self.assertIn('label: "Open Local Folder"', text)
        self.assertIn('label: "Open Server Folder"', text)
        self.assertIn('const localProjectManagerCopyToServerBtn = document.getElementById(', text)
        self.assertIn('const localProjectManagerSyncBtn = document.getElementById(', text)
        self.assertIn("renderLocalProjectManagerActivePane();", text)
        self.assertIn("function renderLocalProjectManagerActivePane() {", text)
        self.assertEqual(1, text.count("function createLocalProjectManagerDirectionCandidateRow("))
        self.assertEqual(1, text.count("function updateLocalProjectManagerFooter("))
        self.assertIn("window.pywebview.api.copy_project_locally(", text)
        self.assertNotIn('window.updateToolStatus("toolCopyProjectLocally"', text)

    def test_local_project_manager_styles_exist(self):
        styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".copy-project-locally-dialog", styles)
        self.assertIn(".local-project-manager-dialog", styles)
        self.assertIn(".local-project-manager-tabs", styles)
        self.assertIn(".local-project-manager-banner", styles)
        self.assertIn(".local-project-manager-server-fallback", styles)
        self.assertIn(".local-project-manager-sync-row", styles)
        self.assertIn(".local-project-manager-folder-row", styles)
        self.assertIn(".local-project-manager-review-summary", styles)
        self.assertIn(".local-project-manager-replace-warning", styles)
        self.assertIn(".local-project-manager-review-section", styles)
        self.assertIn(".local-project-manager-review-row", styles)
        self.assertIn(".local-project-manager-footer", styles)
        self.assertIn(".local-project-manager-blocked-entry", styles)
        self.assertIn(".copy-project-locally-toolbar", styles)
        self.assertIn(".copy-project-locally-row", styles)
        self.assertIn(".copy-project-locally-checkbox", styles)
        self.assertIn(".copy-project-locally-expand-btn", styles)
        self.assertIn(".copy-project-locally-child-list", styles)
        self.assertIn(".copy-project-locally-child-list[hidden]", styles)
        self.assertIn(".copy-project-locally-child-row", styles)
        self.assertIn(".copy-project-locally-row-size", styles)
        self.assertNotIn(".copy-project-locally-badge", styles)


if __name__ == "__main__":
    unittest.main()
