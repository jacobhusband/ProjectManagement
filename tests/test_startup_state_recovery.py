import json
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

import main as main_module
from main import Api


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"


class StartupStateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_get_tasks_loads_utf8_bom_prefixed_tasks_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tasks_path = Path(temp_dir) / "tasks.json"
            payload = [
                {
                    "id": "240001",
                    "name": "BOM Test Project",
                    "deliverables": [
                        {
                            "id": "dlv_1",
                            "name": "Permit Set",
                            "due": "04/03/2026",
                        }
                    ],
                }
            ]
            tasks_path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8-sig",
            )

            with patch.object(main_module, "TASKS_FILE", str(tasks_path)), patch.object(
                main_module,
                "_overlay_projects_with_lighting_schedule_records",
                side_effect=lambda tasks: tasks,
            ):
                loaded = self.api.get_tasks()

            self.assertEqual(payload, loaded)

    def test_get_tasks_loads_plain_utf8_tasks_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tasks_path = Path(temp_dir) / "tasks.json"
            payload = [
                {
                    "id": "240002",
                    "name": "Plain UTF-8 Project",
                    "deliverables": [
                        {
                            "id": "dlv_2",
                            "name": "Bid Set",
                            "due": "04/04/2026",
                        }
                    ],
                }
            ]
            tasks_path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )

            with patch.object(main_module, "TASKS_FILE", str(tasks_path)), patch.object(
                main_module,
                "_overlay_projects_with_lighting_schedule_records",
                side_effect=lambda tasks: tasks,
            ):
                loaded = self.api.get_tasks()

            self.assertEqual(payload, loaded)

    def test_get_user_settings_recovers_missing_identity_fields_from_legacy_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            user_profile = Path(temp_dir) / "User"
            documents_dir = user_profile / "Documents" / "ProjectManagementApp"
            appdata_dir = user_profile / "AppData" / "Roaming" / "ProjectManagementApp"
            documents_dir.mkdir(parents=True)
            appdata_dir.mkdir(parents=True)

            current_settings = main_module.build_default_user_settings()
            current_settings["googleAuth"] = {"email": "existing@example.com"}
            documents_settings_path = documents_dir / "settings.json"
            documents_settings_path.write_text(
                json.dumps(current_settings, indent=2),
                encoding="utf-8",
            )

            legacy_settings = {
                "userName": "Jacob Husband",
                "discipline": ["Electrical"],
                "apiKey": "AIzaSyLegacy",
                "autocadPath": r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
                "showSetupHelp": False,
                "theme": "dark",
                "defaultPmInitials": "JH",
                "lightingTemplates": [{"mark": "A1"}],
            }
            (appdata_dir / "settings.json").write_text(
                json.dumps(legacy_settings, indent=2),
                encoding="utf-8",
            )

            with patch.object(main_module, "SETTINGS_FILE", str(documents_settings_path)), patch.object(
                main_module.sys, "platform", "win32"
            ), patch.dict(
                main_module.os.environ,
                {
                    "USERPROFILE": str(user_profile),
                    "APPDATA": str(user_profile / "AppData" / "Roaming"),
                },
                clear=False,
            ):
                repaired = self.api.get_user_settings()

            self.assertEqual("Jacob Husband", repaired["userName"])
            self.assertEqual("AIzaSyLegacy", repaired["apiKey"])
            self.assertEqual(
                r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
                repaired["autocadPath"],
            )
            self.assertEqual("JH", repaired["defaultPmInitials"])
            self.assertNotIn("googleAuth", repaired)
            self.assertEqual([{"mark": "A1"}], repaired["lightingTemplates"])
            self.assertFalse(repaired["showSetupHelp"])

            saved = json.loads(documents_settings_path.read_text(encoding="utf-8"))
            self.assertEqual("Jacob Husband", saved["userName"])
            self.assertEqual("AIzaSyLegacy", saved["apiKey"])
            self.assertTrue((documents_dir / "settings.json.bak").exists())

    def test_script_only_shows_onboarding_when_no_existing_user_data(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("function hasExistingUserData() {", script)
        self.assertIn("if (Array.isArray(db) && db.length > 0) return true;", script)
        self.assertNotIn("googleAuthState", script)
        self.assertNotIn("microsoftAuthState.signedIn", script)
        self.assertIn("return !hasExistingUserData();", script)

    def test_get_user_settings_strips_legacy_account_auth_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            payload = main_module.build_default_user_settings()
            payload["microsoftAuth"] = {"accessToken": "stale-token"}
            payload["googleAuth"] = {"accessToken": "old-google-token"}
            settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            with patch.object(main_module, "SETTINGS_FILE", str(settings_path)):
                sanitized = self.api.get_user_settings()

            self.assertNotIn("microsoftAuth", sanitized)
            self.assertNotIn("googleAuth", sanitized)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertNotIn("microsoftAuth", saved)
            self.assertNotIn("googleAuth", saved)


if __name__ == "__main__":
    unittest.main()
