"""Exercise desktop transfer methods against fixture data, without starting the app."""
import ast
from contextlib import ExitStack
import datetime
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import data_transfer

tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
api_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Api")
methods = [node for node in api_class.body if isinstance(node, ast.FunctionDef)
           and node.name in ("export_app_data", "import_app_data")]


class DataTransferBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / "current"
        self.incoming = self.root / "incoming"
        self.current.mkdir()
        self.incoming.mkdir()
        self.current_targets = {name: self.current / name for name in ("settings.json", "tasks.json")}
        self.source_targets = {name: self.incoming / name for name in self.current_targets}
        self.original_settings = {"userName": "Current", "apiKey": "keep-this-key", "theme": "dark"}
        self.original_tasks = [{"id": "current", "name": "Current project"}]
        for targets, settings, tasks in [
            (self.current_targets, self.original_settings, self.original_tasks),
            (self.source_targets, {"userName": "Imported", "theme": "light"}, [{"id": "imported", "name": "Imported project"}]),
        ]:
            targets["settings.json"].write_text(json.dumps(settings), encoding="utf-8")
            targets["tasks.json"].write_text(json.dumps(tasks), encoding="utf-8")
        self.archive = self.root / "transfer.zip"
        data_transfer.export_archive(self.archive, self.source_targets, set())
        namespace = {
            "webview": types.SimpleNamespace(FileDialog=types.SimpleNamespace(OPEN="open", SAVE="save")),
            "data_transfer": data_transfer, "ExitStack": ExitStack, "datetime": datetime,
            "APP_VERSION": "test", "get_app_data_dir": lambda: str(self.current),
            "get_app_data_path": lambda name: str(self.current / name),
            "_get_data_file_lock": lambda target: threading.RLock(), "tempfile": tempfile,
            "json": json, "Path": Path, "os": os, "logging": logging,
            "SETTINGS_FILE": str(self.current_targets["settings.json"]),
            "_read_json_file_strict": lambda name: json.loads(Path(name).read_text(encoding="utf-8")),
            "_sanitize_user_settings_payload": lambda value: (value, False),
            "_DATA_FILE_VERIFIED_SIGNATURES": {}, "_data_file_key": str,
        }
        exec(compile(ast.Module(body=methods, type_ignores=[]), "main.py", "exec"), namespace)
        self.dialog = Mock()
        self.dialog.create_confirmation_dialog.return_value = True
        self.api = types.SimpleNamespace(
            _create_file_dialog=Mock(return_value=(str(self.archive),)),
            _get_dialog_window=lambda: self.dialog,
            _data_transfer_targets=lambda: (self.current_targets, set()),
        )
        for method in methods:
            setattr(self.api, method.name, types.MethodType(namespace[method.name], self.api))

    def test_cancel_file_chooser_and_confirmation_leave_current_data_unchanged(self):
        self.api._create_file_dialog.return_value = None
        self.assertEqual("cancelled", self.api.export_app_data()["status"])
        self.assertEqual("cancelled", self.api.import_app_data()["status"])
        self.api._create_file_dialog.return_value = (str(self.archive),)
        self.dialog.create_confirmation_dialog.return_value = False
        self.assertEqual("cancelled", self.api.import_app_data()["status"])
        self.assertEqual(self.original_tasks, json.loads(self.current_targets["tasks.json"].read_text()))
        self.assertFalse((self.current / "transfer_backups").exists())

    def test_import_preserves_destination_key_and_keeps_recovery_archive(self):
        result = self.api.import_app_data()
        self.assertEqual("success", result["status"], result)
        settings = json.loads(self.current_targets["settings.json"].read_text())
        self.assertEqual({"userName": "Imported", "theme": "light", "apiKey": "keep-this-key"}, settings)
        self.assertEqual("imported", json.loads(self.current_targets["tasks.json"].read_text())[0]["id"])
        with zipfile.ZipFile(result["backupPath"]) as backup:
            self.assertEqual(self.original_settings, json.loads(backup.read("settings.json")))
            self.assertEqual(self.original_tasks, json.loads(backup.read("tasks.json")))
        message = self.dialog.create_confirmation_dialog.call_args.args[1]
        self.assertIn("1 project,", message)

    def test_export_uses_save_dialog_and_adds_zip_extension(self):
        path = self.root / "portable-copy"
        self.api._create_file_dialog.return_value = str(path)
        result = self.api.export_app_data()
        self.assertEqual("success", result["status"], result)
        self.assertEqual(str(path) + ".zip", result["path"])
        self.assertEqual("save", self.api._create_file_dialog.call_args.args[0])
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertNotIn("apiKey", json.loads(archive.read("settings.json")))


if __name__ == "__main__":
    unittest.main()
