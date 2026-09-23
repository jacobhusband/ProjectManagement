"""CAD scripts get argument lists, and the file lists handed to them do not pile up."""
import json
import os
import sys
import tempfile
import time
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


_ensure_google_genai_stub()
_ensure_webview_stub()
_ensure_dotenv_stub()

import main as main_module
from main import Api


class CadHandoffFileTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self._temp = tempfile.TemporaryDirectory(prefix="acies-cad-handoff-")
        gettempdir = patch.object(main_module.tempfile, "gettempdir", return_value=self._temp.name)
        gettempdir.start()
        self.addCleanup(gettempdir.stop)
        self.addCleanup(self._temp.cleanup)
        self.handoff_dir = Path(self._temp.name) / main_module.CAD_HANDOFF_DIRNAME

    def test_file_lists_and_manifests_go_to_the_handoff_folder(self):
        dwg = Path(self._temp.name) / "E01.00.dwg"
        dwg.write_text("dwg", encoding="utf-8")

        list_path = Path(self.api._write_files_list_temp([str(dwg)]))
        with patch.object(Api, "_normalize_dwg_file_sources", return_value=[{"path": str(dwg)}]):
            manifest_path = Path(self.api._write_dwg_source_manifest_temp([{"path": str(dwg)}]))

        self.assertEqual(self.handoff_dir, list_path.parent)
        self.assertEqual(self.handoff_dir, manifest_path.parent)
        self.assertEqual(str(dwg) + "\n", list_path.read_text(encoding="utf-8"))
        self.assertEqual([{"path": str(dwg)}], json.loads(manifest_path.read_text(encoding="utf-8")))

    def test_stale_handoff_files_are_pruned_and_recent_ones_kept(self):
        self.handoff_dir.mkdir(parents=True)
        stale = self.handoff_dir / "dwg-list-old.txt"
        recent = self.handoff_dir / "dwg-list-recent.txt"
        stale.write_text("old", encoding="utf-8")
        recent.write_text("recent", encoding="utf-8")
        old_time = time.time() - main_module.CAD_HANDOFF_MAX_AGE_SECONDS - 60
        os.utime(stale, (old_time, old_time))

        self.api._write_files_list_temp([r"C:\Projects\E02.00.dwg"])

        self.assertFalse(stale.exists())
        self.assertTrue(recent.exists())

    def test_script_runner_refuses_shell_string_commands(self):
        with self.assertRaises(TypeError):
            self.api._run_script_with_progress('powershell.exe -File "x.ps1" & calc', "toolPublishDwgs")


if __name__ == "__main__":
    unittest.main()
