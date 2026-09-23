"""
Tests for complete project deletion functionality across UI, backend, and database layer.
"""

import unittest
from pathlib import Path
import tempfile
import os

from database import (
    init_db,
    upsert_project,
    get_project,
    list_projects,
    delete_project,
    upsert_drawing,
    upsert_panel_schedule,
    get_panel_schedule,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"
MAIN_PY_PATH = REPO_ROOT / "main.py"


class ProjectDeletionUiTests(unittest.TestCase):
    def test_index_html_has_delete_project_buttons(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        # Edit modal delete button
        self.assertIn('id="btnDeleteProject"', html)
        self.assertIn('data-click-action="onDeleteCurrentProject"', html)
        self.assertIn('modal-full-only', html)

        # Page view topbar delete button
        self.assertIn('id="pageDeleteProjectBtn"', html)
        self.assertIn('data-click-action="onDeleteActiveProjectFromPageView"', html)

    def test_script_js_has_project_deletion_functions_and_wiring(self):
        js = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        # Function definitions
        self.assertIn("function removeProject(i,", js)
        self.assertIn("function onDeleteCurrentProject()", js)
        self.assertIn("function onDeleteActiveProjectFromPageView()", js)

        # Deletion steps in removeProject
        self.assertIn("deleteManagedPageWorkbooks", js)
        self.assertIn("window.pywebview.api.delete_project", js)
        self.assertIn("editDlg", js)
        self.assertIn("closePageView()", js)
        self.assertIn("db.splice(currentIndex, 1)", js)

        # Context menu wiring
        self.assertIn("Delete Project", js)
        self.assertIn("data-project-directory-action", js)
        self.assertIn('action === "delete"', js)

        # Table row actions wiring
        self.assertIn("project-details-actions", js)
        self.assertIn("Delete project", js)
        self.assertIn("removeProject(projectIndex)", js)

        # Single deliverable prompt
        self.assertIn("is the only deliverable for project", js)

        # Page view button toggle
        self.assertIn("pageDeleteProjectBtn", js)

    def test_styles_css_has_project_action_styles(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".project-details-actions", css)
        self.assertIn(".project-row-action-btn", css)
        self.assertIn(".project-directory-context-menu__divider", css)

    def test_main_py_has_delete_project_api(self):
        py = MAIN_PY_PATH.read_text(encoding="utf-8")
        self.assertIn("def delete_project(self, project_id=", py)


class ProjectDatabaseCascadingDeletionTests(unittest.TestCase):
    def setUp(self):
        self.fd, self.temp_db = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        init_db(self.temp_db)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            try:
                os.remove(self.temp_db)
            except OSError:
                pass

    def test_delete_project_cascades(self):
        proj = upsert_project("250410", "Test Delete Project", "C:/Projects/250410", db_path=self.temp_db)
        proj_id = proj["id"]

        dwg = upsert_drawing(proj_id, "C:/Projects/250410/E01.dwg", "E01", "Power Plan", db_path=self.temp_db)
        panel_payload = {
            "panelName": "LP1",
            "voltage": "120/208V",
            "phase": 3,
            "wire": 4,
            "mainBusRatingAmps": 225,
            "circuits": [
                {"circuitNumber": 1, "phasePole": "A", "loadDescription": "Lights", "breakerAmps": 20}
            ]
        }
        panel = upsert_panel_schedule(proj_id, panel_payload, dwg_id=dwg["id"], db_path=self.temp_db)
        panel_id = panel["id"]

        self.assertIsNotNone(get_project("250410", db_path=self.temp_db))
        self.assertIsNotNone(get_panel_schedule(panel_id, db_path=self.temp_db))

        # Delete project by number
        deleted = delete_project("250410", db_path=self.temp_db)
        self.assertTrue(deleted)

        # Verify project and cascading panel schedule are deleted
        self.assertIsNone(get_project("250410", db_path=self.temp_db))
        self.assertIsNone(get_panel_schedule(panel_id, db_path=self.temp_db))
        self.assertEqual(len(list_projects(db_path=self.temp_db)), 0)


if __name__ == "__main__":
    unittest.main()
