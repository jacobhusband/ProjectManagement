import io
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import call, patch


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


AUTO_SELECTED_FILES_LIST = r"C:\Temp\workroom-dwgs.txt"
AUTOCAD_CORE_PATH = r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe"
FALLBACK_STATUS_MESSAGE = "Workroom auto-select unavailable. Opening file picker..."

TOOL_CASES = (
    {
        "method_name": "run_publish_script",
        "tool_id": "toolPublishDwgs",
        "script_name": "PlotDWGs.ps1",
        "settings": {
            "autocadPath": AUTOCAD_CORE_PATH,
            "publishDwgOptions": {
                "automateProjectDisciplinePublish": False,
                "autoDetectPaperSize": False,
                "shrinkPercent": 85,
            },
        },
        "expected_args": (
            "-AcadCore",
            AUTOCAD_CORE_PATH,
            "-AutoDetectPaperSize",
            "0",
            "-AutoAcceptDetectedPaperSize",
            "0",
            "-ShrinkPercent",
            "85",
            "-StripPdfLayers",
            "1",
            "-RefreshExcelOleLinks",
            "1",
        ),
    },
    {
        "method_name": "run_manage_layers_script",
        "tool_id": "toolManageLayers",
        "script_name": "ManageLayersDWGs.ps1",
        "settings": {
            "autocadPath": AUTOCAD_CORE_PATH,
            "manageLayersOptions": {
                "scanAllLayers": False,
            },
        },
        "expected_args": (
            "-AcadCore",
            AUTOCAD_CORE_PATH,
            "-ScanAllLayers",
            "0",
        ),
    },
)


class WorkroomCadLaunchCommandTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.test_mode = False
        self.api._workroom_cad_file_cache = {}

    def test_cad_auto_select_trace_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="acies-cad-trace-") as temp_dir:
            trace_path = Path(temp_dir) / "cad_auto_select_trace.log"
            with patch.object(main_module, "CAD_AUTO_SELECT_TRACE_FILE", str(trace_path)):
                clear_result = self.api.clear_cad_auto_select_trace()
                self.assertEqual("success", clear_result["status"])

                frontend_result = self.api.trace_cad_auto_select_event(
                    "frontend_probe",
                    {"toolId": "toolPublishDwgs"},
                )
                self.assertEqual("success", frontend_result["status"])

                self.api._trace_cad_auto_select(
                    "backend_probe",
                    count=2,
                    file_paths=[r"C:\Projects\123456\Electrical\one.dwg"],
                )

                trace_result = self.api.get_cad_auto_select_trace(20)

            self.assertEqual("success", trace_result["status"])
            self.assertEqual(str(trace_path), trace_result["path"])
            self.assertEqual(2, trace_result["lineCount"])
            self.assertEqual("frontend_probe", trace_result["entries"][0]["event"])
            self.assertEqual("frontend", trace_result["entries"][0]["trace_source"])
            self.assertEqual("toolPublishDwgs", trace_result["entries"][0]["toolId"])
            self.assertEqual("backend_probe", trace_result["entries"][1]["event"])
            self.assertEqual(2, trace_result["entries"][1]["count"])
            self.assertEqual(
                [r"C:\Projects\123456\Electrical\one.dwg"],
                trace_result["entries"][1]["file_paths"],
            )

    def test_open_project_cad_files_only_opens_working_drawings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "123456 Test Project"
            electrical = project / "Electrical"
            electrical.mkdir(parents=True)
            (electrical / "Archive").mkdir()
            (electrical / "Archive" / "old.dwg").touch()
            (electrical / "notes.txt").touch()
            drawings = [electrical / "E01 power.dwg", electrical / "E02.DWG"]
            for drawing in drawings:
                drawing.touch()
            with patch('main.os.startfile') as startfile:
                result = self.api.open_project_cad_files({'projectPath': str(project)})
            self.assertEqual('success', result['status'])
            self.assertEqual([call(str(path)) for path in drawings], startfile.call_args_list)

    def test_open_project_cad_files_reports_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            electrical = Path(temp_dir) / 'Electrical'
            electrical.mkdir()
            for name in ('one.dwg', 'two.dwg'):
                (electrical / name).touch()
            with patch('main.os.startfile', side_effect=[OSError('No association'), None]):
                result = self.api.open_project_cad_files({'projectPath': str(electrical)})
            self.assertEqual('error', result['status'])
            self.assertEqual([str(electrical / 'two.dwg')], result['opened'])
            self.assertEqual(str(electrical / 'one.dwg'), result['failed'][0]['path'])

    def test_open_project_cad_files_requires_project_and_drawings(self):
        with patch('main.os.startfile') as startfile:
            self.assertEqual('error', self.api.open_project_cad_files()['status'])
            with tempfile.TemporaryDirectory() as temp_dir:
                context = {'projectPath': temp_dir}
                self.assertEqual('error', self.api.open_project_cad_files(context)['status'])
                (Path(temp_dir) / 'Electrical').mkdir()
                result = self.api.open_project_cad_files(context)
                self.assertIn('No DWG files', result['message'])
            startfile.assert_not_called()

    def test_script_worker_is_non_daemon_and_stops_cleanly(self):
        progress_seen = threading.Event()

        def record_status(_tool_id, message, activity_id=None):
            if message == "ready":
                progress_seen.set()

        command = [
            sys.executable,
            "-u",
            "-c",
            "import time; print('PROGRESS: ready', flush=True); time.sleep(30)",
        ]
        with patch.object(self.api, "_trace_cad_auto_select"), patch.object(
            self.api,
            "_notify_tool_status",
            side_effect=record_status,
        ):
            result = self.api._run_script_with_progress(command, "toolPublishDwgs")
            self.assertEqual("started", result["status"])
            self.assertTrue(progress_seen.wait(10), "CAD worker did not report startup progress")

            with self.api._script_worker_lock:
                workers = list(self.api._script_workers)
            self.assertEqual(1, len(workers))
            self.assertFalse(workers[0].daemon)

            self.assertTrue(self.api.stop_script_workers(timeout=10))

        with self.api._script_worker_lock:
            self.assertEqual(set(), self.api._script_workers)
            self.assertEqual(set(), self.api._script_processes)

    def test_resolve_workroom_context_accepts_snake_case_project_path(self):
        with tempfile.TemporaryDirectory(prefix="acies-context-path-") as temp_dir:
            selected_path = str(Path(temp_dir) / "260001 Example")
            result = self.api._resolve_workroom_context(
                {"discipline": ["Electrical"]},
                {
                    "source": "workroom",
                    "project_path": selected_path,
                    "discipline": "Mechanical",
                },
            )

        self.assertEqual("workroom", result["source"])
        self.assertEqual(selected_path, result["project_path"])
        self.assertEqual("Mechanical", result["discipline"])

    def test_default_directory_accepts_snake_case_project_path(self):
        with tempfile.TemporaryDirectory(prefix="acies-default-dir-") as temp_dir:
            result = self.api._resolve_launch_context_default_directory(
                {"source": "manual", "project_path": temp_dir}
            )

        self.assertEqual(str(Path(temp_dir)), result)

    def test_app_cad_picker_writes_valid_dwg_list_for_hidden_script(self):
        with tempfile.TemporaryDirectory(prefix="acies-app-cad-picker-") as temp_dir:
            temp_path = Path(temp_dir)
            first_dwg = temp_path / "E001.dwg"
            second_dwg = temp_path / "E002.DWG"
            ignored_file = temp_path / "notes.txt"
            for path in (first_dwg, second_dwg, ignored_file):
                path.write_text("", encoding="utf-8")

            with patch.object(
                self.api,
                "select_files",
                return_value={
                    "status": "success",
                    "paths": [str(first_dwg), str(ignored_file), str(second_dwg)],
                },
            ) as picker_mock:
                result = self.api._select_cad_files_in_app(temp_dir)

            self.assertEqual("success", result["status"])
            self.assertEqual(2, result["selection"]["count"])
            picker_mock.assert_called_once_with({
                "allow_multiple": True,
                "file_types": ["Drawing Files (*.dwg)", "All Files (*.*)"],
                "default_directory": temp_dir,
            })
            files_list_path = Path(result["selection"]["files_list_path"])
            try:
                self.assertEqual(
                    [str(first_dwg), str(second_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)

    def _run_tool(self, case, auto_selection, auto_select_enabled=True):
        captured = []
        with patch.object(self.api, "get_user_settings", return_value=case["settings"]), patch.object(
            self.api,
            "_resolve_workroom_auto_file_selection",
            return_value=auto_selection,
        ), patch.object(
            self.api,
            "_is_workroom_auto_select_enabled",
            return_value=auto_select_enabled,
        ), patch.object(
            self.api,
            "_resolve_workroom_context",
            return_value={
                "source": "workroom",
                "project_path": r"C:\Projects\123456\Sheets",
                "discipline": "Electrical",
                "discipline_source": "launch_context",
            },
        ), patch.object(
            self.api,
            "_run_script_with_progress",
            side_effect=lambda command, tool_id, **kwargs: captured.append((command, tool_id, kwargs)),
        ), patch.object(
            self.api,
            "_select_cad_files_in_app",
            return_value={
                "status": "success",
                "selection": {
                    "files_list_path": AUTO_SELECTED_FILES_LIST,
                    "count": 2,
                    "resolution_mode": "app_file_picker",
                },
            },
        ), patch.object(self.api, "_notify_tool_status") as notify_mock:
            result = getattr(self.api, case["method_name"])({"source": "workroom"})
        return result, captured, notify_mock

    def test_workroom_cad_tools_pass_files_list_path_as_explicit_argv(self):
        auto_selection = {"files_list_path": AUTO_SELECTED_FILES_LIST}

        for case in TOOL_CASES:
            with self.subTest(method=case["method_name"]):
                result, captured, notify_mock = self._run_tool(case, auto_selection)

                self.assertEqual("success", result["status"])
                self.assertEqual("", result["activityId"])
                self.assertEqual(1, len(captured))

                command, tool_id, kwargs = captured[0]
                self.assertEqual(case["tool_id"], tool_id)
                self.assertEqual({"activity_id": None}, kwargs)
                self.assertIsInstance(command, list)
                self.assertGreaterEqual(len(command), 7)
                self.assertEqual("powershell.exe", command[0])
                self.assertEqual("-NoProfile", command[1])
                self.assertEqual("-ExecutionPolicy", command[2])
                self.assertEqual("Bypass", command[3])
                self.assertEqual("-File", command[4])
                self.assertTrue(command[5].endswith(case["script_name"]))

                for expected_arg in case["expected_args"]:
                    self.assertIn(expected_arg, command)

                files_list_index = command.index("-FilesListPath")
                self.assertEqual(AUTO_SELECTED_FILES_LIST, command[files_list_index + 1])
                notify_mock.assert_not_called()

    def test_workflow_blocking_manage_layers_passes_wait_true(self):
        manage_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_manage_layers_script"
        )
        captured = []
        with patch.object(self.api, "get_user_settings", return_value=manage_case["settings"]), \
                patch.object(self.api, "_resolve_workroom_auto_file_selection",
                             return_value={"files_list_path": AUTO_SELECTED_FILES_LIST, "count": 1}), \
                patch.object(
                    self.api,
                    "_run_script_with_progress",
                    side_effect=lambda command, tool_id, **kwargs: captured.append((command, tool_id, kwargs))
                    or {"status": "success"},
                ):
            result = self.api.run_manage_layers_script(
                {"source": "workroom", "workflowBlocking": True}
            )

        self.assertEqual("success", result["status"])
        self.assertEqual(1, len(captured))
        self.assertEqual("toolManageLayers", captured[0][1])
        self.assertTrue(captured[0][2]["wait"])

    def test_workflow_selected_dwg_files_bypass_manual_picker_when_auto_select_disabled(self):
        manage_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_manage_layers_script"
        )
        with tempfile.TemporaryDirectory(prefix="acies-workflow-dwgs-") as temp_dir:
            dwg_path = Path(temp_dir) / "E001.dwg"
            dwg_path.write_text("", encoding="utf-8")
            captured = []
            with patch.object(self.api, "get_user_settings", return_value=manage_case["settings"]), \
                    patch.object(
                        self.api,
                        "_run_script_with_progress",
                        side_effect=lambda command, tool_id, **kwargs: captured.append((command, tool_id, kwargs))
                        or {"status": "success"},
                    ), patch.object(self.api, "_notify_tool_status") as notify_mock:
                result = self.api.run_manage_layers_script({
                    "source": "manual",
                    "cadFilePaths": [str(dwg_path)],
                    "workflowPreselectedDwgFiles": True,
                })

            self.assertEqual("success", result["status"])
            self.assertEqual(1, len(captured))
            command = captured[0][0]
            self.assertIn("-FilesListPath", command)
            files_list_path = Path(command[command.index("-FilesListPath") + 1])
            try:
                self.assertEqual([str(dwg_path)], files_list_path.read_text(encoding="utf-8").splitlines())
            finally:
                files_list_path.unlink(missing_ok=True)
            notify_mock.assert_called_once_with(
                "toolManageLayers",
                "Using auto-selected DWGs (1) via workflow_preselected_files...",
                activity_id=None,
            )

    def test_workroom_cad_tools_use_app_picker_when_auto_selection_is_empty(self):
        for case in TOOL_CASES:
            with self.subTest(method=case["method_name"]):
                result, captured, notify_mock = self._run_tool(case, auto_selection=None)

                self.assertEqual("success", result["status"])
                self.assertEqual("", result["activityId"])
                self.assertEqual(1, len(captured))

                command, tool_id, kwargs = captured[0]
                self.assertEqual(case["tool_id"], tool_id)
                self.assertEqual({"activity_id": None}, kwargs)
                self.assertIsInstance(command, list)
                self.assertIn("-FilesListPath", command)
                self.assertEqual(
                    AUTO_SELECTED_FILES_LIST,
                    command[command.index("-FilesListPath") + 1],
                )

                for expected_arg in case["expected_args"]:
                    self.assertIn(expected_arg, command)

                selection_message = (
                    "Select DWG files to publish..."
                    if case["tool_id"] == "toolPublishDwgs"
                    else "Select DWG files to update..."
                )
                notify_mock.assert_has_calls([
                    call(case["tool_id"], FALLBACK_STATUS_MESSAGE, activity_id=None),
                    call(case["tool_id"], selection_message, activity_id=None),
                    call(
                        case["tool_id"],
                        "Using selected DWGs (2)...",
                        activity_id=None,
                    ),
                ])

    def test_publish_tool_can_disable_pdf_layer_cleanup(self):
        publish_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_publish_script"
        )
        settings = {
            **publish_case["settings"],
            "publishDwgOptions": {
                **publish_case["settings"]["publishDwgOptions"],
                "stripPdfLayers": False,
            },
        }
        case = {**publish_case, "settings": settings}

        result, captured, _ = self._run_tool(
            case,
            auto_selection={"files_list_path": AUTO_SELECTED_FILES_LIST},
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(1, len(captured))
        command = captured[0][0]
        strip_arg_index = command.index("-StripPdfLayers")
        self.assertEqual("0", command[strip_arg_index + 1])

    def test_publish_tool_can_disable_excel_ole_refresh(self):
        publish_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_publish_script"
        )
        settings = {
            **publish_case["settings"],
            "publishDwgOptions": {
                **publish_case["settings"]["publishDwgOptions"],
                "refreshExcelOleLinks": False,
            },
        }
        case = {**publish_case, "settings": settings}

        result, captured, _ = self._run_tool(
            case,
            auto_selection={"files_list_path": AUTO_SELECTED_FILES_LIST},
        )

        self.assertEqual("success", result["status"])
        command = captured[0][0]
        refresh_arg_index = command.index("-RefreshExcelOleLinks")
        self.assertEqual("0", command[refresh_arg_index + 1])

    def test_automatic_project_publish_uses_selected_discipline_and_accepts_detected_size(self):
        publish_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_publish_script"
        )
        settings = {
            **publish_case["settings"],
            "discipline": ["Electrical", "Mechanical", "Plumbing"],
            "activeDiscipline": "Mechanical",
            "publishDwgOptions": {
                **publish_case["settings"]["publishDwgOptions"],
                "automateProjectDisciplinePublish": True,
                "autoDetectPaperSize": True,
            },
        }
        with tempfile.TemporaryDirectory(prefix="acies-auto-publish-") as temp_dir:
            project_path = Path(temp_dir)
            discipline_path = project_path / "Mechanical"
            discipline_path.mkdir()
            first_dwg = discipline_path / "M001.dwg"
            second_dwg = discipline_path / "M002.DWG"
            for dwg_path in (first_dwg, second_dwg):
                dwg_path.write_text("", encoding="utf-8")

            captured = []
            with patch.object(self.api, "get_user_settings", return_value=settings), patch.object(
                self.api,
                "_run_script_with_progress",
                side_effect=lambda command, tool_id, **kwargs: captured.append(
                    (command, tool_id, kwargs)
                ),
            ), patch.object(
                self.api,
                "_select_cad_files_in_app",
            ) as picker_mock, patch.object(
                self.api,
                "_notify_tool_status",
            ) as notify_mock:
                result = self.api.run_publish_script({
                    "source": "projects-tab",
                    "projectPath": str(project_path),
                })

            self.assertEqual("success", result["status"])
            picker_mock.assert_not_called()
            self.assertEqual(1, len(captured))
            command = captured[0][0]
            self.assertEqual(
                "1",
                command[command.index("-AutoAcceptDetectedPaperSize") + 1],
            )
            files_list_path = Path(command[command.index("-FilesListPath") + 1])
            try:
                self.assertEqual(
                    [str(first_dwg), str(second_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)
            notify_mock.assert_any_call(
                "toolPublishDwgs",
                "Using auto-selected DWGs (2) via project_discipline_auto_publish...",
                activity_id=None,
            )

    def test_automatic_project_publish_missing_selected_discipline_notifies_and_prompts(self):
        publish_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_publish_script"
        )
        settings = {
            **publish_case["settings"],
            "discipline": ["Electrical", "Mechanical", "Plumbing"],
            "activeDiscipline": "Plumbing",
            "publishDwgOptions": {
                **publish_case["settings"]["publishDwgOptions"],
                "automateProjectDisciplinePublish": True,
                "autoDetectPaperSize": True,
            },
        }
        with tempfile.TemporaryDirectory(prefix="acies-auto-publish-missing-") as temp_dir:
            captured = []
            with patch.object(self.api, "get_user_settings", return_value=settings), patch.object(
                self.api,
                "_run_script_with_progress",
                side_effect=lambda command, tool_id, **kwargs: captured.append(
                    (command, tool_id, kwargs)
                ),
            ), patch.object(
                self.api,
                "_select_cad_files_in_app",
                return_value={
                    "status": "success",
                    "selection": {
                        "files_list_path": AUTO_SELECTED_FILES_LIST,
                        "count": 1,
                        "resolution_mode": "app_file_picker",
                    },
                },
            ) as picker_mock, patch.object(
                self.api,
                "_notify_tool_status",
            ) as notify_mock:
                result = self.api.run_publish_script({
                    "source": "projects-tab",
                    "projectPath": temp_dir,
                })

            self.assertEqual("success", result["status"])
            picker_mock.assert_called_once_with(str(Path(temp_dir)))
            command = captured[0][0]
            self.assertEqual(
                "0",
                command[command.index("-AutoAcceptDetectedPaperSize") + 1],
            )
            fallback_messages = [
                args[1]
                for args, _kwargs in notify_mock.call_args_list
                if len(args) > 1
            ]
            self.assertTrue(any(
                "could not find the Plumbing folder" in message
                and "Select the DWG files manually" in message
                for message in fallback_messages
            ))

    def test_automatic_project_manage_layers_uses_active_discipline_dwgs(self):
        manage_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_manage_layers_script"
        )
        settings = {
            **manage_case["settings"],
            "discipline": ["Electrical", "Mechanical", "Plumbing"],
            "activeDiscipline": "Plumbing",
            "manageLayersOptions": {
                **manage_case["settings"]["manageLayersOptions"],
                "autoSelectProjectDisciplineDwgs": True,
            },
        }
        with tempfile.TemporaryDirectory(prefix="acies-auto-manage-layers-") as temp_dir:
            project_path = Path(temp_dir)
            discipline_path = project_path / "Plumbing"
            discipline_path.mkdir()
            first_dwg = discipline_path / "P001.dwg"
            second_dwg = discipline_path / "P002.DWG"
            for dwg_path in (first_dwg, second_dwg):
                dwg_path.write_text("", encoding="utf-8")

            captured = []
            with patch.object(self.api, "get_user_settings", return_value=settings), patch.object(
                self.api,
                "_run_script_with_progress",
                side_effect=lambda command, tool_id, **kwargs: captured.append(
                    (command, tool_id, kwargs)
                ),
            ), patch.object(
                self.api,
                "_select_cad_files_in_app",
            ) as picker_mock, patch.object(
                self.api,
                "_notify_tool_status",
            ) as notify_mock:
                result = self.api.run_manage_layers_script({
                    "source": "projects-tab",
                    "projectPath": str(project_path),
                })

            self.assertEqual("success", result["status"])
            picker_mock.assert_not_called()
            self.assertEqual(1, len(captured))
            command = captured[0][0]
            files_list_path = Path(command[command.index("-FilesListPath") + 1])
            try:
                self.assertEqual(
                    [str(first_dwg), str(second_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)
            notify_mock.assert_any_call(
                "toolManageLayers",
                "Using auto-selected DWGs (2) via project_discipline_auto_manage_layers...",
                activity_id=None,
            )

    def test_automatic_project_manage_layers_missing_folder_prompts_for_files(self):
        manage_case = next(
            case for case in TOOL_CASES if case["method_name"] == "run_manage_layers_script"
        )
        settings = {
            **manage_case["settings"],
            "activeDiscipline": "Mechanical",
            "manageLayersOptions": {
                **manage_case["settings"]["manageLayersOptions"],
                "autoSelectProjectDisciplineDwgs": True,
            },
        }
        with tempfile.TemporaryDirectory(prefix="acies-auto-manage-layers-missing-") as temp_dir:
            captured = []
            with patch.object(self.api, "get_user_settings", return_value=settings), patch.object(
                self.api,
                "_run_script_with_progress",
                side_effect=lambda command, tool_id, **kwargs: captured.append(
                    (command, tool_id, kwargs)
                ),
            ), patch.object(
                self.api,
                "_select_cad_files_in_app",
                return_value={
                    "status": "success",
                    "selection": {
                        "files_list_path": AUTO_SELECTED_FILES_LIST,
                        "count": 1,
                        "resolution_mode": "app_file_picker",
                    },
                },
            ) as picker_mock, patch.object(
                self.api,
                "_notify_tool_status",
            ) as notify_mock:
                result = self.api.run_manage_layers_script({
                    "source": "projects-tab",
                    "projectPath": temp_dir,
                })

            self.assertEqual("success", result["status"])
            picker_mock.assert_called_once_with(str(Path(temp_dir)))
            self.assertEqual(1, len(captured))
            fallback_messages = [
                args[1]
                for args, _kwargs in notify_mock.call_args_list
                if len(args) > 1
            ]
            self.assertTrue(any(
                "could not find the Mechanical folder" in message
                and "Select the DWG files manually" in message
                for message in fallback_messages
            ))

    def test_automatic_project_publish_prefers_workroom_discipline_context(self):
        with tempfile.TemporaryDirectory(prefix="acies-auto-publish-workroom-") as temp_dir:
            discipline_path = Path(temp_dir) / "Plumbing"
            discipline_path.mkdir()
            dwg_path = discipline_path / "P001.dwg"
            dwg_path.write_text("", encoding="utf-8")

            result = self.api._resolve_project_discipline_publish_selection(
                {
                    "discipline": ["Electrical", "Mechanical", "Plumbing"],
                    "activeDiscipline": "Mechanical",
                },
                {
                    "source": "workroom",
                    "projectPath": temp_dir,
                    "discipline": "Plumbing",
                },
            )

            self.assertEqual("success", result["status"])
            self.assertEqual("Plumbing", result["discipline"])
            self.assertEqual("Plumbing", result["selection"]["discipline"])
            self.assertEqual(
                "project_discipline_auto_publish",
                result["selection"]["resolution_mode"],
            )
            files_list_path = Path(result["selection"]["files_list_path"])
            try:
                self.assertEqual(
                    [str(dwg_path)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)

    def test_projects_tab_cad_tools_use_app_picker_with_project_directory(self):
        default_directory = r"C:\Projects\260243 BofA - Eastport Plaza"

        for case in TOOL_CASES:
            with self.subTest(method=case["method_name"]):
                captured = []
                with patch.object(self.api, "get_user_settings", return_value=case["settings"]), patch.object(
                    self.api,
                    "_resolve_workroom_auto_file_selection",
                    return_value=None,
                ), patch.object(
                    self.api,
                    "_is_workroom_auto_select_enabled",
                    return_value=False,
                ), patch.object(
                    self.api,
                    "_resolve_launch_context_default_directory",
                    return_value=default_directory,
                ), patch.object(
                    self.api,
                    "_run_script_with_progress",
                    side_effect=lambda command, tool_id, **kwargs: captured.append((command, tool_id, kwargs)),
                ), patch.object(
                    self.api,
                    "_select_cad_files_in_app",
                    return_value={
                        "status": "success",
                        "selection": {
                            "files_list_path": AUTO_SELECTED_FILES_LIST,
                            "count": 1,
                            "resolution_mode": "app_file_picker",
                        },
                    },
                ) as picker_mock, patch.object(
                    self.api,
                    "_notify_tool_status",
                ):
                    result = getattr(self.api, case["method_name"])(
                        {"source": "projects-tab", "projectPath": default_directory}
                    )

                self.assertEqual("success", result["status"])
                self.assertEqual("", result["activityId"])
                self.assertEqual(1, len(captured))

                command, tool_id, kwargs = captured[0]
                self.assertEqual(case["tool_id"], tool_id)
                self.assertEqual({"activity_id": None}, kwargs)
                self.assertIsInstance(command, list)
                self.assertIn("-FilesListPath", command)
                self.assertEqual(
                    AUTO_SELECTED_FILES_LIST,
                    command[command.index("-FilesListPath") + 1],
                )
                self.assertNotIn("-DefaultDirectory", command)
                picker_mock.assert_called_once_with(default_directory)

                for expected_arg in case["expected_args"]:
                    self.assertIn(expected_arg, command)

    def test_resolve_workroom_auto_file_selection_prefers_explicit_launch_context_paths(self):
        with tempfile.TemporaryDirectory(prefix="acies-workroom-cad-") as temp_dir:
            temp_path = Path(temp_dir)
            first_dwg = temp_path / "first.dwg"
            second_dwg = temp_path / "second.dwg"
            invalid_txt = temp_path / "ignore.txt"
            missing_dwg = temp_path / "missing.dwg"
            first_dwg.write_text("", encoding="utf-8")
            second_dwg.write_text("", encoding="utf-8")
            invalid_txt.write_text("", encoding="utf-8")

            launch_context = {
                "source": "workroom",
                "cadFilePaths": [
                    str(first_dwg),
                    "",
                    str(invalid_txt),
                    str(second_dwg),
                    str(first_dwg),
                    str(missing_dwg),
                ],
            }

            with patch.object(
                self.api,
                "_is_workroom_auto_select_enabled",
                return_value=True,
            ), patch.object(
                self.api,
                "_resolve_workroom_context",
                return_value={
                    "source": "workroom",
                    "project_path": r"C:\Projects\123456",
                    "discipline": "Electrical",
                    "discipline_source": "launch_context",
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_discipline_folder",
            ) as resolve_folder_mock, patch.object(
                self.api,
                "_list_base_level_dwgs",
            ) as list_dwgs_mock:
                result = self.api._resolve_workroom_auto_file_selection(
                    {},
                    launch_context,
                    "run_publish_script",
                )

            self.assertIsNotNone(result)
            self.assertEqual("launch_context_explicit_files", result["resolution_mode"])
            self.assertEqual(2, result["count"])
            self.assertEqual(str(temp_path), result["folder_path"])
            self.assertEqual(r"C:\Projects\123456", result["project_path"])
            self.assertEqual("Electrical", result["discipline"])

            files_list_path = Path(result["files_list_path"])
            try:
                self.assertTrue(files_list_path.exists())
                self.assertEqual(
                    [str(first_dwg), str(second_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)

            resolve_folder_mock.assert_not_called()
            list_dwgs_mock.assert_not_called()

    def test_get_workroom_cad_files_caches_detected_dwg_paths(self):
        with tempfile.TemporaryDirectory(prefix="acies-workroom-cad-") as temp_dir:
            temp_path = Path(temp_dir)
            first_dwg = temp_path / "first.dwg"
            second_dwg = temp_path / "second.dwg"
            first_dwg.write_text("", encoding="utf-8")
            second_dwg.write_text("", encoding="utf-8")

            with patch.object(
                self.api,
                "get_user_settings",
                return_value={},
            ), patch.object(
                self.api,
                "_resolve_workroom_context",
                return_value={
                    "source": "workroom",
                    "project_path": r"C:\Projects\777777",
                    "discipline": "Electrical",
                    "discipline_source": "launch_context",
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_discipline_folder",
                return_value={
                    "resolved_folder": str(temp_path),
                    "mode": "project_path_child_folder",
                    "discipline": "Electrical",
                    "candidates": [str(temp_path)],
                },
            ), patch.object(
                self.api,
                "_list_base_level_dwgs",
                return_value=[str(first_dwg), str(second_dwg)],
            ):
                result = self.api.get_workroom_cad_files({"source": "workroom"})

            self.assertEqual("success", result["status"])
            self.assertEqual(2, len(result["files"]))

            cache_entry = self.api._get_workroom_cad_file_cache_entry(
                r"C:\Projects\777777",
                "Electrical",
            )
            self.assertIsNotNone(cache_entry)
            self.assertEqual(r"C:\Projects\777777", cache_entry["project_path"])
            self.assertEqual("Electrical", cache_entry["discipline"])
            self.assertEqual(str(temp_path), cache_entry["folder_path"])
            self.assertEqual("project_path_child_folder", cache_entry["resolution_mode"])
            self.assertEqual(
                [str(first_dwg), str(second_dwg)],
                cache_entry["files"],
            )

    def test_resolve_workroom_auto_file_selection_prefers_cached_detection_over_explicit_paths(self):
        with tempfile.TemporaryDirectory(prefix="acies-workroom-cad-") as temp_dir:
            temp_path = Path(temp_dir)
            cached_dwg = temp_path / "cached.dwg"
            explicit_dwg = temp_path / "explicit.dwg"
            cached_dwg.write_text("", encoding="utf-8")
            explicit_dwg.write_text("", encoding="utf-8")
            self.api._set_workroom_cad_file_cache_entry(
                r"C:\Projects\123456",
                "Electrical",
                str(temp_path),
                [str(cached_dwg)],
                "project_path_child_folder",
            )

            launch_context = {
                "source": "workroom",
                "cadFilePaths": [str(explicit_dwg)],
            }

            with patch.object(
                self.api,
                "_is_workroom_auto_select_enabled",
                return_value=True,
            ), patch.object(
                self.api,
                "_resolve_workroom_context",
                return_value={
                    "source": "workroom",
                    "project_path": r"C:\Projects\123456",
                    "discipline": "Electrical",
                    "discipline_source": "launch_context",
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_discipline_folder",
            ) as resolve_folder_mock, patch.object(
                self.api,
                "_list_base_level_dwgs",
            ) as list_dwgs_mock:
                result = self.api._resolve_workroom_auto_file_selection(
                    {},
                    launch_context,
                    "run_publish_script",
                )

            self.assertIsNotNone(result)
            self.assertEqual("workroom_cached_detection", result["resolution_mode"])
            self.assertEqual(1, result["count"])
            self.assertEqual(str(temp_path), result["folder_path"])
            self.assertEqual(r"C:\Projects\123456", result["project_path"])
            self.assertEqual("Electrical", result["discipline"])

            files_list_path = Path(result["files_list_path"])
            try:
                self.assertTrue(files_list_path.exists())
                self.assertEqual(
                    [str(cached_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)

            resolve_folder_mock.assert_not_called()
            list_dwgs_mock.assert_not_called()

    def test_workflow_preselected_files_override_cached_detection(self):
        with tempfile.TemporaryDirectory(prefix="acies-workflow-cache-") as temp_dir:
            temp_path = Path(temp_dir)
            cached_dwg = temp_path / "cached.dwg"
            explicit_dwg = temp_path / "explicit.dwg"
            cached_dwg.write_text("", encoding="utf-8")
            explicit_dwg.write_text("", encoding="utf-8")
            self.api._set_workroom_cad_file_cache_entry(
                r"C:\Projects\123456",
                "Electrical",
                str(temp_path),
                [str(cached_dwg)],
                "project_path_child_folder",
            )

            result = self.api._resolve_workroom_auto_file_selection(
                {"workroomAutoSelectCadFiles": True},
                {
                    "source": "workroom",
                    "projectPath": r"C:\Projects\123456",
                    "discipline": "Electrical",
                    "cadFilePaths": [str(explicit_dwg)],
                    "workflowPreselectedDwgFiles": True,
                },
                "run_manage_layers_script",
            )

            self.assertIsNotNone(result)
            self.assertEqual("workflow_preselected_files", result["resolution_mode"])
            self.assertEqual(1, result["count"])
            files_list_path = Path(result["files_list_path"])
            try:
                self.assertEqual([str(explicit_dwg)], files_list_path.read_text(encoding="utf-8").splitlines())
            finally:
                files_list_path.unlink(missing_ok=True)

    def test_invalid_workflow_preselected_files_do_not_fall_back_to_cache(self):
        with tempfile.TemporaryDirectory(prefix="acies-workflow-cache-invalid-") as temp_dir:
            temp_path = Path(temp_dir)
            cached_dwg = temp_path / "cached.dwg"
            cached_dwg.write_text("", encoding="utf-8")
            self.api._set_workroom_cad_file_cache_entry(
                r"C:\Projects\123456",
                "Electrical",
                str(temp_path),
                [str(cached_dwg)],
                "project_path_child_folder",
            )

            result = self.api._resolve_workroom_auto_file_selection(
                {"workroomAutoSelectCadFiles": True},
                {
                    "source": "workroom",
                    "projectPath": r"C:\Projects\123456",
                    "discipline": "Electrical",
                    "cadFilePaths": [str(temp_path / "missing.dwg")],
                    "workflowPreselectedDwgFiles": True,
                },
                "run_manage_layers_script",
            )

        self.assertIsNone(result)

    def test_resolve_workroom_auto_file_selection_falls_back_to_explicit_paths_when_cached_detection_is_stale(self):
        with tempfile.TemporaryDirectory(prefix="acies-workroom-cad-") as temp_dir:
            temp_path = Path(temp_dir)
            stale_dwg = temp_path / "stale.dwg"
            explicit_dwg = temp_path / "explicit.dwg"
            explicit_dwg.write_text("", encoding="utf-8")
            self.api._set_workroom_cad_file_cache_entry(
                r"C:\Projects\222222",
                "Mechanical",
                str(temp_path),
                [str(stale_dwg)],
                "project_path_child_folder",
            )

            launch_context = {
                "source": "workroom",
                "cadFilePaths": [str(explicit_dwg)],
            }

            with patch.object(
                self.api,
                "_is_workroom_auto_select_enabled",
                return_value=True,
            ), patch.object(
                self.api,
                "_resolve_workroom_context",
                return_value={
                    "source": "workroom",
                    "project_path": r"C:\Projects\222222",
                    "discipline": "Mechanical",
                    "discipline_source": "launch_context",
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_discipline_folder",
            ) as resolve_folder_mock, patch.object(
                self.api,
                "_list_base_level_dwgs",
            ) as list_dwgs_mock:
                result = self.api._resolve_workroom_auto_file_selection(
                    {},
                    launch_context,
                    "run_publish_script",
                )

            self.assertIsNotNone(result)
            self.assertEqual("launch_context_explicit_files", result["resolution_mode"])
            self.assertEqual(1, result["count"])
            self.assertEqual(str(temp_path), result["folder_path"])
            self.assertEqual(r"C:\Projects\222222", result["project_path"])
            self.assertEqual("Mechanical", result["discipline"])

            files_list_path = Path(result["files_list_path"])
            try:
                self.assertTrue(files_list_path.exists())
                self.assertEqual(
                    [str(explicit_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)

            resolve_folder_mock.assert_not_called()
            list_dwgs_mock.assert_not_called()

    def test_resolve_workroom_auto_file_selection_falls_back_to_folder_scan_when_explicit_paths_invalid(self):
        with tempfile.TemporaryDirectory(prefix="acies-workroom-cad-") as temp_dir:
            temp_path = Path(temp_dir)
            invalid_txt = temp_path / "ignore.txt"
            fallback_dwg = temp_path / "fallback.dwg"
            invalid_txt.write_text("", encoding="utf-8")
            fallback_dwg.write_text("", encoding="utf-8")

            launch_context = {
                "source": "workroom",
                "cadFilePaths": [str(invalid_txt), str(temp_path / "missing.dwg"), ""],
            }

            with patch.object(
                self.api,
                "_is_workroom_auto_select_enabled",
                return_value=True,
            ), patch.object(
                self.api,
                "_resolve_workroom_context",
                return_value={
                    "source": "workroom",
                    "project_path": r"C:\Projects\654321",
                    "discipline": "Mechanical",
                    "discipline_source": "launch_context",
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_discipline_folder",
                return_value={
                    "resolved_folder": str(temp_path),
                    "mode": "project_path_child_folder",
                    "discipline": "Mechanical",
                    "candidates": [str(temp_path)],
                },
            ) as resolve_folder_mock, patch.object(
                self.api,
                "_list_base_level_dwgs",
                return_value=[str(fallback_dwg)],
            ) as list_dwgs_mock:
                result = self.api._resolve_workroom_auto_file_selection(
                    {},
                    launch_context,
                    "run_publish_script",
                )

            self.assertIsNotNone(result)
            self.assertEqual("project_path_child_folder", result["resolution_mode"])
            self.assertEqual(1, result["count"])
            self.assertEqual(str(temp_path), result["folder_path"])
            self.assertEqual(r"C:\Projects\654321", result["project_path"])
            self.assertEqual("Mechanical", result["discipline"])

            files_list_path = Path(result["files_list_path"])
            try:
                self.assertTrue(files_list_path.exists())
                self.assertEqual(
                    [str(fallback_dwg)],
                    files_list_path.read_text(encoding="utf-8").splitlines(),
                )
            finally:
                files_list_path.unlink(missing_ok=True)

            resolve_folder_mock.assert_called_once_with(r"C:\Projects\654321", "Mechanical")
            list_dwgs_mock.assert_called_once_with(str(temp_path))


class BundleStatusVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.github_repo = "jacobhusband/ElectricalCommands"
        self.api.release_tag = None

    def test_get_bundle_statuses_hides_get_attributes_bundle(self):
        with tempfile.TemporaryDirectory(prefix="acies-bundle-statuses-") as temp_dir:
            plugins_dir = Path(temp_dir)
            (plugins_dir / "ElectricalCommands.CleanCADCommands.bundle").mkdir()
            (plugins_dir / "ElectricalCommands.GetAttributesCommands.bundle").mkdir()
            self.api.app_plugins_folder = str(plugins_dir)

            release_info = {
                "tag": "v1.2.3",
                "assets": [
                    {
                        "name": "ElectricalCommands.CleanCADCommands-v1.2.3.zip",
                        "browser_download_url": "https://example.com/clean.zip",
                    },
                    {
                        "name": "ElectricalCommands.GetAttributesCommands-v1.2.3.zip",
                        "browser_download_url": "https://example.com/getattributes.zip",
                    },
                ],
                "release_notes": "",
                "html_url": "",
            }

            with patch.object(
                self.api,
                "_fetch_latest_bundle_release",
                return_value=release_info,
            ):
                result = self.api.get_bundle_statuses()

        self.assertEqual("success", result["status"])
        bundle_names = [item["bundle_name"] for item in result["data"]]
        self.assertIn("ElectricalCommands.CleanCADCommands.bundle", bundle_names)
        self.assertNotIn("ElectricalCommands.GetAttributesCommands.bundle", bundle_names)

    def test_install_single_bundle_returns_bundle_folder_metadata(self):
        with tempfile.TemporaryDirectory(prefix="acies-install-bundle-") as temp_dir:
            plugins_dir = Path(temp_dir)
            self.api.app_plugins_folder = str(plugins_dir)
            self.api._is_autocad_running = lambda: False
            self.api.release_tag = "v1.2.3"

            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w") as bundle_zip:
                bundle_zip.writestr("PackageContents.xml", "<ApplicationPackage />")

            class FakeResponse:
                def __init__(self, content):
                    self.content = content

                def raise_for_status(self):
                    return None

            asset = {
                "name": "ElectricalCommands.CleanCADCommands-v1.2.3.zip",
                "browser_download_url": "https://example.com/clean.zip",
            }

            with patch("main.requests.get", return_value=FakeResponse(archive_bytes.getvalue())):
                result = self.api.install_single_bundle(asset)

            expected_bundle = plugins_dir / "ElectricalCommands.CleanCADCommands.bundle"
            self.assertEqual("success", result["status"])
            self.assertEqual(str(expected_bundle), result["bundlePath"])
            self.assertEqual(str(plugins_dir), result["pluginsFolderPath"])
            self.assertTrue((expected_bundle / "version.txt").exists())

    def test_uninstall_bundle_returns_plugins_folder_metadata(self):
        with tempfile.TemporaryDirectory(prefix="acies-uninstall-bundle-") as temp_dir:
            plugins_dir = Path(temp_dir)
            bundle_dir = plugins_dir / "ElectricalCommands.CleanCADCommands.bundle"
            bundle_dir.mkdir(parents=True)
            self.api.app_plugins_folder = str(plugins_dir)
            self.api._is_autocad_running = lambda: False

            result = self.api.uninstall_bundle("ElectricalCommands.CleanCADCommands.bundle")

            self.assertEqual("success", result["status"])
            self.assertEqual(str(plugins_dir), result["pluginsFolderPath"])
            self.assertFalse(bundle_dir.exists())


if __name__ == "__main__":
    unittest.main()
