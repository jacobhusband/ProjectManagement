import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ELECTRICAL_COMMANDS_ROOT = REPO_ROOT.parent / "ElectricalCommands"
COMMAND_PATH = (
    ELECTRICAL_COMMANDS_ROOT
    / "AutoCADCommands"
    / "LFSCommands"
    / "LightingPlanCommands.cs"
)


@unittest.skipUnless(
    ELECTRICAL_COMMANDS_ROOT.is_dir(),
    "Cross-repo contract test: needs the sibling ElectricalCommands checkout",
)
class LightingPlanAutocadBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command_source = COMMAND_PATH.read_text(encoding="utf-8")
        cls.project_source = (
            COMMAND_PATH.parent / "AutoCADCommands.LFSCommands.csproj"
        ).read_text(encoding="utf-8")
        cls.descriptions = json.loads(
            (COMMAND_PATH.parent / "LFSCommands_descriptions.json").read_text(
                encoding="utf-8"
            )
        )

    def test_scan_and_apply_commands_are_registered_and_packaged(self):
        for command in ("LIGHTPLANSCAN", "LPSCAN", "LIGHTPLANAPPLY", "LPAPPLY"):
            self.assertIn(f'[CommandMethod("{command}"', self.command_source)
            self.assertIn(command, self.descriptions["commands"])
        self.assertIn('<Compile Include="LightingPlanCommands.cs" />', self.project_source)

    def test_scan_exports_configurable_rooms_fixtures_and_attributes(self):
        self.assertIn("ACIESLightingPlan.snapshot.json", self.command_source)
        self.assertIn("ACIESLightingPlan.config.json", self.command_source)
        self.assertIn("RoomBoundaryLayerPatterns", self.command_source)
        self.assertIn("FixtureBlockPatterns", self.command_source)
        self.assertIn("ReadBlockAttributes", self.command_source)
        self.assertIn("FingerprintGuid", self.command_source)

    def test_apply_is_idempotent_and_only_removes_managed_stale_tags(self):
        self.assertIn('LightingPlanRegAppName = "ACIES_LIGHTING_PLAN"', self.command_source)
        self.assertIn("FindExistingLightingPlanTags", self.command_source)
        self.assertIn("SetLightingPlanXData", self.command_source)
        self.assertIn("desiredKeys.Contains(pair.Key)", self.command_source)
        self.assertIn("RemoveStaleGeneratedTags", self.command_source)


if __name__ == "__main__":
    unittest.main()

