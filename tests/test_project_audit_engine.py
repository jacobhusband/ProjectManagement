import json
import os
import re
import shutil
import tempfile
import unittest


AUDIT_COMMANDS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ElectricalCommands", "AutoCADCommands", "AuditCommands")
)


@unittest.skipUnless(
    os.path.isdir(AUDIT_COMMANDS_DIR),
    "Cross-repo contract test: needs the sibling ElectricalCommands checkout",
)
class TestProjectAuditEngine(unittest.TestCase):
    def setUp(self):
        test_dir = os.path.dirname(__file__)
        self.audit_dir = os.path.normpath(
            os.path.join(test_dir, "..", "..", "ElectricalCommands", "AutoCADCommands", "AuditCommands")
        )
        self.catalog_path = os.path.join(self.audit_dir, "master_audit_catalog.json")
        self.engine_path = os.path.join(self.audit_dir, "AuditEngine.cs")
        self.test_dir = tempfile.mkdtemp()

        with open(self.catalog_path, "r", encoding="utf-8") as catalog_file:
            self.catalog = json.load(catalog_file)
        with open(self.engine_path, "r", encoding="utf-8") as engine_file:
            self.engine_source = engine_file.read()
        self.produced_flags = set(re.findall(r'flags\["([^"]+)"\]\s*=', self.engine_source))

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_master_catalog_schema_integrity_and_predicates(self):
        self.assertEqual(self.catalog["version"], "3.0.0")
        rules = self.catalog["rules"]
        self.assertGreaterEqual(len(rules), 70, "Version 3 should contain the expanded audit coverage")

        valid_topics = {
            "Single Line Diagram",
            "Power Plan",
            "Lighting Plan",
            "Panel & Fixture Schedules",
            "Cover Sheet & General Notes",
            "Mechanical & Plumbing Coordination",
            "General Setup",
        }
        seen_ids = set()

        for rule in rules:
            for field in (
                "id",
                "title",
                "description",
                "codeCitation",
                "discipline",
                "severity",
                "topic",
                "whyItMatters",
                "order",
                "condition",
            ):
                self.assertIn(field, rule, f"Rule {rule.get('id', '<unknown>')} missing {field}")

            self.assertNotIn(rule["id"], seen_ids, f"Duplicate rule ID: {rule['id']}")
            seen_ids.add(rule["id"])
            self.assertIn(rule["topic"], valid_topics)
            self.assertIn(rule["severity"], ["Critical", "High", "Standard", "Aesthetic"])

            is_internal_standard = (
                "ACIES Standard" in rule["codeCitation"]
                or "BofA Prototype" in rule["codeCitation"]
            )
            if not is_internal_standard:
                self.assertGreater(
                    len(rule.get("exceptionsAndNuances", "")),
                    20,
                    f"Code-backed rule {rule['id']} needs useful exception guidance",
                )
                self.assertGreater(
                    len(rule.get("codeCycleNotes", "")),
                    20,
                    f"Code-backed rule {rule['id']} needs cycle guidance",
                )

            condition = rule.get("condition", {})
            referenced_flags = (
                condition.get("requiredFlags", [])
                + condition.get("anyFlags", [])
                + condition.get("excludedFlags", [])
            )
            for flag in referenced_flags:
                self.assertIn(flag, self.produced_flags, f"Rule {rule['id']} references unknown flag {flag}")

    def test_known_code_corrections_are_preserved(self):
        rules = {rule["id"]: rule for rule in self.catalog["rules"]}

        meeting = rules["elec_pwr_meeting_room_floor_boxes"]
        self.assertIn("Not More Than 1,000", meeting["title"])
        self.assertIn("not more than 1,000", meeting["description"])
        self.assertEqual(meeting["condition"]["requiredFlags"], ["NeedsMeetingRoomReceptacles"])

        floor_outlet = rules["elec_pwr_meeting_room_floor_outlet"]
        self.assertIn("215 sq ft", floor_outlet["description"])
        self.assertIn("12 ft", floor_outlet["description"])

        controlled = rules["elec_pwr_controlled_receptacles_t24"]
        self.assertNotIn("50%", controlled["title"] + controlled["description"])
        self.assertIn("within 6 ft", controlled["exceptionsAndNuances"])

        duct_smoke = rules["mech_coord_duct_smoke_detectors"]
        self.assertIn("Over 2,000 CFM", duct_smoke["title"])
        self.assertIn("CMC 609.1", duct_smoke["codeCitation"])
        self.assertNotIn("907.2.12.1.2", duct_smoke["codeCitation"])

        daylight = rules["ltg_t24_daylight_harvesting_zones"]
        self.assertIn("120 W", daylight["exceptionsAndNuances"])
        self.assertNotIn(">100 sq ft", daylight["title"] + daylight["description"])

        demand_response = rules["ltg_t24_demand_response_4000w"]
        self.assertIn("Over 4,000 W", demand_response["title"])
        self.assertIn("greater than 4,000 W", demand_response["description"])

        spd = rules["elec_sld_spd_service_entrance"]
        self.assertIn("not a blanket mandate", spd["exceptionsAndNuances"])
        self.assertEqual(
            set(spd["condition"]["anyFlags"]),
            {"NeedsDwellingServiceSpd", "NeedsEmergencySystemSpd"},
        )

        battery = rules["ltg_em_battery_units_90min"]
        self.assertIn("700.12(I)", battery["codeCitation"])
        self.assertIn("700.12(H)", battery["codeCitation"])

        pv = rules["elec_solar_pv_backfed_breaker"]
        bess = rules["elec_bess_storage_system"]
        self.assertEqual(pv["condition"]["requiredFlags"], ["NeedsSolarPvInterconnection"])
        self.assertEqual(bess["condition"]["requiredFlags"], ["NeedsBessReview"])

        serialized_catalog = json.dumps(self.catalog)
        self.assertNotIn("NeedsMeetingRoomFloorBoxes", serialized_catalog)
        self.assertNotIn("NeedsSolarPv120Rule", serialized_catalog)

    def blank_flags(self):
        return {flag: False for flag in self.produced_flags}

    @staticmethod
    def eval_rule(rule, scope, flags):
        condition = rule.get("condition", {})
        if any(not flags.get(flag, False) for flag in condition.get("requiredFlags", [])):
            return False
        if any(flags.get(flag, False) for flag in condition.get("excludedFlags", [])):
            return False
        any_flags = condition.get("anyFlags", [])
        if any_flags and not any(flags.get(flag, False) for flag in any_flags):
            return False
        if condition.get("allowedClients") and scope.get("clientStandard") not in condition["allowedClients"]:
            return False
        if condition.get("allowedPhases") and scope.get("phase") not in condition["allowedPhases"]:
            return False
        if condition.get("allowedDisciplines") and scope.get("discipline") not in condition["allowedDisciplines"]:
            return False
        if condition.get("emergencyPowerTypes") and scope.get("emergencyPowerType") not in condition["emergencyPowerTypes"]:
            return False
        return True

    def active_ids(self, scope, flags):
        return {
            rule["id"]
            for rule in self.catalog["rules"]
            if self.eval_rule(rule, scope, flags)
        }

    def test_corrected_scope_inference_and_exception_paths(self):
        scope = {
            "phase": "IFP / Permit",
            "discipline": "Electrical",
            "clientStandard": "Generic Commercial",
            "emergencyPowerType": "None",
        }

        # Mirrors a California first-time office with public access. Public access alone
        # must not activate 406.12, while the corrected 210.65 predicates both activate.
        flags = self.blank_flags()
        flags.update(
            {
                "NeedsControlledReceptacles": True,
                "NeedsTamperResistant": False,
                "NeedsMeetingRoomReceptacles": True,
                "NeedsMeetingRoomFloorOutlet": True,
            }
        )
        active = self.active_ids(scope, flags)
        self.assertIn("elec_pwr_controlled_receptacles_t24", active)
        self.assertNotIn("elec_pwr_tamper_resistant_receptacles", active)
        self.assertIn("elec_pwr_meeting_room_floor_boxes", active)
        self.assertIn("elec_pwr_meeting_room_floor_outlet", active)

        # An alteration/occupancy exception replaces the mandate with an evidence check.
        flags["NeedsControlledReceptacles"] = False
        flags["ControlledReceptaclesExempt"] = True
        active = self.active_ids(scope, flags)
        self.assertNotIn("elec_pwr_controlled_receptacles_t24", active)
        self.assertIn("elec_pwr_controlled_receptacle_exception", active)

        # Ensure the first-time tenant option used by the UI is included by the C# predicate.
        self.assertIn(
            '"First-Time Tenant Build-Out / Shell Completion"',
            self.engine_source,
        )
        self.assertIn(
            'flags["NeedsServiceEquipmentReceptacle"] = hasServiceWork;',
            self.engine_source,
        )
        self.assertIn(
            "uses2023Nec && scope.Has2023NecSpdSleepingOccupancy",
            self.engine_source,
        )

    def test_independent_systems_and_documented_exceptions(self):
        scope = {
            "phase": "IFP / Permit",
            "discipline": "Electrical",
            "clientStandard": "Generic Commercial",
            "emergencyPowerType": "Integral Emergency Battery Packs",
        }
        flags = self.blank_flags()
        flags.update(
            {
                "NeedsLocalAmendmentReview": True,
                "DaylightControlsExempt": True,
                "DemandResponseExempt": True,
                "ExteriorLightingControlsExempt": True,
                "NeedsDuctSmokeDetectors": True,
                "HasDuctSmokeAlternative": True,
                "NeedsEvInfrastructureReview": True,
                "NeedsEvChargingCalculations": False,
                "NeedsSolarPvInterconnection": True,
                "NeedsBessReview": False,
                "NeedsIntegralBatteryUnits": True,
                "NeedsEmergencyInverter": False,
                "NeedsExitSignReview": True,
                "NeedsEgressIllumination": False,
            }
        )
        active = self.active_ids(scope, flags)

        self.assertIn("gen_setup_ahj_local_amendments", active)
        self.assertIn("ltg_t24_daylight_exception", active)
        self.assertNotIn("ltg_t24_daylight_harvesting_zones", active)
        self.assertIn("ltg_t24_demand_response_exception", active)
        self.assertNotIn("ltg_t24_demand_response_4000w", active)
        self.assertIn("ltg_t24_exterior_control_exception", active)
        self.assertNotIn("ltg_t24_exterior_photocell_astronomical", active)
        self.assertIn("mech_coord_duct_smoke_alternative", active)
        self.assertNotIn("mech_coord_duct_smoke_detectors", active)

        self.assertIn("elec_ev_calgreen_infrastructure", active)
        self.assertNotIn("elec_ev_charging_infrastructure", active)
        self.assertIn("elec_solar_pv_backfed_breaker", active)
        self.assertNotIn("elec_bess_storage_system", active)

        self.assertIn("ltg_em_battery_units_90min", active)
        self.assertNotIn("ltg_em_inverter_circuit_unswitched", active)
        self.assertIn("ltg_em_exit_sign_single_vs_double_face", active)
        self.assertNotIn("ltg_em_egress_illumination_1fc", active)

    def test_audit_state_json_serialization(self):
        state_file = os.path.join(self.test_dir, "project_audit_state.json")
        sample_state = {
            "version": 3,
            "lastModifiedUtc": "2026-08-18T21:45:00Z",
            "scope": {
                "phase": "IFP / Permit",
                "discipline": "Electrical",
                "codeJurisdiction": "California (CEC 2025 / T24 2025)",
                "authorityHavingJurisdiction": "Sample City",
                "permitApplicationDate": "2026-08-18",
                "constructionScopeNature": "First-Time Tenant Build-Out / Shell Completion",
                "hasOfficeSpaces": True,
                "hasMeetingRoomsAtOrBelow1000SqFt": True,
                "hasRequiredExitSigns": True,
                "hasEmergencyEgressLighting": True,
            },
            "checks": {
                "elec_pwr_controlled_receptacles_t24": {
                    "isCompleted": True,
                    "completedAtUtc": "2026-08-18T21:46:00Z",
                    "notes": "Verified controlled-outlet proximity and workstation distribution",
                    "status": "Pass",
                }
            },
        }

        with open(state_file, "w", encoding="utf-8") as state_output:
            json.dump(sample_state, state_output, indent=2)
        with open(state_file, "r", encoding="utf-8") as state_input:
            loaded = json.load(state_input)

        self.assertEqual(loaded["version"], 3)
        self.assertEqual(loaded["scope"]["authorityHavingJurisdiction"], "Sample City")
        self.assertTrue(loaded["scope"]["hasMeetingRoomsAtOrBelow1000SqFt"])
        self.assertTrue(loaded["checks"]["elec_pwr_controlled_receptacles_t24"]["isCompleted"])


if __name__ == "__main__":
    unittest.main()
