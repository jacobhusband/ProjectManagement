import json
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
        requests_module.post = lambda *args, **kwargs: None
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


_ensure_google_genai_stub()
_ensure_webview_stub()
_ensure_dotenv_stub()
_ensure_requests_stub()
_ensure_pydantic_stub()

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as main_module
from main import Api


ELECTRICAL_COMMANDS_ROOT = REPO_ROOT.parent / "ElectricalCommands"


class ProjectChecklistBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_project_checklist_record_round_trips_and_versions(self):
        with tempfile.TemporaryDirectory(prefix="acies-project-checklists-") as temp_dir:
            db_path = Path(temp_dir) / "project_checklists.db"
            dwg_path = str(Path(temp_dir) / "260243 Example" / "Electrical" / "E001.dwg")

            with patch.object(main_module, "PROJECT_CHECKLIST_DB_FILE", str(db_path)):
                first = main_module._save_project_checklist_record(
                    "260243",
                    {
                        "state": {
                            "checklists": [
                                {
                                    "checklistId": "checklist_a",
                                    "completedItems": ["item_1", "item_1", "", "item_2"],
                                    "itemNotes": {"item_2": "Verify panel name", "": "ignored"},
                                }
                            ]
                        },
                        "dwgPath": dwg_path,
                    },
                    updated_by="desktop",
                )
                second = main_module._save_project_checklist_record(
                    "260243",
                    {
                        "state": {
                            "checklists": [
                                {
                                    "checklistId": "checklist_a",
                                    "completedItems": ["item_2"],
                                    "itemNotes": {"item_2": "Done"},
                                }
                            ]
                        },
                        "expectedVersion": first["version"],
                    },
                    updated_by="autocad",
                )
                stale = main_module._save_project_checklist_record(
                    "260243",
                    {"state": {"checklists": []}, "expectedVersion": first["version"]},
                    updated_by="autocad",
                )
                link = main_module._get_project_checklist_link(dwg_path)

            self.assertEqual(1, first["version"])
            self.assertEqual(["item_1", "item_2"], first["state"]["checklists"][0]["completedItems"])
            self.assertEqual({"item_2": "Verify panel name"}, first["state"]["checklists"][0]["itemNotes"])
            self.assertEqual(2, second["version"])
            self.assertFalse(second["conflict"])
            self.assertEqual("autocad", second["updatedBy"])
            self.assertEqual(3, stale["version"])
            self.assertTrue(stale["conflict"])
            self.assertEqual(2, stale["previousVersion"])
            self.assertEqual("260243", link["projectId"])

    def test_project_checklist_api_reports_missing_and_existing_records(self):
        with tempfile.TemporaryDirectory(prefix="acies-project-checklists-api-") as temp_dir:
            db_path = Path(temp_dir) / "project_checklists.db"
            with patch.object(main_module, "PROJECT_CHECKLIST_DB_FILE", str(db_path)):
                missing = self.api.get_project_checklist_record("260244")
                saved = self.api.save_project_checklist_record(
                    "260244",
                    {
                        "state": {
                            "checklists": [
                                {
                                    "checklistId": "checklist_b",
                                    "completedItems": ["item_3"],
                                    "itemNotes": {},
                                }
                            ]
                        },
                        "updatedBy": "desktop",
                    },
                )
                version = self.api.get_project_checklist_version("260244")

            self.assertEqual("success", missing["status"])
            self.assertFalse(missing["exists"])
            self.assertEqual("success", saved["status"])
            self.assertEqual("260244", saved["projectId"])
            self.assertEqual(1, saved["data"]["version"])
            self.assertEqual("success", version["status"])
            self.assertTrue(version["data"]["exists"])
            self.assertEqual(1, version["data"]["version"])


@unittest.skipUnless(
    ELECTRICAL_COMMANDS_ROOT.is_dir(),
    "Cross-repo contract test: needs the sibling ElectricalCommands checkout",
)
class ProjectChecklistMetadataTests(unittest.TestCase):
    def test_autocad_command_and_description_metadata_exist(self):
        command_file = (
            ELECTRICAL_COMMANDS_ROOT
            / "AutoCADCommands"
            / "GeneralCommands"
            / "ProjectChecklistCommand.cs"
        ).read_text(encoding="utf-8")
        descriptions_path = (
            ELECTRICAL_COMMANDS_ROOT
            / "AutoCADCommands"
            / "GeneralCommands"
            / "GeneralCommands_descriptions.json"
        )
        descriptions = json.loads(descriptions_path.read_text(encoding="utf-8"))

        self.assertIn('[CommandMethod("CHECKLIST", CommandFlags.Session)]', command_file)
        self.assertIn('[CommandMethod("CHECKLISTS", CommandFlags.Session)]', command_file)
        self.assertIn('[CommandMethod("PROJECTCHECKLIST", CommandFlags.Session)]', command_file)
        self.assertIn('[CommandMethod("PCL", CommandFlags.Session)]', command_file)
        self.assertIn("CHECKLIST", descriptions["commands"])
        self.assertIn("CHECKLISTS", descriptions["commands"])
        self.assertIn("PROJECTCHECKLIST", descriptions["commands"])
        self.assertIn("PCL", descriptions["commands"])

    def test_autocad_store_uses_folder_scoped_json_storage(self):
        store_file = (
            ELECTRICAL_COMMANDS_ROOT
            / "AutoCADCommands"
            / "GeneralCommands"
            / "ProjectChecklistStore.cs"
        ).read_text(encoding="utf-8")

        self.assertIn('checklist_state.json', store_file)
        self.assertIn('LoadFolderState', store_file)
        self.assertIn('SaveFolderState', store_file)
        self.assertIn('LoadAllChecklists', store_file)
        self.assertIn('GetBuiltInChecklists', store_file)
        self.assertIn('LastActiveChecklistId', store_file)
        self.assertIn('Pre-flight Electrical Checklist', store_file)
        self.assertIn('Electrical General Checklist', store_file)

    def test_autocad_wpf_window_implements_interactive_ui(self):
        xaml_file = (
            ELECTRICAL_COMMANDS_ROOT
            / "AutoCADCommands"
            / "GeneralCommands"
            / "ProjectChecklistWindow.xaml"
        ).read_text(encoding="utf-8")
        cs_file = (
            ELECTRICAL_COMMANDS_ROOT
            / "AutoCADCommands"
            / "GeneralCommands"
            / "ProjectChecklistWindow.xaml.cs"
        ).read_text(encoding="utf-8")

        self.assertIn('x:Class="ElectricalCommands.ProjectChecklistWindow"', xaml_file)
        self.assertIn('ChecklistComboBox', xaml_file)
        self.assertIn('SearchTextBox', xaml_file)
        self.assertIn('HideCompletedCheckBox', xaml_file)
        self.assertIn('ChecklistProgressBar', xaml_file)
        self.assertIn('ResetChecklistButton', xaml_file)
        self.assertIn('SaveStateToDisk()', cs_file)
        self.assertIn('ProjectChecklistStore.SaveFolderState', cs_file)
        self.assertIn('SwitchFolderOrDrawing', cs_file)
        self.assertIn('_state.LastActiveChecklistId', cs_file)


if __name__ == "__main__":
    unittest.main()
