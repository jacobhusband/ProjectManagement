"""The public installer must not carry secrets, and releases should have real notes.

The installer is attached to a public GitHub release, and PyInstaller copies .env
into it, so whatever release.yml writes to .env can be read by anyone.
"""
import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
BUILD_SCRIPT = REPO_ROOT / "build-config" / "build.ps1"


def release_steps():
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["release"]["steps"]


def step_named(name):
    return next(step for step in release_steps() if step.get("name") == name)


class ReleaseEnvTests(unittest.TestCase):
    def test_the_installer_env_carries_no_gemini_key(self):
        text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("GOOGLE_API_KEY", text)
        self.assertNotIn("GEMINI_API_KEY", text)

    def test_the_installer_env_only_has_the_sign_in_client(self):
        step = step_named("Create release .env")
        self.assertEqual({"GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID"}, set(step["env"]))
        written = set(re.findall(r"^\s*(GOOGLE_[A-Z_]+)\s*=", step["run"], flags=re.MULTILINE))
        self.assertEqual({"GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID"}, written)

    def test_a_local_build_warns_when_it_would_bundle_a_key(self):
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("GOOGLE_API_KEY", text)
        self.assertIn("Write-Warning", text)
        # The warning must come before PyInstaller copies .env into the bundle.
        self.assertLess(text.index("Write-Warning"), text.index("PyInstaller build"))


class ReleaseNotesTests(unittest.TestCase):
    def test_notes_are_looked_up_before_the_release_is_published(self):
        names = [step.get("name") for step in release_steps()]
        self.assertLess(names.index("Find release notes"), names.index("Publish GitHub release"))

    def test_the_release_uses_the_notes_file_and_keeps_the_generated_notes(self):
        publish = step_named("Publish GitHub release")["with"]
        self.assertEqual("${{ steps.notes.outputs.path }}", publish["body_path"])
        self.assertTrue(publish["generate_release_notes"])

    def test_the_notes_step_reads_a_file_named_after_the_tag(self):
        step = step_named("Find release notes")
        self.assertEqual("notes", step["id"])
        self.assertIn("release-notes/$env:GITHUB_REF_NAME.md", step["run"])
        # GitHub reads GITHUB_OUTPUT as UTF-8; a bare `>>` is UTF-16 in Windows PowerShell.
        self.assertIn("-Encoding utf8", step["run"])

    def test_the_current_release_has_notes_written_for_people(self):
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        notes = REPO_ROOT / "release-notes" / f"v{version}.md"
        if not notes.exists():
            self.skipTest(f"No notes yet for {version}; the release workflow will warn.")
        text = notes.read_text(encoding="utf-8")
        self.assertIn(f"## ACIES Scheduler {version}", text)
        self.assertGreater(len(text.strip()), 200, "The notes look like a stub.")
        self.assertNotIn("TODO", text)


class InstallerSmokeTests(unittest.TestCase):
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "installer-smoke.yml"
    SCRIPT = REPO_ROOT / "build-config" / "smoke-test-installer.ps1"

    def workflow(self):
        return yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))

    def test_it_runs_after_every_release_build_and_on_demand(self):
        # PyYAML reads the bare key `on` as the boolean True.
        triggers = self.workflow().get("on") or self.workflow().get(True)
        self.assertEqual(["Build and Release"], triggers["workflow_run"]["workflows"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertIn("build-config/smoke-test-installer.ps1", triggers["push"]["paths"])

    def test_it_only_tests_a_release_that_was_published(self):
        condition = self.workflow()["jobs"]["smoke"]["if"]
        self.assertIn("github.event.workflow_run.conclusion == 'success'", condition)

    def test_it_covers_two_windows_generations_and_a_pc_without_webview2(self):
        job = self.workflow()["jobs"]["smoke"]
        self.assertEqual("${{ matrix.os }}", job["runs-on"])
        legs = job["strategy"]["matrix"]["include"]
        self.assertFalse(job["strategy"]["fail-fast"])
        self.assertGreaterEqual(len({leg["os"] for leg in legs}), 2)
        self.assertIn("missing", {leg["webview2"] for leg in legs})
        self.assertIn("-SimulateMissingWebView2", self.WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("SimulateMissingWebView2", self.SCRIPT.read_text(encoding="utf-8"))

    def test_it_installs_the_published_installer_on_a_fresh_windows_vm(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("releases/latest/download/acies-scheduler-setup.exe", text)
        self.assertIn("smoke-test-installer.ps1", text)

    def test_the_script_covers_what_a_new_user_hits(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        for expected in (
            "Get-PathWithoutPython",       # the helpers must work with no Python on PATH
            "acies-pdf-tools.exe",
            "PlotDWGs.ps1",
            "Get-WebView2Version",
            "Fetching bundle statuses",    # proof the page reached Python
            "unins",                       # it uninstalls again
            "Write-Annotation",            # the job log needs a sign-in, annotations do not
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        # The published installer must not carry a Gemini key (releases from 2.1.1 on).
        self.assertIn("The installer carries no Gemini API key", text)
        self.assertIn('[version]"2.1.1"', text)
        # Setup must never run on a PC that already has the app unless the caller asked for it.
        self.assertIn("-InstallerPath", text)
        self.assertIn("-AppDir", text)


if __name__ == "__main__":
    unittest.main()
