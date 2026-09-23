import base64
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as main_module
from main import Api

# 1x1 PNG
_PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_PNG_DATA_URL = "data:image/png;base64," + _PNG_1X1_B64


class PageAssetBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def _patched_data_path(self, temp_dir):
        return patch.object(
            main_module,
            "get_app_data_path",
            lambda name="tasks.json": str(Path(temp_dir) / name),
        )

    def test_save_and_get_page_asset_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-assets-") as temp_dir:
            with self._patched_data_path(temp_dir):
                saved = self.api.save_page_asset("proj_260243", _PNG_DATA_URL, "shot.png")
                self.assertEqual("success", saved["status"])
                asset_path = saved["assetPath"]
                self.assertTrue(asset_path.startswith("page_assets/proj_260243/"))

                # File actually landed inside page_assets/<owner>/
                on_disk = Path(temp_dir) / "page_assets" / "proj_260243"
                files = list(on_disk.glob("*.png"))
                self.assertEqual(1, len(files))

                preview = self.api.get_page_asset(asset_path)
                self.assertEqual("success", preview["status"])
                self.assertTrue(preview["dataUrl"].startswith("data:image/png;base64,"))

    def test_owner_key_is_sanitized(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-assets-owner-") as temp_dir:
            with self._patched_data_path(temp_dir):
                saved = self.api.save_page_asset("proj_260243/../secret", _PNG_DATA_URL, "x.png")
                self.assertEqual("success", saved["status"])
                self.assertNotIn("..", saved["assetPath"])
                # All asset files must remain under page_assets/
                root = Path(temp_dir) / "page_assets"
                for path in root.rglob("*.png"):
                    self.assertIn(str(root.resolve()), str(path.resolve()))

    def test_get_page_asset_rejects_traversal(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-assets-traversal-") as temp_dir:
            # A real file OUTSIDE the page_assets sandbox.
            secret = Path(temp_dir) / "secret.png"
            secret.write_bytes(base64.b64decode(_PNG_1X1_B64))
            with self._patched_data_path(temp_dir):
                for bad in ["../secret.png", "page_assets/../../secret.png", "..\\secret.png"]:
                    result = self.api.get_page_asset(bad)
                    self.assertNotEqual(
                        "success", result.get("status"),
                        msg=f"Traversal path should not resolve: {bad}",
                    )

    def test_get_page_asset_missing_file(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-assets-missing-") as temp_dir:
            with self._patched_data_path(temp_dir):
                result = self.api.get_page_asset("page_assets/proj_x/does-not-exist.png")
                self.assertEqual("error", result["status"])

    def test_save_page_asset_rejects_non_data_url(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-assets-bad-") as temp_dir:
            with self._patched_data_path(temp_dir):
                result = self.api.save_page_asset("proj_x", "not-a-data-url", "x.png")
                self.assertEqual("error", result["status"])

    def test_lighting_schedule_normalization_preserves_symbol_metadata(self):
        payload = {
            "rows": [{
                "mark": "L1",
                "description": "Recessed light",
                "symbolAssetPath": "page_assets/lighting_260243/symbol.png",
                "symbolAlt": "Recessed light symbol",
                "starterFixtureKey": "ca-2025-res-l1",
            }],
            "generalNotes": "Residential notes",
            "notes": "Fixture notes",
            "includeSymbolColumn": True,
        }
        normalized = main_module._normalize_lighting_schedule_payload(payload)
        row = normalized["rows"][0]
        self.assertEqual("L1", row["mark"])
        self.assertEqual(
            "page_assets/lighting_260243/symbol.png",
            row["symbolAssetPath"],
        )
        self.assertEqual("Recessed light symbol", row["symbolAlt"])
        self.assertEqual("ca-2025-res-l1", row["starterFixtureKey"])
        self.assertTrue(normalized["includeSymbolColumn"])

    def test_legacy_lighting_schedule_rows_gain_empty_symbol_metadata(self):
        normalized = main_module._normalize_lighting_schedule_payload({
            "rows": [{"mark": "A", "description": "Legacy fixture"}],
        })
        row = normalized["rows"][0]
        self.assertEqual("", row["symbolAssetPath"])
        self.assertEqual("", row["symbolAlt"])
        self.assertEqual("", row["starterFixtureKey"])
        self.assertFalse(normalized["includeSymbolColumn"])

    def test_lighting_schedule_symbol_row_forces_symbol_column(self):
        normalized = main_module._normalize_lighting_schedule_payload({
            "rows": [
                {"mark": "A", "description": "Plain fixture"},
                {
                    "mark": "B",
                    "description": "Pasted symbol fixture",
                    "symbolAssetPath": "page_assets/lighting_260243/symbol.png",
                },
            ],
        })
        self.assertTrue(normalized["includeSymbolColumn"])

    def test_lighting_schedule_starter_row_forces_symbol_column(self):
        normalized = main_module._normalize_lighting_schedule_payload({
            "rows": [{
                "mark": "L1",
                "description": "Starter fixture",
                "starterFixtureKey": "ca-2025-res-l1",
            }],
            "includeSymbolColumn": False,
        })
        self.assertTrue(normalized["includeSymbolColumn"])

    def test_autocad_pascal_case_schedule_restores_starter_symbol_metadata(self):
        normalized = main_module._normalize_lighting_schedule_payload({
            "Rows": [{
                "Mark": "L4",
                "Description": "4-inch adjustable LED spotlight",
                "ModelNumber": "WF4 ADJ SWW5 90CRI MW M6",
            }],
            "GeneralNotes": "Residential notes",
            "Notes": "Fixture notes",
            "IncludeSymbolColumn": True,
        })
        row = normalized["rows"][0]
        self.assertEqual("L4", row["mark"])
        self.assertEqual("ca-2025-res-l4", row["starterFixtureKey"])
        self.assertEqual(
            "assets/lighting/ca-residential-l4.png",
            row["symbolAssetPath"],
        )
        self.assertTrue(normalized["includeSymbolColumn"])


if __name__ == "__main__":
    unittest.main()
