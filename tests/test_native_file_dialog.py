"""Exercise modal picker dispatch without importing startup or touching user data."""
import ast
import logging
import os
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "main.py"


def load_dialog_api():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    api = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Api")
    names = {"_show_file_dialog_windows", "_create_file_dialog", "select_files"}
    api.body = [node for node in api.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = dict(os=os, sys=sys, threading=threading, logging=logging)
    exec(compile(ast.Module(body=[api], type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope["Api"]


class NativeFileDialogTests(unittest.TestCase):
    def setUp(self):
        self.api = load_dialog_api()()
        self.native = Mock(InvokeRequired=True, WindowState="minimized")
        self.window = Mock(native=self.native)
        self.api._get_dialog_window = Mock(return_value=self.window)
        self.api._is_dialog_window_available = Mock(return_value=True)
        self.api._resolve_dialog_directory = lambda directory: directory
        self.api._get_file_dialog_type = lambda name: name
        self.in_ui = False

        def invoke(action):
            self.in_ui = True
            try:
                action()
            finally:
                self.in_ui = False

        self.native.Invoke.side_effect = invoke
        self.paths = (r"C:\Project\E01.dwg", r"C:\Project\E02.dwg")

        def show(dialog_type, **kwargs):
            self.assertTrue(self.in_ui, "the backend must run on the owner's UI thread")
            self.assertEqual("normal", self.native.WindowState)
            self.native.BringToFront.assert_called()
            self.native.Activate.assert_called()
            return self.paths

        self.window.create_file_dialog.side_effect = show
        winforms = types.ModuleType("System.Windows.Forms")
        winforms.FormWindowState = types.SimpleNamespace(Minimized="minimized", Normal="normal")
        system = types.ModuleType("System")
        system.Action = lambda action: action
        windows = types.ModuleType("System.Windows")
        system.Windows = windows
        windows.Forms = winforms
        clr = types.ModuleType("clr")
        clr.AddReference = Mock()
        modules = {"clr": clr, "System": system, "System.Windows": windows,
                   "System.Windows.Forms": winforms}
        for patcher in [patch.dict(sys.modules, modules), patch.object(sys, "platform", "win32")]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.options = {"allow_multiple": True, "file_types": ["Drawing Files (*.dwg)"],
                        "default_directory": str(Path(__file__).parent)}

    def test_open_save_and_folder_use_the_same_ui_thread_dispatch(self):
        for dialog_type in ("OPEN", "SAVE", "FOLDER"):
            with self.subTest(dialog_type=dialog_type):
                kwargs = dict(directory=r"C:\Project", allow_multiple=dialog_type == "OPEN",
                              save_filename="set.pdf", file_types=("PDF Files (*.pdf)",))
                self.assertEqual(self.paths, self.api._create_file_dialog(dialog_type, **kwargs))
                self.window.create_file_dialog.assert_called_with(dialog_type, **kwargs)
        self.assertEqual(3, self.native.Invoke.call_count)
        self.window.restore.assert_not_called()

    def test_selection_keeps_filters_default_directory_and_multiple_paths(self):
        result = self.api.select_files(self.options)
        self.assertEqual({"status": "success", "paths": list(self.paths)}, result)
        self.window.create_file_dialog.assert_called_once_with(
            "OPEN", directory=self.options["default_directory"], allow_multiple=True,
            file_types=tuple(self.options["file_types"]))

    def test_cancel_returns_cancelled_without_opening_another_dialog(self):
        self.window.create_file_dialog.side_effect = lambda *args, **kwargs: None
        self.assertEqual({"status": "cancelled", "paths": []}, self.api.select_files(self.options))
        self.window.create_file_dialog.assert_called_once()

    def test_native_failure_propagates_without_falling_back_to_mta_thread(self):
        self.window.create_file_dialog.side_effect = RuntimeError("native dialog failed")
        with self.assertRaisesRegex(RuntimeError, "native dialog failed"):
            self.api._create_file_dialog("SAVE")
        self.window.create_file_dialog.assert_called_once()

    def test_call_already_on_ui_thread_does_not_invoke_itself(self):
        self.native.InvokeRequired = False
        self.in_ui = True
        self.assertEqual("success", self.api.select_files(self.options)["status"])
        self.native.Invoke.assert_not_called()

    def test_closing_window_does_not_show_a_dialog(self):
        self.api._is_dialog_window_available.return_value = False
        with self.assertLogs(level="ERROR"):
            result = self.api.select_files(self.options)
        self.assertEqual("error", result["status"])
        self.window.create_file_dialog.assert_not_called()

    def test_none_filters_are_normalized_for_pywebview(self):
        self.api._create_file_dialog("SAVE", file_types=None)
        self.window.create_file_dialog.assert_called_once_with("SAVE", file_types=())

    def test_non_windows_backend_uses_normal_modal_dialog(self):
        self.window.create_file_dialog.side_effect = None
        self.window.create_file_dialog.return_value = self.paths
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(self.paths, self.api._create_file_dialog("FOLDER"))
        self.window.restore.assert_called_once_with()
        self.native.Invoke.assert_not_called()

    def test_app_dialogs_cannot_bypass_the_shared_handler(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        allowed = {"_show_file_dialog_windows", "_create_file_dialog"}

        def visit(node, function=None):
            if isinstance(node, ast.FunctionDef) and function not in allowed:
                function = node.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "create_file_dialog":
                    self.assertIn(function, allowed, f"Dialog bypass on line {node.lineno}")
            for child in ast.iter_child_nodes(node):
                visit(child, function)

        visit(tree)


if __name__ == "__main__":
    unittest.main()
