"""Durability of the primary data files: tasks, notes, timesheets, templates, checklists, settings."""
import datetime
import json
import os
import sys
import tempfile
import threading
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


_ensure_google_genai_stub()
_ensure_webview_stub()
_ensure_dotenv_stub()
_ensure_requests_stub()

import main as main_module
from main import Api


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _damaged_copies(folder):
    return sorted(name for name in os.listdir(folder) if ".damaged-" in name)


class DataFileStorageTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="acies-data-files-")
        self.folder = Path(self._temp.name)
        self.path = str(self.folder / "tasks.json")
        main_module._DATA_FILE_VERIFIED_SIGNATURES.clear()
        main_module._consume_data_recovery_notices()

    def tearDown(self):
        self._temp.cleanup()

    def test_save_swaps_in_new_version_and_keeps_previous_as_backup(self):
        main_module._write_data_file_safely(self.path, [{"id": "1"}])
        main_module._write_data_file_safely(self.path, [{"id": "2"}])

        self.assertEqual([{"id": "2"}], _read_json(self.path))
        self.assertEqual([{"id": "1"}], _read_json(self.path + ".bak"))
        self.assertEqual([], [name for name in os.listdir(self.folder) if name.endswith(".tmp")])

    def test_damaged_file_is_restored_from_backup_and_kept_aside(self):
        Path(self.path + ".bak").write_text(json.dumps([{"id": "good"}]), encoding="utf-8")
        Path(self.path).write_text('[{"id": "trunc', encoding="utf-8")

        payload = main_module._read_data_file_with_recovery(self.path)

        self.assertEqual([{"id": "good"}], payload)
        self.assertEqual([{"id": "good"}], _read_json(self.path))
        damaged = _damaged_copies(self.folder)
        self.assertEqual(1, len(damaged))
        self.assertEqual('[{"id": "trunc', (self.folder / damaged[0]).read_text(encoding="utf-8"))
        notices = main_module._consume_data_recovery_notices()
        self.assertEqual(["tasks.json"], [notice["file"] for notice in notices])
        self.assertEqual(self.path + ".bak", notices[0]["recoveredFrom"])

    def test_saving_over_a_damaged_file_never_rotates_it_into_the_backup(self):
        Path(self.path + ".bak").write_text(json.dumps([{"id": "good"}]), encoding="utf-8")
        Path(self.path).write_text("{not json", encoding="utf-8")

        main_module._write_data_file_safely(self.path, [{"id": "new"}])

        self.assertEqual([{"id": "new"}], _read_json(self.path))
        self.assertEqual([{"id": "good"}], _read_json(self.path + ".bak"))
        self.assertEqual(1, len(_damaged_copies(self.folder)))

    def test_missing_file_is_a_fresh_start_even_when_a_backup_exists(self):
        # Deleting a data file on purpose (for example "delete all notes") must not
        # bring the old contents back from the backup on the next launch.
        Path(self.path + ".bak").write_text(json.dumps([{"id": "deleted"}]), encoding="utf-8")

        with self.assertRaises(FileNotFoundError):
            main_module._read_data_file_with_recovery(self.path)
        self.assertFalse(os.path.exists(self.path))

    def test_unreadable_file_without_backups_raises_and_is_left_untouched(self):
        Path(self.path).write_text("{not json", encoding="utf-8")

        with self.assertRaises(main_module.DataFileUnreadableError):
            main_module._read_data_file_with_recovery(self.path)
        self.assertEqual("{not json", Path(self.path).read_text(encoding="utf-8"))

    def test_recovery_falls_back_to_the_newest_readable_daily_snapshot(self):
        Path(self.path).write_text("{not json", encoding="utf-8")
        Path(self.path + ".bak").write_text("{also damaged", encoding="utf-8")
        backups = self.folder / main_module.DATA_FILE_SNAPSHOT_DIRNAME
        backups.mkdir()
        (backups / "tasks.2000-01-01.json").write_text(json.dumps([{"id": "older"}]), encoding="utf-8")
        (backups / "tasks.2000-01-02.json").write_text(json.dumps([{"id": "newest"}]), encoding="utf-8")

        self.assertEqual(
            [{"id": "newest"}],
            main_module._read_data_file_with_recovery(self.path),
        )

    def test_one_snapshot_per_day_and_old_snapshots_are_pruned(self):
        backups = self.folder / main_module.DATA_FILE_SNAPSHOT_DIRNAME
        backups.mkdir()
        for day in range(1, 21):
            (backups / f"tasks.2000-01-{day:02d}.json").write_text("[]", encoding="utf-8")

        main_module._write_data_file_safely(self.path, [{"id": "1"}])
        main_module._write_data_file_safely(self.path, [{"id": "2"}])
        main_module._write_data_file_safely(self.path, [{"id": "3"}])

        snapshots = main_module._data_file_snapshot_paths(self.path)
        self.assertEqual(main_module.DATA_FILE_SNAPSHOT_KEEP, len(snapshots))
        today = datetime.date.today().isoformat()
        self.assertEqual(str(backups / f"tasks.{today}.json"), snapshots[0])
        # The snapshot captures the first good version seen today, before later saves.
        self.assertEqual([{"id": "1"}], _read_json(snapshots[0]))

    def test_unserializable_payload_leaves_existing_file_untouched(self):
        main_module._write_data_file_safely(self.path, [{"id": "1"}])

        with self.assertRaises(TypeError):
            main_module._write_data_file_safely(self.path, [{"bad": object()}])
        self.assertEqual([{"id": "1"}], _read_json(self.path))

    def test_concurrent_saves_always_leave_complete_files(self):
        payloads = [[{"id": str(index), "notes": "x" * 20000}] for index in range(8)]
        threads = [
            threading.Thread(target=main_module._write_data_file_safely, args=(self.path, payload))
            for payload in payloads
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertIn(_read_json(self.path), payloads)
        self.assertIn(_read_json(self.path + ".bak"), payloads)


class DataFileApiTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="acies-data-api-")
        self.folder = Path(self._temp.name)
        self.api = Api.__new__(Api)
        main_module._DATA_FILE_VERIFIED_SIGNATURES.clear()
        main_module._consume_data_recovery_notices()
        self.paths = {}
        for constant, name in (
            ("TASKS_FILE", "tasks.json"),
            ("NOTES_FILE", "notes.json"),
            ("TIMESHEETS_FILE", "timesheets.json"),
            ("TEMPLATES_FILE", "templates.json"),
            ("CHECKLISTS_FILE", "checklists.json"),
        ):
            self.paths[constant] = str(self.folder / name)
            patcher = patch.object(main_module, constant, self.paths[constant])
            patcher.start()
            self.addCleanup(patcher.stop)
        overlay = patch.object(
            main_module, "_overlay_projects_with_lighting_schedule_records", side_effect=lambda payload: payload
        )
        overlay.start()
        self.addCleanup(overlay.stop)

    def tearDown(self):
        self._temp.cleanup()

    def test_get_tasks_reports_unreadable_data_instead_of_an_empty_list(self):
        Path(self.paths["TASKS_FILE"]).write_text("{not json", encoding="utf-8")

        result = self.api.get_tasks()

        self.assertIsInstance(result, dict)
        self.assertEqual("error", result["status"])
        self.assertEqual("data_file_unreadable", result["code"])
        self.assertEqual("error", self.api.mark_overdue_projects_complete()["status"])
        self.assertEqual("{not json", Path(self.paths["TASKS_FILE"]).read_text(encoding="utf-8"))

    def test_get_tasks_restores_a_damaged_file_and_reports_it_once(self):
        Path(self.paths["TASKS_FILE"] + ".bak").write_text(
            json.dumps([{"id": "240001", "name": "Recovered"}]), encoding="utf-8"
        )
        Path(self.paths["TASKS_FILE"]).write_text('[{"id": "2400', encoding="utf-8")

        tasks = self.api.get_tasks()

        self.assertEqual("Recovered", tasks[0]["name"])
        notices = self.api.get_data_recovery_notices()["notices"]
        self.assertEqual(["tasks.json"], [notice["file"] for notice in notices])
        self.assertEqual([], self.api.get_data_recovery_notices()["notices"])

    def test_damaged_notes_and_timesheets_recover_from_backups(self):
        Path(self.paths["NOTES_FILE"] + ".bak").write_text(json.dumps({"pages": ["kept"]}), encoding="utf-8")
        Path(self.paths["NOTES_FILE"]).write_text('{"pages": [', encoding="utf-8")
        Path(self.paths["TIMESHEETS_FILE"] + ".bak").write_text(
            json.dumps({"weeks": {"2026-09-21": {}}, "expenses": {}}), encoding="utf-8"
        )
        Path(self.paths["TIMESHEETS_FILE"]).write_text('{"weeks": {"2026', encoding="utf-8")

        self.assertEqual({"pages": ["kept"]}, self.api.get_notes())
        self.assertIn("2026-09-21", self.api.get_timesheets()["weeks"])

    def test_damaged_templates_are_restored_instead_of_reset_to_defaults(self):
        custom = {
            "templates": [{"id": "tpl_custom", "name": "My Letter", "isDefault": False, "sourcePath": ""}],
            "defaultTemplatesInstalled": True,
            "lastModified": None,
        }
        Path(self.paths["TEMPLATES_FILE"] + ".bak").write_text(json.dumps(custom), encoding="utf-8")
        Path(self.paths["TEMPLATES_FILE"]).write_text('{"templates": [', encoding="utf-8")

        data = self.api.get_templates()

        self.assertIn("tpl_custom", [template["id"] for template in data["templates"]])

    def test_save_round_trip_for_every_data_file(self):
        self.assertEqual("success", self.api.save_tasks([{"id": "1"}])["status"])
        self.assertEqual("success", self.api.save_notes({"pages": []})["status"])
        self.assertEqual("success", self.api.save_timesheets({"weeks": {}, "expenses": {}})["status"])
        self.assertEqual("success", self.api.save_checklists({"checklists": []})["status"])
        self.assertEqual([{"id": "1"}], self.api.get_tasks())
        self.assertEqual({"pages": []}, self.api.get_notes())
        self.assertEqual({"checklists": []}, self.api.get_checklists())


if __name__ == "__main__":
    unittest.main()
