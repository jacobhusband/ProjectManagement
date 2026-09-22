"""
Unit tests for apps/ProjectManagement/database.py
Compatible with unittest and pytest.
"""

import os
import tempfile
import unittest
from database import (
    init_db,
    upsert_project,
    get_project,
    list_projects,
    delete_project,
    upsert_drawing,
    upsert_panel_schedule,
    get_panel_schedule,
    list_panel_schedules,
    delete_panel_schedule,
)


class TestDatabase(unittest.TestCase):
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

    def test_project_crud(self):
        proj = upsert_project("24-001", "Acme Headquarters", "C:/Projects/24-001", db_path=self.temp_db)
        self.assertIsNotNone(proj)
        self.assertEqual(proj["project_number"], "24-001")
        self.assertEqual(proj["project_name"], "Acme Headquarters")

        # Test update
        updated = upsert_project("24-001", "Acme Headquarters Ph2", "C:/Projects/24-001", db_path=self.temp_db)
        self.assertEqual(updated["id"], proj["id"])
        self.assertEqual(updated["project_name"], "Acme Headquarters Ph2")

        # Test list
        all_projs = list_projects(db_path=self.temp_db)
        self.assertEqual(len(all_projs), 1)
        self.assertEqual(all_projs[0]["project_number"], "24-001")

        # Test delete
        self.assertTrue(delete_project("24-001", db_path=self.temp_db))
        self.assertIsNone(get_project("24-001", db_path=self.temp_db))
        self.assertEqual(len(list_projects(db_path=self.temp_db)), 0)

    def test_drawing_and_panel_schedule_crud(self):
        proj = upsert_project("24-002", "City Center", "C:/Projects/24-002", db_path=self.temp_db)
        proj_id = proj["id"]

        dwg = upsert_drawing(proj_id, "C:/Projects/24-002/E-201.dwg", "E-201", "Power Plan", db_path=self.temp_db)
        self.assertEqual(dwg["sheet_number"], "E-201")

        panel_payload = {
            "panelName": "LP-1",
            "voltage": "120/208V",
            "phase": 3,
            "wire": 4,
            "mainBusRatingAmps": 225,
            "mainType": "MCB",
            "mainBreakerAmps": 200,
            "location": "ELEC RM 101",
            "oleHandle": "3F1A",
            "excelWorkbookPath": "C:/Projects/24-002/Panels.xlsx",
            "validationStatus": "VALID",
            "diagnostics": [],
            "loadSummary": {
                "phaseAConnectedVA": 12500,
                "phaseBConnectedVA": 12200,
                "phaseCConnectedVA": 12800,
                "unbalancePercentage": 4.8
            },
            "circuits": [
                {
                    "circuitNumber": 1,
                    "phasePole": "A",
                    "loadDescription": "Lighting Corridor",
                    "loadType": "LIGHTING_CONTINUOUS",
                    "breakerAmps": 20,
                    "poles": 1,
                    "connectedVA": 1600,
                    "demandVA": 2000
                },
                {
                    "circuitNumber": 2,
                    "phasePole": "A",
                    "loadDescription": "Receptacles Office 101",
                    "loadType": "RECEPTACLE_NON_CONTINUOUS",
                    "breakerAmps": 20,
                    "poles": 1,
                    "connectedVA": 1440,
                    "demandVA": 1440
                }
            ]
        }

        panel = upsert_panel_schedule(proj_id, panel_payload, dwg_id=dwg["id"], db_path=self.temp_db)
        self.assertIsNotNone(panel)
        self.assertEqual(panel["panel_name"], "LP-1")
        self.assertEqual(panel["main_bus_amps"], 225)
        self.assertEqual(len(panel["circuits"]), 2)
        self.assertEqual(panel["circuits"][0]["circuit_number"], 1)
        self.assertEqual(panel["loadSummary"]["unbalancePercentage"], 4.8)

        # Test list panels for project
        panels = list_panel_schedules(proj_id, db_path=self.temp_db)
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["panel_name"], "LP-1")

        # Test cascade delete
        deleted = delete_panel_schedule(panel["id"], db_path=self.temp_db)
        self.assertTrue(deleted)
        self.assertIsNone(get_panel_schedule(panel["id"], db_path=self.temp_db))


if __name__ == "__main__":
    unittest.main()
