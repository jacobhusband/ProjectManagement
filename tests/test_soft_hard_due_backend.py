"""Soft / hard due dates on the backend: the one shown date drives date sweeps."""
import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_data_file_storage import Api, _read_json, main_module


class ActiveDueFieldTests(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 4)

    def test_soft_date_shows_until_it_passes_then_the_hard_date(self):
        cases = [
            ({}, "", ""),
            ({"due": "2026-09-10"}, "due", "2026-09-10"),
            ({"hardDue": "2026-09-20"}, "hardDue", "2026-09-20"),
            ({"due": "2026-09-10", "hardDue": "2026-09-20"}, "due", "2026-09-10"),
            # The soft date's own day still shows it; the day after hands over.
            ({"due": "09/04/2026", "hardDue": "2026-09-20"}, "due", "09/04/2026"),
            ({"due": "2026-09-03", "hardDue": "2026-09-20"}, "hardDue", "2026-09-20"),
            # A passed soft date with no hard date keeps showing (as overdue).
            ({"due": "2026-09-01"}, "due", "2026-09-01"),
            # A soft date on or after the hard date is ignored.
            ({"due": "2026-09-20", "hardDue": "2026-09-20"}, "hardDue", "2026-09-20"),
            ({"due": "2026-09-25", "hardDue": "2026-09-20"}, "hardDue", "2026-09-20"),
            # An unreadable date never beats a readable one.
            ({"due": "soon", "hardDue": "2026-09-20"}, "hardDue", "2026-09-20"),
            ({"due": "2026-09-10", "hardDue": "tbd"}, "due", "2026-09-10"),
        ]
        for deliverable, field, value in cases:
            with self.subTest(deliverable=deliverable):
                self.assertEqual(
                    field, main_module.get_active_due_field(deliverable, self.TODAY)
                )
                self.assertEqual(
                    value, main_module.get_effective_due_str(deliverable, self.TODAY)
                )

    def test_non_dict_has_no_due_date(self):
        self.assertEqual("", main_module.get_active_due_field(None))
        self.assertEqual("", main_module.get_effective_due_str("nope"))


class SoftHardOverdueSweepTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="acies-soft-hard-")
        self.addCleanup(self._temp.cleanup)
        self.tasks_file = str(Path(self._temp.name) / "tasks.json")
        self.api = Api.__new__(Api)
        main_module._DATA_FILE_VERIFIED_SIGNATURES.clear()
        for patcher in (
            patch.object(main_module, "TASKS_FILE", self.tasks_file),
            patch.object(
                main_module,
                "_overlay_projects_with_lighting_schedule_records",
                side_effect=lambda payload: payload,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        today = datetime.date.today()
        past = (today - datetime.timedelta(days=3)).isoformat()
        long_past = (today - datetime.timedelta(days=6)).isoformat()
        future = (today + datetime.timedelta(days=3)).isoformat()
        projects = [{
            "id": "250002",
            "deliverables": [
                {"name": "Soft passed, hard ahead", "due": past, "hardDue": future,
                 "status": "In progress"},
                {"name": "Both passed", "due": long_past, "hardDue": past,
                 "status": "In progress"},
            ],
        }]
        Path(self.tasks_file).write_text(json.dumps(projects), encoding="utf-8")

    def test_sweep_follows_the_shown_date(self):
        result = self.api.mark_overdue_projects_complete()

        self.assertEqual({"status": "success", "count": 1}, result)
        statuses = {
            d["name"]: d.get("status")
            for d in _read_json(self.tasks_file)[0]["deliverables"]
        }
        self.assertEqual("In progress", statuses["Soft passed, hard ahead"])
        self.assertEqual("Complete", statuses["Both passed"])


if __name__ == "__main__":
    unittest.main()
