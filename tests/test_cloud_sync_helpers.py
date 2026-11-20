import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
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


class LocalSettingsHelperTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_build_default_user_settings_omits_cloud_sync(self):
        settings = main_module.build_default_user_settings()

        self.assertNotIn("cloudSync", settings)
        self.assertEqual("Electrical", settings["activeDiscipline"])
        self.assertEqual(
            main_module.build_default_workflow_cad_defaults(),
            settings["workflowCadDefaults"],
        )
        self.assertTrue(settings["publishDwgOptions"]["stripPdfLayers"])
        self.assertTrue(settings["publishDwgOptions"]["refreshExcelOleLinks"])
        self.assertTrue(
            settings["publishDwgOptions"]["automateProjectDisciplinePublish"]
        )
        self.assertFalse(
            settings["manageLayersOptions"]["autoSelectProjectDisciplineDwgs"]
        )

    def test_sanitize_user_settings_preserves_valid_unconfigured_active_discipline(self):
        payload = main_module.build_default_user_settings()
        payload["discipline"] = ["Mechanical", "Plumbing"]
        payload["activeDiscipline"] = "Electrical"

        sanitized, changed = main_module._sanitize_user_settings_payload(payload)

        self.assertFalse(changed)
        self.assertEqual(["Mechanical", "Plumbing"], sanitized["discipline"])
        self.assertEqual("Electrical", sanitized["activeDiscipline"])

    def test_sanitize_user_settings_falls_back_for_invalid_active_discipline(self):
        payload = main_module.build_default_user_settings()
        payload["discipline"] = ["Mechanical", "Plumbing"]
        payload["activeDiscipline"] = "Architectural"

        sanitized, changed = main_module._sanitize_user_settings_payload(payload)

        self.assertTrue(changed)
        self.assertEqual(["Mechanical", "Plumbing"], sanitized["discipline"])
        self.assertEqual("Mechanical", sanitized["activeDiscipline"])

    def test_sanitize_user_settings_normalizes_workflow_cad_defaults(self):
        payload = main_module.build_default_user_settings()
        payload["workflowCadDefaults"] = {
            "manageLayersDwgSource": "manual",
            "cleanXrefsSearchZipArchives": False,
        }

        sanitized, changed = main_module._sanitize_user_settings_payload(payload)

        self.assertTrue(changed)
        self.assertEqual("manual", sanitized["workflowCadDefaults"]["manageLayersDwgSource"])
        self.assertEqual(
            "electricalXrefsToNewestArch",
            sanitized["workflowCadDefaults"]["cleanXrefsDwgSource"],
        )
        self.assertFalse(sanitized["workflowCadDefaults"]["cleanXrefsSearchZipArchives"])

    def test_sanitize_user_settings_adds_missing_publish_layer_cleanup_default(self):
        payload = main_module.build_default_user_settings()
        payload["publishDwgOptions"] = {
            "autoDetectPaperSize": False,
            "shrinkPercent": 85,
        }

        sanitized, changed = main_module._sanitize_user_settings_payload(payload)

        self.assertTrue(changed)
        self.assertFalse(sanitized["publishDwgOptions"]["autoDetectPaperSize"])
        self.assertEqual(85, sanitized["publishDwgOptions"]["shrinkPercent"])
        self.assertTrue(sanitized["publishDwgOptions"]["stripPdfLayers"])
        self.assertTrue(sanitized["publishDwgOptions"]["refreshExcelOleLinks"])
        self.assertTrue(
            sanitized["publishDwgOptions"]["automateProjectDisciplinePublish"]
        )

    def test_sanitize_user_settings_migrates_electrical_publish_automation(self):
        payload = main_module.build_default_user_settings()
        payload["publishDwgOptions"].pop("automateProjectDisciplinePublish")
        payload["publishDwgOptions"]["automateProjectElectricalPublish"] = False

        sanitized, changed = main_module._sanitize_user_settings_payload(payload)

        self.assertTrue(changed)
        self.assertFalse(
            sanitized["publishDwgOptions"]["automateProjectDisciplinePublish"]
        )
        self.assertNotIn(
            "automateProjectElectricalPublish", sanitized["publishDwgOptions"]
        )

    def test_sanitize_user_settings_adds_missing_manage_layers_auto_select_default(self):
        payload = main_module.build_default_user_settings()
        payload["manageLayersOptions"] = {"scanAllLayers": False}

        sanitized, changed = main_module._sanitize_user_settings_payload(payload)

        self.assertTrue(changed)
        self.assertFalse(sanitized["manageLayersOptions"]["scanAllLayers"])
        self.assertFalse(
            sanitized["manageLayersOptions"]["autoSelectProjectDisciplineDwgs"]
        )
        self.assertEqual([], sanitized["manageLayersOptions"]["freezePatterns"])
        self.assertEqual([], sanitized["manageLayersOptions"]["thawPatterns"])

if __name__ == "__main__":
    unittest.main()
