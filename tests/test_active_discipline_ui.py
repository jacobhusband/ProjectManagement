import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"


class ActiveDisciplineUiTests(unittest.TestCase):
    def test_active_discipline_settings_exist(self):
        # Cloud settings sync (and its activeDiscipline normalization) was removed in 8fa93fa.
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('activeDiscipline: "Electrical",', script)
        self.assertIn("function normalizeActiveDiscipline(", script)
        self.assertIn("function syncActiveDisciplineWithConfigured() {", script)

    def test_active_discipline_can_be_unconfigured_known_discipline(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        normalize_start = script.index("function normalizeActiveDiscipline(")
        normalize_end = script.index("function syncActiveDisciplineWithConfigured()", normalize_start)
        normalize_block = script[normalize_start:normalize_end]
        self.assertIn('const normalized = normalizeWorkroomCadDiscipline(value, "");', normalize_block)
        self.assertIn("if (normalized) return normalized;", normalize_block)
        self.assertNotIn("configured.includes(normalized)", normalize_block)

        set_active_start = script.index("function setActiveDiscipline(discipline) {")
        set_active_end = script.index("function handleHeaderDisciplineSwitcherKeydown", set_active_start)
        set_active_block = script[set_active_start:set_active_end]
        self.assertIn('const nextActive = normalizeWorkroomCadDiscipline(discipline, "");', set_active_block)
        self.assertNotIn("getConfiguredDisciplines()", set_active_block)
        self.assertNotIn("configured.includes", set_active_block)

        keydown_start = script.index("function handleHeaderDisciplineSwitcherKeydown")
        keydown_end = script.index("function initializeHeaderDisciplineSwitcher()", keydown_start)
        keydown_block = script[keydown_start:keydown_end]
        self.assertIn("const selectableOptions = HEADER_DISCIPLINE_TOGGLE_OPTIONS;", keydown_block)
        self.assertNotIn("getConfiguredDisciplines().includes", keydown_block)

    def test_active_discipline_drives_current_work_context(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("getActiveDisciplineList().map((discipline) =>", script)
        self.assertIn(
            'return DISCIPLINE_TO_FUNCTION[getActiveDiscipline()] || "E";',
            script,
        )
        self.assertIn('return getActiveDiscipline() || "General";', script)
        self.assertIn("return [getActiveWorkroomDiscipline()];", script)
        self.assertIn("getActiveDisciplineList()", script)
        self.assertIn(
            'return ["general", "templates", getActiveDisciplineCategoryKey()].includes(category);',
            script,
        )

    def test_configured_discipline_list_still_drives_storage_workflows(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        managed_roots_start = script.index("function getLocalProjectManagerManagedRootNames() {")
        managed_roots_end = script.index("function isLocalProjectManagerManagedRoot", managed_roots_start)
        managed_roots_block = script[managed_roots_start:managed_roots_end]

        self.assertIn("normalizeDisciplineList(userSettings?.discipline)", managed_roots_block)
        self.assertNotIn("getActiveDiscipline", managed_roots_block)


if __name__ == "__main__":
    unittest.main()
