import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HeaderDisciplineUiTests(unittest.TestCase):
    def test_discipline_filter_remains_without_account_controls(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="headerDisciplineSwitcher"', html)
        self.assertIn('role="radiogroup"', html)
        for discipline in ("Mechanical", "Electrical", "Plumbing"):
            self.assertIn(f'data-discipline="{discipline}"', html)
        for control in ("headerGoogleAuthBtn", "headerAccountPopover", "googleAccountDlg", "settings_googleAuthActionBtn"):
            self.assertNotIn(control, html)

    def test_discipline_filter_keeps_keyboard_and_selection_handlers(self):
        script = (ROOT / "script.js").read_text(encoding="utf-8")
        for handler in ("renderHeaderDisciplineSwitcher", "setActiveDiscipline", "handleHeaderDisciplineSwitcherKeydown"):
            self.assertIn(f"function {handler}(", script)
        self.assertIn("initializeHeaderDisciplineSwitcher();", script)
        self.assertNotIn("googleAuthState", script)


if __name__ == "__main__":
    unittest.main()
