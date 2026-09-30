"""Activity history: finished activity kept after it is cleared from the activity tray."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_data_file_storage import Api, main_module


REPO_ROOT = Path(__file__).resolve().parents[1]


class ActivityHistoryApiTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="acies-activity-history-")
        self.addCleanup(self._temp.cleanup)
        self.path = Path(self._temp.name) / "activity_history.json"
        patcher = patch.object(main_module, "ACTIVITY_HISTORY_FILE", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)
        main_module._DATA_FILE_VERIFIED_SIGNATURES.clear()
        main_module._consume_data_recovery_notices()
        self.api = Api.__new__(Api)

    def test_missing_file_is_an_empty_history(self):
        self.assertEqual({"status": "success", "entries": []}, self.api.get_activity_history())

    def test_save_round_trip_keeps_entries_in_order(self):
        entries = [
            {"id": "b", "status": "success", "openFolderPath": r"C:\Out"},
            {"id": "a", "status": "error", "rerunLaunchContext": {"cadFilePaths": [r"C:\P\E1.dwg"]}},
        ]

        self.assertEqual("success", self.api.save_activity_history({"entries": entries})["status"])

        self.assertEqual({"status": "success", "entries": entries}, self.api.get_activity_history())

    def test_entries_without_an_id_are_dropped_and_the_newest_are_kept(self):
        entries = [{"id": f"activity-{index}"} for index in range(main_module.ACTIVITY_HISTORY_LIMIT + 5)]

        self.api.save_activity_history({"entries": [None, "text", {"id": " "}, *entries]})

        saved = json.loads(self.path.read_text(encoding="utf-8"))["entries"]
        self.assertEqual(main_module.ACTIVITY_HISTORY_LIMIT, len(saved))
        self.assertEqual("activity-0", saved[0]["id"])

    def test_damaged_file_reports_an_error_so_the_app_does_not_save_over_it(self):
        self.path.write_text('{"entries": [', encoding="utf-8")

        result = self.api.get_activity_history()

        self.assertEqual("error", result["status"])
        self.assertEqual([], result["entries"])
        self.assertEqual('{"entries": [', self.path.read_text(encoding="utf-8"))

    def test_damaged_file_is_restored_from_its_backup(self):
        backup = {"entries": [{"id": "kept", "status": "success"}]}
        Path(str(self.path) + ".bak").write_text(json.dumps(backup), encoding="utf-8")
        self.path.write_text('{"entries": [', encoding="utf-8")

        self.assertEqual(backup["entries"], self.api.get_activity_history()["entries"])
        self.assertTrue(any(".damaged-" in name for name in os.listdir(self._temp.name)))


class ActivityHistoryMarkupTests(unittest.TestCase):
    def test_history_is_reachable_from_the_header_and_the_tray(self):
        html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")

        for element_id in (
            "activityHistoryBtn",
            "activityTrayHistory",
            "activityHistoryDlg",
            "activityHistorySearch",
            "activityHistoryClearBtn",
            "activityHistoryEmpty",
            "activityHistoryList",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('data-close-dialog="activityHistoryDlg"', html)


if __name__ == "__main__":
    unittest.main()
