"""The deliverable UI exposes one due date across forms and calendars."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeliverableDueUiTests(unittest.TestCase):
    def test_modal_has_one_due_date(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('<input class="d-due"'), 1)
        self.assertIn('<label class="label">Due Date</label>', html)
        self.assertNotIn("d-hard-due", html)
        self.assertNotIn("Soft Due Date", html)
        self.assertNotIn("Hard Due Date", html)

    def test_calendars_and_register_do_not_offer_date_kinds(self):
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        industry = (ROOT / "industry-projects.js").read_text(encoding="utf-8")
        for text in (script, industry):
            self.assertNotIn("createDueKindTag", text)
            self.assertNotIn("DUE_FIELD_LABELS", text)
            self.assertNotIn("calendar-due-kind-switch", text)
            self.assertNotIn("d-hard-due", text)
        self.assertIn('clearBtn.onclick = () => commit("");', script)

    def test_register_shows_one_due_column(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<th class="reg-th"[^>]*>Due</th>')
        self.assertNotIn(">Internal</th>", html)
        self.assertNotIn(">External</th>", html)


if __name__ == "__main__":
    unittest.main()
