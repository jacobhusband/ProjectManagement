import os
import json
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
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


import main as main_module  # noqa: E402
from main import Api  # noqa: E402


class WorkflowRunnerTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.calls = []

        def _make_invoker(tool_id, result):
            def _invoke(api, launch_context, activity_id, params):
                self.calls.append({
                    "toolId": tool_id,
                    "launch_context": launch_context,
                    "activity_id": activity_id,
                    "params": params,
                })
                return result

            return _invoke

        self.success_result = {"status": "success"}
        self.fake_registry = {
            "stepA": {
                "displayName": "Step A",
                "invoke": _make_invoker("stepA", self.success_result),
                "params": [],
            },
            "stepB": {
                "displayName": "Step B",
                "invoke": _make_invoker("stepB", self.success_result),
                "params": [],
            },
            "stepC": {
                "displayName": "Step C",
                "invoke": _make_invoker("stepC", self.success_result),
                "params": [],
            },
            "stepError": {
                "displayName": "Failing Step",
                "invoke": _make_invoker(
                    "stepError", {"status": "error", "message": "boom"}
                ),
                "params": [],
            },
            "stepRaise": {
                "displayName": "Raising Step",
                "invoke": lambda api, ctx, aid, params: (_ for _ in ()).throw(
                    RuntimeError("explode")
                ),
                "params": [],
            },
        }

    def _workflow(self, steps):
        return {
            "workflows": [
                {
                    "id": "wf_test",
                    "name": "Test Workflow",
                    "steps": steps,
                }
            ]
        }

    def test_runs_steps_sequentially_in_declared_order(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
            {"toolId": "stepB", "params": {}},
            {"toolId": "stepC", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf_test", launch_context={"src": "ctx"})

        self.assertEqual("success", result["status"])
        self.assertEqual(3, result["stepCount"])
        self.assertEqual(
            ["stepA", "stepB", "stepC"],
            [call["toolId"] for call in self.calls],
        )

    def test_activity_updates_include_workflow_title(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status") as notify:
            result = self.api.run_workflow("wf_test", activity_id="activity_1")

        self.assertEqual("success", result["status"])
        payloads = [call.args[0] for call in notify.call_args_list]
        self.assertGreater(len(payloads), 0)
        for payload in payloads:
            self.assertEqual("Workflow: Test Workflow", payload["label"])
            self.assertEqual("Test Workflow", payload["workflowTitle"])

    def test_per_step_params_reach_invoker(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {"freezePatterns": ["*cloud*", "*rev*"]}},
            {"toolId": "stepB", "params": {"stripXrefs": False}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            self.api.run_workflow("wf_test")

        self.assertEqual(2, len(self.calls))
        self.assertEqual({"freezePatterns": ["*cloud*", "*rev*"]}, self.calls[0]["params"])
        self.assertEqual({"stripXrefs": False}, self.calls[1]["params"])

    def test_launch_context_forwarded_to_each_step(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
            {"toolId": "stepB", "params": {}},
        ])
        launch_context = {"source": "workroom", "project_path": "X:/p"}
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            self.api.run_workflow("wf_test", launch_context=launch_context)

        for call in self.calls:
            self.assertEqual("workroom", call["launch_context"]["source"])
            self.assertEqual("X:/p", call["launch_context"]["project_path"])
            self.assertTrue(call["launch_context"]["workflowBlocking"])

    def test_workflow_step_contexts_are_marked_blocking(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            self.api.run_workflow("wf_test", launch_context={})

        self.assertTrue(self.calls[0]["launch_context"]["workflowBlocking"])

    def test_blocking_script_error_halts_workflow(self):
        self.api.test_mode = False
        with tempfile.TemporaryDirectory(prefix="acies-workflow-blocking-") as temp_dir:
            files_list = Path(temp_dir) / "files.txt"
            files_list.write_text("", encoding="utf-8")
            settings = self._workflow([
                {"toolId": "manageLike", "params": {}},
                {"toolId": "stepC", "params": {}},
            ])
            settings["autocadPath"] = "accoreconsole.exe"
            settings["manageLayersOptions"] = {"scanAllLayers": True}
            registry = {
                "manageLike": {
                    "displayName": "Manage-like",
                    "invoke": lambda api, ctx, aid, params: api.run_manage_layers_script(ctx, aid, params),
                    "params": [],
                    "requiredInputs": [],
                },
                "stepC": self.fake_registry["stepC"],
            }
            with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", registry), \
                    patch.object(self.api, "get_user_settings", return_value=settings), \
                    patch.object(self.api, "_notify_activity_status"), \
                    patch.object(self.api, "_resolve_workroom_auto_file_selection",
                                 return_value={"files_list_path": str(files_list), "count": 1}), \
                    patch.object(self.api, "_run_script_with_progress",
                                 return_value={"status": "error", "message": "script failed"}) as run_script:
                result = self.api.run_workflow("wf_test", launch_context={})

        self.assertEqual("error", result["status"])
        self.assertEqual(1, result["failedStep"])
        self.assertEqual("manageLike", result["tool"])
        self.assertIn("script failed", result["message"])
        self.assertEqual([], [call["toolId"] for call in self.calls])
        self.assertTrue(run_script.call_args.kwargs["wait"])

    def test_stops_on_first_step_error_result(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
            {"toolId": "stepError", "params": {}},
            {"toolId": "stepC", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf_test")

        self.assertEqual("error", result["status"])
        self.assertEqual(2, result["failedStep"])
        self.assertEqual("stepError", result["tool"])
        self.assertIn("boom", result["message"])
        self.assertEqual(
            ["stepA", "stepError"],
            [call["toolId"] for call in self.calls],
            "Steps after the failing step must not run.",
        )

    def test_cancelled_step_stops_workflow_without_running_later_steps(self):
        cancelled_registry = dict(self.fake_registry)

        def _cancelled_step(api, launch_context, activity_id, params):
            self.calls.append({"toolId": "stepCancelled"})
            return {"status": "cancelled", "message": "Cancelled by user."}

        cancelled_registry["stepCancelled"] = {
            "displayName": "Cancelled Step",
            "invoke": _cancelled_step,
            "params": [],
        }
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
            {"toolId": "stepCancelled", "params": {}},
            {"toolId": "stepC", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", cancelled_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status") as notify:
            result = self.api.run_workflow("wf_test", activity_id="workflow_activity")

        self.assertEqual("cancelled", result["status"])
        self.assertEqual(2, result["cancelledStep"])
        self.assertEqual(["stepA", "stepCancelled"], [call["toolId"] for call in self.calls])
        self.assertEqual("cancelled", notify.call_args.args[0]["status"])

    def test_cancel_activity_terminates_matching_workflow_step_process(self):
        self.api._ensure_script_worker_state()
        process = object()
        self.api._script_processes_by_activity["workflow_activity-step2"] = process

        with patch.object(self.api, "_terminate_script_process") as terminate:
            result = self.api.cancel_activity("workflow_activity")

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["cancelledProcessCount"])
        terminate.assert_called_once_with(process)
        self.assertTrue(self.api._is_activity_cancel_requested("workflow_activity-step2"))

    def test_stops_on_first_step_exception(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
            {"toolId": "stepRaise", "params": {}},
            {"toolId": "stepC", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf_test")

        self.assertEqual("error", result["status"])
        self.assertEqual(2, result["failedStep"])
        self.assertEqual("stepRaise", result["tool"])
        self.assertEqual(["stepA"], [call["toolId"] for call in self.calls])

    def test_missing_workflow_returns_error(self):
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value={"workflows": []}), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf_missing")
        self.assertEqual("error", result["status"])
        self.assertIn("not found", result["message"].lower())

    def test_unknown_tool_id_in_step_halts(self):
        settings = self._workflow([
            {"toolId": "stepA", "params": {}},
            {"toolId": "doesNotExist", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf_test")
        self.assertEqual("error", result["status"])
        self.assertEqual(2, result["failedStep"])

    def test_empty_steps_returns_error(self):
        settings = self._workflow([])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf_test")
        self.assertEqual("error", result["status"])

    def test_default_registry_includes_expected_tools(self):
        registry = main_module.WORKFLOW_TOOL_REGISTRY
        for tool_id in ("backupDrawings", "manageLayers", "cleanXrefs", "publishDwgs"):
            self.assertIn(tool_id, registry, f"Missing default registry entry: {tool_id}")
            self.assertIn("displayName", registry[tool_id])
            self.assertTrue(callable(registry[tool_id]["invoke"]))


class LayerPatternNormalizationTests(unittest.TestCase):
    def test_none_returns_empty_list(self):
        self.assertEqual([], main_module._normalize_layer_pattern_list(None))

    def test_list_input_passes_through_trimmed(self):
        self.assertEqual(
            ["*cloud*", "*rev*"],
            main_module._normalize_layer_pattern_list([" *cloud* ", "*rev*", ""]),
        )

    def test_semicolon_string_split(self):
        self.assertEqual(
            ["*cloud*", "*rev*"],
            main_module._normalize_layer_pattern_list("*cloud* ; *rev*"),
        )

    def test_comma_string_split(self):
        self.assertEqual(
            ["*cloud*", "*rev*"],
            main_module._normalize_layer_pattern_list("*cloud*, *rev*"),
        )

    def test_dedup_case_insensitive(self):
        self.assertEqual(
            ["*CLOUD*"],
            main_module._normalize_layer_pattern_list(["*CLOUD*", "*cloud*", "  "]),
        )


class WorkflowToolDescriptorTests(unittest.TestCase):
    def test_descriptors_are_json_safe(self):
        descriptors = main_module.get_workflow_tool_descriptors()
        self.assertTrue(len(descriptors) >= 4)
        for entry in descriptors:
            self.assertIn("toolId", entry)
            self.assertIn("displayName", entry)
            self.assertIn("params", entry)
            self.assertIn("requiredInputs", entry)
            self.assertNotIn("invoke", entry, "Callables must not leak to the UI side.")

    def test_required_inputs_match_expected_shape(self):
        descriptors = {d["toolId"]: d for d in main_module.get_workflow_tool_descriptors()}

        backup_inputs = descriptors["backupDrawings"]["requiredInputs"]
        self.assertEqual(1, len(backup_inputs))
        self.assertEqual("projectFolder", backup_inputs[0]["key"])
        self.assertEqual("folder", backup_inputs[0]["type"])

        for tool_id in ("manageLayers", "cleanXrefs", "publishDwgs"):
            req = descriptors[tool_id]["requiredInputs"]
            self.assertEqual(1, len(req), f"{tool_id} should declare one required input")
            self.assertEqual("dwgFiles", req[0]["key"])
            self.assertEqual("dwgFiles", req[0]["type"])

        publish_params = {
            param["key"]: param for param in descriptors["publishDwgs"]["params"]
        }
        self.assertIn("refreshExcelOleLinks", publish_params)
        self.assertEqual("bool", publish_params["refreshExcelOleLinks"]["type"])
        self.assertTrue(publish_params["refreshExcelOleLinks"]["default"])


class BuildWorkflowStepLaunchContextTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_returns_dict_when_base_is_none(self):
        result = self.api._build_workflow_step_launch_context(None, {}, [])
        self.assertEqual({}, result)

    def test_does_not_mutate_base(self):
        base = {"source": "workroom", "project_path": "C:/orig"}
        inputs = {"projectFolder": "C:/override", "dwgFiles": ["a.dwg"]}
        required = [
            {"key": "projectFolder", "type": "folder"},
            {"key": "dwgFiles", "type": "dwgFiles"},
        ]
        self.api._build_workflow_step_launch_context(base, inputs, required)
        self.assertEqual({"source": "workroom", "project_path": "C:/orig"}, base)

    def test_injects_project_folder_into_project_path(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={},
            inputs={"projectFolder": "C:/Projects/X"},
            required=[{"key": "projectFolder", "type": "folder"}],
        )
        self.assertEqual("C:/Projects/X", result["project_path"])
        self.assertEqual("C:/Projects/X", result["projectPath"])
        self.assertEqual("C:/Projects/X", result["rootProjectPath"])

    def test_project_folder_overrides_inherited_launch_paths(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={
                "source": "workroom",
                "project_path": "C:/Projects/OldSnake",
                "projectPath": "C:/Projects/OldProject",
                "rootProjectPath": "C:/Projects/OldRoot",
            },
            inputs={"projectFolder": "C:/Projects/Selected"},
            required=[{"key": "projectFolder", "type": "folder"}],
        )
        self.assertEqual("workroom", result["source"])
        self.assertEqual("C:/Projects/Selected", result["project_path"])
        self.assertEqual("C:/Projects/Selected", result["projectPath"])
        self.assertEqual("C:/Projects/Selected", result["rootProjectPath"])

    def test_sets_source_manual_when_base_has_no_source(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={},
            inputs={"projectFolder": "C:/p"},
            required=[{"key": "projectFolder", "type": "folder"}],
        )
        self.assertEqual("manual", result["source"])

    def test_preserves_existing_source_when_base_has_workroom(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={"source": "workroom"},
            inputs={"projectFolder": "C:/p"},
            required=[{"key": "projectFolder", "type": "folder"}],
        )
        self.assertEqual("workroom", result["source"])

    def test_injects_dwg_files_into_cad_file_paths(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={},
            inputs={"dwgFiles": ["a.dwg", "b.dwg"]},
            required=[{"key": "dwgFiles", "type": "dwgFiles"}],
        )
        self.assertEqual(["a.dwg", "b.dwg"], result["cadFilePaths"])
        self.assertTrue(result["workflowPreselectedDwgFiles"])

    def test_filters_empty_dwg_paths(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={},
            inputs={"dwgFiles": ["a.dwg", "  ", "", "b.dwg"]},
            required=[{"key": "dwgFiles", "type": "dwgFiles"}],
        )
        self.assertEqual(["a.dwg", "b.dwg"], result["cadFilePaths"])

    def test_injects_dwg_file_sources(self):
        sources = [
            {
                "kind": "zipEntry",
                "zipPath": "C:/Arch/latest.zip",
                "entryName": "A01.dwg",
                "projectRoot": "C:/Project",
                "displayPath": "C:/Arch/latest.zip::A01.dwg",
            }
        ]
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={},
            inputs={"dwgFiles": ["C:/Arch/latest.zip::A01.dwg"], "dwgFileSources": sources},
            required=[{"key": "dwgFiles", "type": "dwgFiles"}],
        )
        self.assertEqual(["C:/Arch/latest.zip::A01.dwg"], result["cadFilePaths"])
        self.assertEqual(os.path.normpath("C:/Arch/latest.zip"), result["dwgFileSources"][0]["zipPath"])
        self.assertEqual(os.path.normpath("C:/Project"), result["dwgFileSources"][0]["projectRoot"])
        self.assertEqual("A01.dwg", result["dwgFileSources"][0]["entryName"])
        self.assertEqual("C:/Arch/latest.zip::A01.dwg", result["dwgFileSources"][0]["displayPath"])
        self.assertTrue(result["workflowPreselectedDwgFiles"])

    def test_ignores_inputs_not_in_required_schema(self):
        result = self.api._build_workflow_step_launch_context(
            base_launch_context={},
            inputs={"dwgFiles": ["a.dwg"], "projectFolder": "C:/p"},
            required=[{"key": "projectFolder", "type": "folder"}],
        )
        self.assertEqual("C:/p", result["project_path"])
        self.assertNotIn("cadFilePaths", result)

    def test_blank_project_folder_does_not_override(self):
        base = {"project_path": "C:/keep"}
        result = self.api._build_workflow_step_launch_context(
            base_launch_context=base,
            inputs={"projectFolder": "   "},
            required=[{"key": "projectFolder", "type": "folder"}],
        )
        self.assertEqual("C:/keep", result["project_path"])


class WorkflowRunnerStepInputsTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.received_contexts = []

        def _capture_invoker(_tool_id):
            def _invoke(api, ctx, aid, params):
                self.received_contexts.append({"ctx": dict(ctx or {}), "params": params})
                return {"status": "success"}
            return _invoke

        # Registry with requiredInputs declared so the runner knows what to inject.
        self.fake_registry = {
            "backupLike": {
                "displayName": "Backup-like",
                "invoke": _capture_invoker("backupLike"),
                "params": [],
                "requiredInputs": [{"key": "projectFolder", "type": "folder"}],
            },
            "dwgLike": {
                "displayName": "DWG-like",
                "invoke": _capture_invoker("dwgLike"),
                "params": [],
                "requiredInputs": [{"key": "dwgFiles", "type": "dwgFiles"}],
            },
            "stepNoInputs": {
                "displayName": "No-input",
                "invoke": _capture_invoker("stepNoInputs"),
                "params": [],
                "requiredInputs": [],
            },
        }

    def _settings(self, steps):
        return {"workflows": [{"id": "wf", "name": "Test", "steps": steps}]}

    def test_step_inputs_inject_project_path_and_cad_file_paths(self):
        settings = self._settings([
            {"toolId": "backupLike", "params": {}},
            {"toolId": "dwgLike", "params": {}},
        ])
        step_inputs = {
            "0": {"projectFolder": "C:/Projects/X"},
            "1": {"dwgFiles": ["E001.dwg", "E002.dwg"]},
        }
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow(
                "wf", launch_context={}, step_inputs=step_inputs)

        self.assertEqual("success", result["status"])
        self.assertEqual(2, len(self.received_contexts))
        self.assertEqual("C:/Projects/X", self.received_contexts[0]["ctx"]["project_path"])
        self.assertEqual("manual", self.received_contexts[0]["ctx"]["source"])
        self.assertEqual(["E001.dwg", "E002.dwg"], self.received_contexts[1]["ctx"]["cadFilePaths"])

    def test_step_inputs_optional_backward_compat(self):
        """Calling without step_inputs preserves the v1 behavior."""
        settings = self._settings([
            {"toolId": "backupLike", "params": {}},
            {"toolId": "stepNoInputs", "params": {}},
        ])
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow("wf", launch_context={"source": "workroom"})

        self.assertEqual("success", result["status"])
        # The base launch_context still flows through; no injection happens.
        self.assertNotIn("project_path", self.received_contexts[0]["ctx"])
        self.assertEqual("workroom", self.received_contexts[0]["ctx"]["source"])

    def test_step_with_no_required_inputs_ignores_step_inputs_entry(self):
        settings = self._settings([{"toolId": "stepNoInputs", "params": {}}])
        step_inputs = {"0": {"projectFolder": "C:/should-be-ignored"}}
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", self.fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            self.api.run_workflow("wf", step_inputs=step_inputs)
        self.assertNotIn("project_path", self.received_contexts[0]["ctx"])

    def test_folder_step_input_reaches_project_source_resolution(self):
        selected_project = "C:/Projects/260001 Example"
        settings = self._settings([{"toolId": "backupLike", "params": {}}])

        def _resolve_source(api, ctx, aid, params):
            self.received_contexts.append({"ctx": dict(ctx or {}), "params": params})
            return api._resolve_copy_project_source_path(None, ctx, {})

        registry = {
            "backupLike": {
                "displayName": "Backup-like",
                "invoke": _resolve_source,
                "params": [],
                "requiredInputs": [{"key": "projectFolder", "type": "folder"}],
            },
        }
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_notify_activity_status"):
            result = self.api.run_workflow(
                "wf",
                launch_context={},
                step_inputs={"0": {"projectFolder": selected_project}},
            )

        self.assertEqual("success", result["status"])
        self.assertEqual(selected_project, self.received_contexts[0]["ctx"]["project_path"])
        self.assertEqual(selected_project, self.received_contexts[0]["ctx"]["projectPath"])
        self.assertEqual(selected_project, self.received_contexts[0]["ctx"]["rootProjectPath"])


class WorkflowCleanXrefsSourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.test_mode = False

    def test_clean_xrefs_uses_workflow_source_manifest_instead_of_workroom_picker(self):
        with tempfile.TemporaryDirectory(prefix="acies-clean-workflow-") as temp_dir:
            temp_path = Path(temp_dir)
            arch_dwg = temp_path / "260002 Example" / "Arch" / "A01-01.dwg"
            arch_dwg.parent.mkdir(parents=True, exist_ok=True)
            arch_dwg.write_text("arch", encoding="utf-8")
            launch_context = {
                "source": "workroom",
                "dwgFileSources": [{"kind": "file", "path": str(arch_dwg)}],
            }
            captured = []
            with patch.object(
                self.api,
                "get_user_settings",
                return_value={
                    "autocadPath": r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
                    "cleanDwgOptions": {},
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_context",
                return_value={
                    "source": "workroom",
                    "project_path": str(arch_dwg.parents[1]),
                    "discipline": "Electrical",
                    "discipline_source": "launch_context",
                },
            ), patch.object(
                self.api,
                "_resolve_workroom_arch_folder",
            ) as arch_folder_mock, patch.object(
                self.api,
                "_run_script_with_progress",
                side_effect=lambda command, tool_id, **kwargs: captured.append((command, tool_id, kwargs)),
            ), patch.object(self.api, "_notify_tool_status"):
                result = self.api.run_clean_xrefs_script(launch_context)

            self.assertEqual("success", result["status"])
            self.assertEqual(1, len(captured))
            command, tool_id, _kwargs = captured[0]
            self.assertEqual("toolCleanXrefs", tool_id)
            self.assertIn("-SourceManifestPath", command)
            self.assertNotIn("-DefaultDirectory", command)
            arch_folder_mock.assert_not_called()

            manifest_path = Path(command[command.index("-SourceManifestPath") + 1])
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual([{"kind": "file", "path": str(arch_dwg), "displayPath": str(arch_dwg)}], manifest)
            finally:
                manifest_path.unlink(missing_ok=True)


class CleanXrefsSelectBeforeQueueTests(unittest.TestCase):
    """XREF asks for its drawings before it waits for its turn in the queue."""

    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.test_mode = False
        self.settings = {
            "autocadPath": r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
        }

    def _select(self, launch_context, context, script_answer, auto_selection=None,
                default_directory="", arch_folder=""):
        """Runs the selection with a fake script that writes script_answer."""
        commands = []

        def fake_script(command):
            commands.append(command)
            output_path = Path(command[command.index("-SelectionOutputPath") + 1])
            if isinstance(script_answer, tuple):
                return script_answer
            output_path.write_text(json.dumps(script_answer), encoding="utf-8")
            return 0, ""

        with patch.object(self.api, "get_user_settings", return_value=self.settings), \
                patch.object(self.api, "_resolve_workroom_context", return_value=context), \
                patch.object(self.api, "_resolve_workroom_auto_file_selection",
                             return_value=auto_selection) as auto_mock, \
                patch.object(self.api, "_resolve_launch_context_default_directory",
                             return_value=default_directory), \
                patch.object(self.api, "_resolve_workroom_arch_folder",
                             return_value=arch_folder), \
                patch.object(self.api, "_run_selection_script", side_effect=fake_script):
            result = self.api.select_clean_xrefs_sources(launch_context)
        return result, commands, auto_mock

    def test_manual_pick_returns_sources_for_the_queued_run(self):
        with tempfile.TemporaryDirectory(prefix="acies-xref-select-") as temp_dir:
            project = Path(temp_dir) / "260010 Example"
            dwg = project / "Arch" / "A01-01.dwg"
            dwg.parent.mkdir(parents=True)
            dwg.write_text("arch", encoding="utf-8")
            zip_path = project / "Arch" / "CAD.zip"
            zip_path.write_bytes(b"zip")

            result, commands, _ = self._select(
                {"projectPath": str(project)},
                {"source": "manual"},
                [
                    {"kind": "file", "path": str(dwg), "projectRoot": "", "displayPath": str(dwg)},
                    {"kind": "zipEntry", "zipPath": str(zip_path), "entryName": "CAD/A02-01.dwg",
                     "projectRoot": str(project), "displayPath": ""},
                ],
                default_directory=str(project),
            )

            self.assertEqual("success", result["status"])
            self.assertEqual([str(dwg), str(zip_path)],
                             [source.get("path") or source["zipPath"] for source in result["sources"]])
            self.assertEqual(str(project), result["sources"][1]["projectRoot"])
            command = commands[0]
            self.assertEqual(str(project), command[command.index("-DefaultDirectory") + 1])
            self.assertFalse(Path(command[command.index("-SelectionOutputPath") + 1]).exists())

            # The run then uses the picked drawings without opening a picker.
            captured = []
            with patch.object(self.api, "get_user_settings", return_value=self.settings), \
                    patch.object(self.api, "_resolve_workroom_context", return_value={"source": "manual"}), \
                    patch.object(self.api, "_run_script_with_progress",
                                 side_effect=lambda command, tool_id, **kwargs: captured.append(command)), \
                    patch.object(self.api, "_notify_tool_status"):
                run = self.api.run_clean_xrefs_script(
                    {"projectPath": str(project), "dwgFileSources": result["sources"]})
            self.assertEqual("success", run["status"])
            manifest_path = Path(captured[0][captured[0].index("-SourceManifestPath") + 1])
            try:
                self.assertEqual(2, len(json.loads(manifest_path.read_text(encoding="utf-8"))))
            finally:
                manifest_path.unlink(missing_ok=True)

    def test_workroom_pick_opens_in_the_arch_folder(self):
        result, commands, auto_mock = self._select(
            {"source": "workroom"},
            {"source": "workroom"},
            [],
            arch_folder=r"P:\260011 Example\Arch",
        )

        self.assertEqual("cancelled", result["status"])
        command = commands[0]
        self.assertEqual(r"P:\260011 Example\Arch", command[command.index("-DefaultDirectory") + 1])
        auto_mock.assert_not_called()

    def test_cancelled_pick_starts_nothing(self):
        result, commands, _ = self._select(None, {"source": "none"}, [])

        self.assertEqual({"status": "cancelled"}, result)
        self.assertNotIn("-DefaultDirectory", commands[0])

    def test_script_error_is_reported(self):
        result, _, _ = self._select(
            None, {"source": "none"}, (1, "AutoCAD Core Console (2020 or newer) was not found."))

        self.assertEqual("error", result["status"])
        self.assertIn("AutoCAD Core Console", result["message"])

    def test_auto_selected_drawings_need_no_question(self):
        with tempfile.TemporaryDirectory(prefix="acies-xref-auto-") as temp_dir:
            files_list = Path(temp_dir) / "dwg-list.txt"
            files_list.write_text("x.dwg\n", encoding="utf-8")

            result, commands, _ = self._select(
                {"cadFilePaths": ["x.dwg"]},
                {"source": "manual"},
                [],
                auto_selection={"files_list_path": str(files_list)},
            )

            self.assertEqual({"status": "skipped"}, result)
            self.assertEqual([], commands)
            self.assertFalse(files_list.exists())

    def test_workflow_sources_need_no_question(self):
        with tempfile.TemporaryDirectory(prefix="acies-xref-workflow-") as temp_dir:
            dwg = Path(temp_dir) / "A01-01.dwg"
            dwg.write_text("arch", encoding="utf-8")
            with patch.object(self.api, "_run_selection_script") as script_mock:
                result = self.api.select_clean_xrefs_sources(
                    {"dwgFileSources": [{"kind": "file", "path": str(dwg)}]})

        self.assertEqual({"status": "skipped"}, result)
        script_mock.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "runs removeXREFPaths.ps1")
    def test_real_script_selection_mode_reports_a_cancelled_pick(self):
        # ACIES_NONINTERACTIVE makes the script skip its picker, as if cancelled.
        powershell = shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("powershell.exe is required")
        with patch.dict(os.environ, {"ACIES_NONINTERACTIVE": "1"}), \
                patch.object(self.api, "get_user_settings", return_value={"autocadPath": powershell}), \
                patch.object(self.api, "_resolve_workroom_context", return_value={"source": "none"}), \
                patch.object(self.api, "_resolve_workroom_auto_file_selection", return_value=None):
            result = self.api.select_clean_xrefs_sources(None)

        self.assertEqual({"status": "cancelled"}, result)


class ResolveWorkflowDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def _settings(self, steps):
        return {"workflows": [{"id": "wf", "name": "Test", "steps": steps}]}

    def test_returns_workflow_cad_defaults_from_electrical_and_newest_arch(self):
        settings = self._settings([
            {"toolId": "backupDrawings", "params": {}},
            {"toolId": "manageLayers", "params": {"freezePatterns": ["*cloud*"]}},
            {"toolId": "cleanXrefs", "params": {}},
        ])
        with tempfile.TemporaryDirectory(prefix="acies-workflow-defaults-") as temp_dir:
            project_root = Path(temp_dir) / "260001 Example"
            electrical = project_root / "Electrical"
            arch_old = project_root / "Arch" / "2024-01-01"
            arch_new = project_root / "Arch" / "2026-01-01"
            arch_zip_folder = project_root / "Arch" / "2026-02-01"
            nested_electrical = electrical / "Nested"
            for folder in (electrical, arch_old, arch_new, arch_zip_folder, nested_electrical):
                folder.mkdir(parents=True, exist_ok=True)

            e001 = electrical / "E001.dwg"
            e002 = electrical / "E002.dwg"
            nested = nested_electrical / "E-nested.dwg"
            old_arch = arch_old / "A01-01.dwg"
            new_arch = arch_new / "A01-01.dwg"
            for path in (e001, e002, nested, old_arch, new_arch):
                path.write_text(path.name, encoding="utf-8")
            zip_path = arch_zip_folder / "Latest CAD.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Backgrounds/Z100.dwg", "zip-dwg")

            os.utime(arch_old, (100, 100))
            os.utime(old_arch, (100, 100))
            os.utime(arch_new, (200, 200))
            os.utime(new_arch, (200, 200))
            os.utime(arch_zip_folder, (300, 300))
            os.utime(zip_path, (300, 300))

            scan_results = [
                {
                    "sourceDwg": str(e001),
                    "references": [
                        {"name": "A01-01", "path": "A01-01.dwg"},
                        {"name": "Z100", "path": "Z100.dwg"},
                    ],
                }
            ]
            with patch.object(self.api, "get_user_settings", return_value=settings), \
                    patch.object(self.api, "_resolve_workroom_context",
                                 return_value={"project_path": str(project_root), "source": "workroom"}), \
                    patch.object(self.api, "_read_workflow_xref_scan_results",
                                 return_value=scan_results):
                result = self.api.resolve_workflow_defaults(
                    "wf", launch_context={"source": "workroom", "discipline": "Mechanical"})

        self.assertEqual("success", result["status"])
        defaults = result["defaults"]
        self.assertEqual(str(project_root), defaults["0"]["projectFolder"])
        self.assertEqual([str(e001), str(e002)], defaults["1"]["dwgFiles"])
        self.assertNotIn(str(nested), defaults["1"]["dwgFiles"])

        clean_sources = defaults["2"]["dwgFileSources"]
        self.assertEqual(str(new_arch), clean_sources[0]["path"])
        self.assertEqual("zipEntry", clean_sources[1]["kind"])
        self.assertEqual(str(zip_path), clean_sources[1]["zipPath"])
        self.assertEqual("Backgrounds/Z100.dwg", clean_sources[1]["entryName"])
        self.assertEqual(str(project_root), clean_sources[1]["projectRoot"])
        self.assertEqual(
            [source["displayPath"] for source in clean_sources],
            defaults["2"]["dwgFiles"],
        )

    def test_returns_empty_defaults_when_nothing_resolves(self):
        settings = self._settings([
            {"toolId": "backupDrawings", "params": {}},
            {"toolId": "cleanXrefs", "params": {}},
        ])
        with patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_resolve_workroom_context", return_value={}), \
                patch.object(self.api, "_resolve_workroom_auto_file_selection", return_value=None):
            result = self.api.resolve_workflow_defaults("wf", launch_context=None)

        self.assertEqual("success", result["status"])
        self.assertEqual({}, result["defaults"])

    def test_skips_steps_with_no_required_inputs(self):
        settings = self._settings([
            # manageLayers has dwgFiles required; pretend the registry says no required inputs
            # by using a tool that has none — we'll patch the registry.
            {"toolId": "noReq", "params": {}},
        ])
        fake_registry = {
            "noReq": {
                "displayName": "No",
                "invoke": lambda api, ctx, aid, params: {"status": "success"},
                "params": [],
                "requiredInputs": [],
            }
        }
        with patch.object(main_module, "WORKFLOW_TOOL_REGISTRY", fake_registry), \
                patch.object(self.api, "get_user_settings", return_value=settings), \
                patch.object(self.api, "_resolve_workroom_context",
                             return_value={"project_path": "C:/x"}), \
                patch.object(self.api, "_resolve_workroom_auto_file_selection", return_value=None):
            result = self.api.resolve_workflow_defaults("wf")

        self.assertEqual("success", result["status"])
        self.assertEqual({}, result["defaults"])

    def test_missing_workflow_returns_error(self):
        with patch.object(self.api, "get_user_settings", return_value={"workflows": []}):
            result = self.api.resolve_workflow_defaults("wf_nope")
        self.assertEqual("error", result["status"])


if __name__ == "__main__":
    unittest.main()
