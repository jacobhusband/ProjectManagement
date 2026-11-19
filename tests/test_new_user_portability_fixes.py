"""Regression tests for bugs that affected new users on clean Windows installs."""

import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import clean_drawings
import database
import main as main_module
import panel_schedule_sync as pss

REPO_ROOT = Path(__file__).resolve().parents[1]


class PackagingAndBundleTests(unittest.TestCase):
    def test_both_pyinstaller_specs_bundle_title24_and_clean_cad_worker(self):
        build_spec = (REPO_ROOT / "build-config" / "ACIES Scheduler.spec").read_text(encoding="utf-8")
        root_spec = (REPO_ROOT / "ACIES Scheduler.spec").read_text(encoding="utf-8")
        build_ps1 = (REPO_ROOT / "build-config" / "build.ps1").read_text(encoding="utf-8")

        self.assertIn("'title24'", build_spec)
        self.assertIn("title24", root_spec)
        self.assertIn("CleanCAD-bin", root_spec)
        self.assertIn("ACIES_BUILD_ENV_FILE", root_spec)
        self.assertIn(r"assets\title24\energycodeace.indoor.page1.options.json", build_ps1)

    def test_wire_sizer_has_no_render_blocking_google_fonts(self):
        src_html = (REPO_ROOT / "WireSizerApplication" / "index.html").read_text(encoding="utf-8")
        dist_html = (REPO_ROOT / "WireSizerApplication" / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis.com", src_html)
        self.assertNotIn("fonts.googleapis.com", dist_html)


class ComAndExcelFallbackTests(unittest.TestCase):
    def test_word_com_initializes_and_uninitializes_com(self):
        events = []
        fake_pythoncom = MagicMock()
        fake_pythoncom.CoInitialize.side_effect = lambda: events.append("init")
        fake_pythoncom.CoUninitialize.side_effect = lambda: events.append("uninit")

        fake_doc = MagicMock()
        fake_word = MagicMock()
        fake_word.Documents.Open.return_value = fake_doc
        fake_win32 = MagicMock()
        fake_win32.client.DispatchEx.return_value = fake_word

        with patch.dict(sys.modules, {
            "pythoncom": fake_pythoncom,
            "win32com": fake_win32,
            "win32com.client": fake_win32.client,
        }):
            main_module._update_word_file_via_com("sample.doc", {"*a*": "b"})

        self.assertEqual(["init", "uninit"], events)
        fake_doc.Save.assert_called_once()
        fake_doc.Close.assert_called_once_with(False)
        fake_word.Quit.assert_called_once()

    def test_excel_conversion_initializes_and_uninitializes_com(self):
        events = []
        fake_pythoncom = MagicMock()
        fake_pythoncom.CoInitialize.side_effect = lambda: events.append("init")
        fake_pythoncom.CoUninitialize.side_effect = lambda: events.append("uninit")

        fake_wb = MagicMock()
        fake_excel = MagicMock()
        fake_excel.Workbooks.Open.return_value = fake_wb
        fake_win32 = MagicMock()
        fake_win32.client.DispatchEx.return_value = fake_excel

        api = main_module.Api.__new__(main_module.Api)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.xlsx"
            dst = Path(tmp) / "out.xls"
            src.write_bytes(b"dummy")
            with patch.dict(sys.modules, {
                "pythoncom": fake_pythoncom,
                "win32com": fake_win32,
                "win32com.client": fake_win32.client,
            }):
                api._convert_excel_workbook(str(src), str(dst), ".xls")

        self.assertEqual(["init", "uninit"], events)
        fake_wb.SaveAs.assert_called_once()
        fake_excel.Quit.assert_called_once()

    def test_panel_schedule_sync_xlsx_falls_back_to_openpyxl_when_excel_unavailable(self):
        with patch.object(pss, "_write_with_excel", side_effect=pss.ExcelUnavailableError("no excel")), \
             patch.object(pss, "_write_with_openpyxl") as openpyxl_write, \
             patch.object(pss.os, "name", "nt"):
            pss._write_workbook("panel.xlsx", [{"sheetName": "P1", "address": "A1", "value": "X"}], prefer_com=True)
        openpyxl_write.assert_called_once()

    def test_panel_schedule_sync_xlsx_still_raises_when_locked_in_excel(self):
        with patch.object(pss, "_write_with_excel", side_effect=pss.PanelScheduleSyncError("locked")), \
             patch.object(pss, "_write_with_openpyxl") as openpyxl_write, \
             patch.object(pss.os, "name", "nt"):
            with self.assertRaisesRegex(pss.PanelScheduleSyncError, "locked"):
                pss._write_workbook("panel.xlsx", [{"sheetName": "P1", "address": "A1", "value": "X"}], prefer_com=True)
        openpyxl_write.assert_not_called()

    def test_conflict_highlight_xlsx_falls_back_to_openpyxl_when_excel_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            wb = Path(tmp) / "panel.xlsx"
            wb.write_bytes(b"stub")
            with patch.object(pss, "_highlight_with_excel", side_effect=pss.ExcelUnavailableError("no excel")), \
                 patch.object(pss, "_highlight_with_openpyxl") as openpyxl_hi, \
                 patch.object(pss.os, "name", "nt"):
                out = pss.create_highlighted_conflict_copy(str(wb), [{"worksheetName": "P1", "address": "A1"}], prefer_com=True)
            self.assertTrue(Path(out).is_file())
            openpyxl_hi.assert_called_once()


class ApiKeyAndBackendResilienceTests(unittest.TestCase):
    def test_resolve_google_ai_api_key_reads_user_settings_without_env_key(self):
        api = main_module.Api.__new__(main_module.Api)
        with patch.object(api, "get_user_settings", return_value={"apiKey": "user-settings-key"}), \
             patch.dict(os.environ, {"GOOGLE_API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
            self.assertEqual("user-settings-key", api._resolve_google_ai_api_key(""))

    def test_run_clean_drawings_stops_early_when_plot_style_table_is_missing(self):
        api = main_module.Api.__new__(main_module.Api)
        with patch.object(api, "get_user_settings", return_value={"autocadPath": r"C:\Autodesk\AutoCAD 2025\accoreconsole.exe"}), \
             patch.object(api, "_resolve_workroom_context", return_value={"project_path": r"C:\Proj"}), \
             patch.object(api, "_plot_style_problem", return_value="Missing 510-monochrome.ctb"), \
             patch.object(api, "_notify_tool_status") as notify_mock, \
             patch.object(clean_drawings, "run") as run_mock:
            res = api.run_clean_drawings({"titleblock": "x.dwg", "drawings": ["a.dwg"]}, activity_id="act-clean")
        self.assertEqual("error", res["status"])
        self.assertIn("510-monochrome.ctb", res["message"])
        notify_mock.assert_called_once()
        run_mock.assert_not_called()

    def test_clean_drawings_plugin_for_uses_pe_major_version_on_custom_install_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            acad = base / "CustomCadFolder" / "accoreconsole.exe"
            acad.parent.mkdir(parents=True)
            acad.write_bytes(b"")
            bundled = base / "CleanCAD-bin"
            dll_25 = bundled / "net8.0-windows" / clean_drawings.WORKER_DLL
            dll_25.parent.mkdir(parents=True)
            dll_25.write_bytes(b"dll")
            dll_24 = bundled / "net48" / clean_drawings.WORKER_DLL
            dll_24.parent.mkdir(parents=True)
            dll_24.write_bytes(b"dll")

            with patch.object(clean_drawings, "BUNDLED_WORKER_DIR", bundled):
                with patch.object(clean_drawings, "_pe_major_version", return_value=25):
                    self.assertEqual(dll_25, clean_drawings.plugin_for(acad))
                with patch.object(clean_drawings, "_pe_major_version", return_value=24):
                    self.assertEqual(dll_24, clean_drawings.plugin_for(acad))

    def test_database_read_and_delete_helpers_succeed_on_fresh_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "fresh.db")
            self.assertIsNone(database.get_project("250001", db_path))
            self.assertIsNone(database.get_panel_schedule("panel-1", db_path))
            self.assertFalse(database.delete_panel_schedule("panel-1", db_path))

    def test_export_timesheet_succeeds_when_startfile_fails_without_excel(self):
        api = main_module.Api.__new__(main_module.Api)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.xlsx"
            with patch.object(main_module.os, "startfile", side_effect=OSError(1155, "No association"), create=True):
                res = api.export_timesheet_excel({
                    "weekKey": "2026-11-16",
                    "userName": "Alex Engineer",
                    "filePath": str(out_path),
                    "entries": [],
                    "expenses": {"projects": []},
                })
            self.assertEqual("success", res["status"])
            self.assertTrue(out_path.is_file())


class CadAndPdfScriptPortabilityTests(unittest.TestCase):
    def test_remove_xref_paths_uses_multi_target_dll_and_no_utf8_bom_for_prepare_scr(self):
        text = (REPO_ROOT / "scripts" / "removeXREFPaths.ps1").read_text(encoding="utf-8")
        self.assertIn(r'PrepareXrefs-bin\$acadFramework\PrepareXrefs.dll', text)
        self.assertNotIn("Set-Content -LiteralPath $prepareScript -Encoding UTF8", text)
        self.assertIn("[IO.File]::WriteAllText($prepareScript,", text)
        self.assertIn("Show-FormWindow $owner", text)
        self.assertIn("Add-Type -AssemblyName System.Drawing", text)

    def test_plot_dwgs_hardens_python_discovery_paths_and_temp_cwd(self):
        text = (REPO_ROOT / "scripts" / "PlotDWGs.ps1").read_text(encoding="utf-8")
        self.assertIn("acies-pdf-tools.exe", text)
        self.assertIn(r"*\Microsoft\WindowsApps\*", text)
        self.assertIn("Push-Location -LiteralPath $env:TEMP", text)
        self.assertNotIn("Tee-Object -FilePath $LogFile", text)
        self.assertNotIn("| Out-File $logFile", text)
        self.assertIn('(if (/= 0 (getvar "DBMOD")) (command "_.QUIT" "_Y") (command "_.QUIT"))', text)

    def test_merge_pdfs_exits_nonzero_when_no_pages_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.pdf"
            missing = Path(tmp) / "missing.pdf"
            res = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "merge_pdfs.py"), str(out), str(missing)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(0, res.returncode)
            self.assertFalse(out.exists())

    def test_detect_pdf_size_falls_back_when_projects_folder_is_shallow(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        try:
            import detect_pdf_size
            with tempfile.TemporaryDirectory() as tmp:
                dwg = Path(tmp) / "Projects" / "250421 Job" / "Electrical" / "E01.dwg"
                dwg.parent.mkdir(parents=True)
                dwg.write_bytes(b"")
                root = detect_pdf_size.get_project_root(str(dwg))
                self.assertEqual(str(Path(tmp) / "Projects" / "250421 Job"), root)
        finally:
            sys.path.pop(0)


class FrontendPortabilityTests(unittest.TestCase):
    def test_script_js_waits_for_pywebview_api_methods_and_fixes_prereq_and_autocad_browse(self):
        import re
        js = (REPO_ROOT / "script.js").read_text(encoding="utf-8")
        self.assertIn('typeof window.pywebview?.api?.get_user_settings !== "function"', js)
        self.assertNotIn("updateCleanDwgToolState()", js)
        self.assertIsNone(re.search(r'(?<!default_)directory:\s*"C:\\\\Program Files\\\\Autodesk"', js))
        self.assertIn('default_directory: "C:\\\\Program Files\\\\Autodesk"', js)

    def test_industry_shell_hides_unknown_version_for_uninstalled_plugins(self):
        js = (REPO_ROOT / "industry-shell.js").read_text(encoding="utf-8")
        self.assertIn('bundle.local_version !== "unknown"', js)


if __name__ == "__main__":
    unittest.main()
