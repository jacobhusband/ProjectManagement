"""Guards the work that keeps application startup fast.

Startup used to wait on network calls, per-project SQLite connections and imports
of libraries that only a few features use. These tests fail if that work moves back
onto the path that opens the window and renders the first screen.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as main_module  # noqa: E402
from main import Api  # noqa: E402

INDEX_HTML = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
SCRIPT_JS = (REPO_ROOT / "script.js").read_text(encoding="utf-8")
BOOTSTRAP_JS = (REPO_ROOT / "app-bootstrap.js").read_text(encoding="utf-8")


def _init_function_source():
    start = SCRIPT_JS.index("async function init() {")
    end = SCRIPT_JS.index("// ===================== NOTION-STYLE PROJECT NOTES PAGES", start)
    return SCRIPT_JS[start:end]


class LightingScheduleOverlayTests(unittest.TestCase):
    def test_overlay_shares_one_connection_across_all_projects(self):
        with tempfile.TemporaryDirectory(prefix="acies-startup-") as temp_dir:
            db_path = str(Path(temp_dir) / "lighting_schedules.db")
            project_ids = [f"26000{index}" for index in range(6)]
            with patch.object(main_module, "LIGHTING_SCHEDULE_DB_FILE", db_path):
                for project_id in project_ids:
                    main_module._save_lighting_schedule_record(
                        project_id,
                        {"schedule": {"rows": [{"mark": f"L{project_id}"}]}},
                    )
                projects = [{"id": project_id, "name": project_id} for project_id in project_ids]

                with patch.object(
                    main_module,
                    "_open_lighting_schedule_db",
                    wraps=main_module._open_lighting_schedule_db,
                ) as open_db:
                    main_module._overlay_projects_with_lighting_schedule_records(projects)

            # One connection per project cost ~1.6s for a 194-project tasks.json.
            self.assertEqual(1, open_db.call_count)
            for project, project_id in zip(projects, project_ids):
                schedule = project["lightingSchedule"]
                self.assertEqual(f"L{project_id}", schedule["rows"][0]["mark"])
                self.assertIn("_storeVersion", schedule)

    def test_single_lookups_still_open_their_own_connection(self):
        with tempfile.TemporaryDirectory(prefix="acies-startup-") as temp_dir:
            db_path = str(Path(temp_dir) / "lighting_schedules.db")
            with patch.object(main_module, "LIGHTING_SCHEDULE_DB_FILE", db_path):
                main_module._save_lighting_schedule_record(
                    "260100", {"schedule": {"rows": [{"mark": "A"}]}}
                )
                record = main_module._get_lighting_schedule_record("260100")
                missing = main_module._get_lighting_schedule_record("does-not-exist")

            self.assertEqual("A", record["schedule"]["rows"][0]["mark"])
            self.assertIsNone(missing)


class GoogleAuthStateTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.record = {
            "provider": "google",
            "email": "user@example.com",
            "displayName": "User Example",
            "refreshToken": "refresh-token",
            "expiresAt": "2000-01-01T00:00:00Z",
        }

    def test_startup_read_never_renews_the_token(self):
        with patch.object(
            self.api, "_load_google_auth_record", return_value=self.record
        ), patch.object(
            self.api, "_refresh_google_auth_record_if_needed"
        ) as refresh:
            state = self.api.get_google_auth_state(refresh=False)

        refresh.assert_not_called()
        self.assertEqual("success", state["status"])
        self.assertTrue(state["auth"]["signedIn"])
        self.assertEqual("user@example.com", state["auth"]["email"])

    def test_default_call_still_renews_an_expiring_token(self):
        renewed = {**self.record, "expiresAt": "2999-01-01T00:00:00Z"}
        with patch.object(
            self.api, "_load_google_auth_record", return_value=self.record
        ), patch.object(
            self.api, "_refresh_google_auth_record_if_needed", return_value=renewed
        ) as refresh:
            state = self.api.get_google_auth_state()

        refresh.assert_called_once_with(self.record)
        self.assertEqual("2999-01-01T00:00:00Z", state["auth"]["expiresAt"])

    def test_a_revoked_token_signs_the_user_out(self):
        with patch.object(
            self.api, "_load_google_auth_record", return_value=self.record
        ), patch.object(
            self.api, "_refresh_google_auth_record_if_needed", return_value=None
        ):
            state = self.api.get_google_auth_state()

        self.assertFalse(state["auth"]["signedIn"])


class LazyModuleTests(unittest.TestCase):
    def test_module_loads_once_on_first_use(self):
        calls = []
        fake = types.SimpleNamespace(answer=42)

        def loader():
            calls.append(1)
            return fake

        lazy = main_module._LazyModule(loader)
        self.assertEqual([], calls)
        self.assertEqual(42, lazy.answer)
        self.assertIs(fake, lazy.preload())
        self.assertEqual(42, lazy.answer)
        self.assertEqual([1], calls)

    def test_attributes_can_be_patched_and_restored(self):
        lazy = main_module._LazyModule(lambda: types.SimpleNamespace(post="real"))
        with patch.object(lazy, "post", "fake"):
            self.assertEqual("fake", lazy.post)
        self.assertEqual("real", lazy.post)

    def test_missing_attribute_raises_attribute_error(self):
        lazy = main_module._LazyModule(lambda: types.SimpleNamespace())
        with self.assertRaises(AttributeError):
            lazy.nope

    def test_slow_libraries_stay_unloaded_after_importing_main(self):
        slow = ("google.genai", "openpyxl", "cv2", "pymupdf", "requests")
        with tempfile.TemporaryDirectory(prefix="acies-import-") as profile:
            env = {
                **os.environ,
                "USERPROFILE": profile,
                "APPDATA": str(Path(profile) / "AppData" / "Roaming"),
                "ACIES_NONINTERACTIVE": "1",
            }
            script = (
                "import json, sys, main; "
                f"print(json.dumps([m for m in {slow!r} if m in sys.modules]))"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], json.loads(result.stdout.strip().splitlines()[-1]))


class PageStartupMarkupTests(unittest.TestCase):
    def test_head_has_no_blocking_remote_script_or_stylesheet(self):
        head = INDEX_HTML[: INDEX_HTML.index("</head>")]
        self.assertEqual([], re.findall(r'<script\b[^>]*\ssrc="https?://', head))
        remote_sheets = [
            tag
            for tag in re.findall(r"<link\b[^>]*>", head)
            if 'rel="stylesheet"' in tag and re.search(r'href="https?://', tag)
        ]
        self.assertTrue(remote_sheets, "expected the Google Fonts stylesheets")
        for tag in remote_sheets:
            with self.subTest(tag=tag[:80]):
                self.assertIn('media="print"', tag)
                self.assertIn("data-async-stylesheet", tag)

    def test_bootstrap_switches_async_stylesheets_to_all_media(self):
        self.assertIn("link[data-async-stylesheet]", BOOTSTRAP_JS)
        self.assertIn("link.media = 'all'", BOOTSTRAP_JS)
        self.assertIn("link.sheet", BOOTSTRAP_JS)

    def test_chart_js_is_vendored_and_loads_on_demand(self):
        chart_tags = [
            tag for tag in re.findall(r"<script\b[^>]*>", INDEX_HTML) if "chart" in tag.lower()
        ]
        self.assertEqual([], chart_tags)
        url = re.search(r'const CHART_JS_URL =\s*"([^"]+)"', SCRIPT_JS).group(1)
        # A file that ships with the app, so Stats works offline and needs no CDN.
        self.assertFalse(url.startswith(("http:", "https:", "//")), url)
        self.assertTrue((REPO_ROOT / url.split("?")[0]).is_file(), url)
        # The first open of the Stats dialog loads the library, then draws.
        draw = SCRIPT_JS[SCRIPT_JS.index("function renderStatsChart("):]
        self.assertLess(draw.index("if (!window.Chart) {"), draw.index("new Chart("))

    def test_policy_allows_scripts_from_the_app_only(self):
        policy = re.search(
            r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', INDEX_HTML
        ).group(1)
        script_src = next(
            part.split()[1:] for part in policy.split(";") if part.split()[:1] == ["script-src"]
        )
        self.assertEqual(["'self'"], script_src)

    def test_vendored_chart_js_matches_the_recorded_hash(self):
        readme = (REPO_ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
        recorded = re.search(r"SHA-384: `(sha384-[A-Za-z0-9+/=]+)`", readme).group(1)
        payload = (REPO_ROOT / "vendor" / "chart.umd.min.js").read_bytes()
        actual = "sha384-" + base64.b64encode(hashlib.sha384(payload).digest()).decode("ascii")
        self.assertEqual(recorded, actual)

    def test_vendored_chart_js_ships_in_every_build_definition(self):
        for name in (
            "ACIES Scheduler.spec",
            "build-config/ACIES Scheduler.spec",
            "build-config/build.ps1",
        ):
            with self.subTest(file=name):
                text = (REPO_ROOT / name).read_text(encoding="utf-8")
                self.assertRegex(text, r"chart\.umd\.min\.js")


class EntryPointTests(unittest.TestCase):
    """Running main.py directly recompiles it on every launch (~0.6s)."""

    def test_launch_script_imports_main_and_calls_run(self):
        launch = (REPO_ROOT / "launch.py").read_text(encoding="utf-8")
        self.assertIn("import main", launch)
        self.assertIn("main.run()", launch)

    def test_main_still_starts_when_run_as_a_script(self):
        source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertRegex(source, r"\ndef run\(\):\r?\n")
        # The PyInstaller build and `python main.py` both run main.py as __main__.
        self.assertRegex(source, r"if __name__ == '__main__':\r?\n    run\(\)")
        self.assertTrue(callable(main_module.run))

    def test_launchers_start_launch_py(self):
        run_cmd = (REPO_ROOT / "run.cmd").read_text(encoding="utf-8")
        self.assertIn("launch.py", run_cmd)
        self.assertNotIn("main.py", run_cmd.replace("running main.py", ""))
        launcher = (REPO_ROOT / "scripts" / "launcher.cs").read_text(encoding="utf-8-sig")
        self.assertIn('Path.Combine(baseDir, "launch.py")', launcher)
        # Older checkouts without launch.py still start.
        self.assertIn('Path.Combine(baseDir, "main.py")', launcher)


class LogoAssetTests(unittest.TestCase):
    def test_logo_is_the_cropped_wordmark_and_stays_small(self):
        from PIL import Image

        logo = REPO_ROOT / "assets" / "acies-modern-logo.png"
        with Image.open(logo) as image:
            size = image.size
        # It used to be a 1.4 MB, 1774x887 bitmap of which the page showed 1110x390.
        self.assertLess(logo.stat().st_size, 100 * 1024)
        tags = re.findall(r'<img src="assets/acies-modern-logo\.png"[^>]*>', INDEX_HTML)
        self.assertEqual(2, len(tags))
        for tag in tags:
            with self.subTest(tag=tag):
                self.assertIn(f'width="{size[0]}"', tag)
                self.assertIn(f'height="{size[1]}"', tag)

    def test_logo_css_fills_the_box_instead_of_cropping_a_larger_bitmap(self):
        css = (REPO_ROOT / "modern-workspace.css").read_text(encoding="utf-8")
        rule = re.search(r"\.brand-mark\.supplied-logo img \{([^}]*)\}", css).group(1)
        self.assertIn("width: 100%;", rule)
        self.assertIn("left: 0;", rule)
        self.assertIn("top: 0;", rule)
        self.assertIn("filter: url(#acies-logo-ink);", rule)

    def test_boot_reads_google_sign_in_locally_and_renews_it_afterwards(self):
        init = _init_function_source()
        self.assertIn("await loadGoogleAuthState({ silent: true, refresh: false });", init)
        # The renewal must not be awaited, or it would hold up the first render again.
        self.assertIn("void refreshGoogleAuthStateInBackground();", init)
        self.assertNotIn("await refreshGoogleAuthStateInBackground", init)
        self.assertLess(
            init.index("render();"), init.index("void refreshGoogleAuthStateInBackground();")
        )
        self.assertIn("api.get_google_auth_state(refresh)", SCRIPT_JS)

    def test_background_renewal_keeps_the_settings_copy_in_step(self):
        start = SCRIPT_JS.index("async function refreshGoogleAuthStateInBackground() {")
        body = SCRIPT_JS[start : SCRIPT_JS.index("function openGoogleAccountDialog()", start)]
        self.assertIn("await loadGoogleAuthState({ silent: true });", body)
        self.assertIn("api.get_user_settings()", body)
        self.assertIn("userSettings.googleAuth =", body)


if __name__ == "__main__":
    unittest.main()
