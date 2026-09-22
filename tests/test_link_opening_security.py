"""Links and updates must not let content inside the window launch arbitrary programs."""
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _ensure_google_genai_stub():
    try:
        from google import genai as _genai  # noqa: F401
        from google.genai import types as _types  # noqa: F401
        return
    except Exception:
        google_module = sys.modules.get("google")
        if google_module is None:
            google_module = types.ModuleType("google")
            google_module.__path__ = []
            sys.modules["google"] = google_module

        genai_module = types.ModuleType("google.genai")
        genai_types_module = types.ModuleType("google.genai.types")
        genai_module.types = genai_types_module
        google_module.genai = genai_module

        sys.modules["google.genai"] = genai_module
        sys.modules["google.genai.types"] = genai_types_module


def _ensure_webview_stub():
    try:
        import webview  # noqa: F401
        return
    except Exception:
        webview_module = types.ModuleType("webview")
        webview_module.windows = []
        webview_module.create_window = lambda *args, **kwargs: None
        webview_module.start = lambda *args, **kwargs: None
        sys.modules["webview"] = webview_module


def _ensure_dotenv_stub():
    try:
        from dotenv import load_dotenv as _load_dotenv  # noqa: F401
        return
    except Exception:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: False
        sys.modules["dotenv"] = dotenv_module


def _ensure_requests_stub():
    try:
        import requests  # noqa: F401
        return
    except Exception:
        requests_module = types.ModuleType("requests")
        requests_module.get = lambda *args, **kwargs: None
        requests_module.post = lambda *args, **kwargs: None
        sys.modules["requests"] = requests_module


_ensure_google_genai_stub()
_ensure_webview_stub()
_ensure_dotenv_stub()
_ensure_requests_stub()

import main as main_module
from main import Api


@unittest.skipUnless(sys.platform == "win32", "Link opening uses os.startfile on Windows")
class LinkOpeningSecurityTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self._temp = tempfile.TemporaryDirectory(prefix="acies-links-")
        self.folder = Path(self._temp.name)
        startfile = patch.object(main_module.os, "startfile", create=True)
        self.startfile = startfile.start()
        self.addCleanup(startfile.stop)

    def tearDown(self):
        self._temp.cleanup()

    def _file(self, name):
        path = self.folder / name
        path.write_text("x", encoding="utf-8")
        return str(path)

    def test_protocol_handlers_other_than_web_and_email_are_refused(self):
        for url in ("javascript:alert(1)", "ms-msdt:/id PCWDiagnostic", "search-ms:query=x", "vbscript:x"):
            with self.subTest(url=url):
                self.assertEqual("error", self.api.open_url(url)["status"])
        self.startfile.assert_not_called()

    def test_web_and_email_links_open_normally(self):
        self.assertEqual("success", self.api.open_url("https://example.com/drawings")["status"])
        self.assertEqual("success", self.api.open_url("mailto:pm@example.com")["status"])
        self.assertEqual(2, self.startfile.call_count)

    def test_windows_paths_passed_as_links_go_through_open_path(self):
        document = self._file("Plan Check Comments.pdf")
        self.assertEqual("success", self.api.open_url(document)["status"])
        self.startfile.assert_called_once_with(os.path.normpath(document))

    def test_documents_and_folders_open_without_a_prompt(self):
        with patch.object(Api, "_confirm_with_native_dialog") as confirm:
            self.assertEqual("success", self.api.open_path(self._file("E01.00.dwg"))["status"])
            self.assertEqual("success", self.api.open_path(str(self.folder))["status"])
        confirm.assert_not_called()
        self.assertEqual(2, self.startfile.call_count)

    def test_programs_only_run_after_the_user_confirms(self):
        program = self._file("payload.exe")
        with patch.object(Api, "_confirm_with_native_dialog", return_value=False) as confirm:
            self.assertEqual("cancelled", self.api.open_path(program)["status"])
            self.assertEqual("cancelled", self.api.open_url(Path(program).as_uri())["status"])
        self.assertEqual(2, confirm.call_count)
        self.startfile.assert_not_called()

        with patch.object(Api, "_confirm_with_native_dialog", return_value=True):
            self.assertEqual("success", self.api.open_path(program)["status"])
        self.startfile.assert_called_once_with(os.path.normpath(program))

    def test_shortcuts_prompt_only_when_they_point_at_a_program(self):
        shortcut = self._file("Server folder.lnk")
        with patch.object(Api, "_confirm_with_native_dialog", return_value=False) as confirm:
            with patch.object(Api, "_resolve_shortcut_target", return_value=str(self.folder)):
                self.assertEqual("success", self.api.open_path(shortcut)["status"])
            confirm.assert_not_called()
            with patch.object(Api, "_resolve_shortcut_target", return_value=r"C:\Windows\System32\cmd.exe"):
                self.assertEqual("cancelled", self.api.open_path(shortcut)["status"])
            with patch.object(Api, "_resolve_shortcut_target", return_value=""):
                self.assertEqual("cancelled", self.api.open_path(shortcut)["status"])
        self.assertEqual(2, confirm.call_count)


class _FakeDownload:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield self.body


class AppUpdaterSecurityTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.app_update_repo = "jacobhusband/ProjectManagement"
        self.api.app_installer_name = "acies-scheduler-setup-test.exe"
        self.installer = b"installer bytes"
        self.release_url = (
            "https://github.com/jacobhusband/ProjectManagement/releases/download/v9.9.9/"
            "acies-scheduler-setup.exe"
        )
        popen = patch.object(main_module.subprocess, "Popen")
        self.popen = popen.start()
        self.addCleanup(popen.stop)
        self.addCleanup(
            lambda: (Path(tempfile.gettempdir()) / self.api.app_installer_name).unlink(missing_ok=True)
        )

    def _release(self, digest=""):
        return {"download_url": self.release_url, "digest": digest, "latest_version": "9.9.9"}

    def test_updater_downloads_the_published_installer_not_a_url_from_the_page(self):
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            return _FakeDownload(self.installer)

        with patch.object(Api, "_fetch_latest_release", return_value=self._release()), \
                patch.object(main_module.requests, "get", side_effect=fake_get):
            result = self.api.download_and_install_app_update("https://evil.example/payload.exe")

        self.assertEqual("success", result["status"])
        self.assertEqual([self.release_url], requested)
        self.popen.assert_called_once()

    def test_updater_refuses_downloads_from_outside_the_release_repo(self):
        release = self._release()
        release["download_url"] = "https://evil.example/acies-scheduler-setup.exe"
        with patch.object(Api, "_fetch_latest_release", return_value=release), \
                patch.object(main_module.requests, "get") as get:
            result = self.api.download_and_install_app_update()

        self.assertEqual("error", result["status"])
        get.assert_not_called()
        self.popen.assert_not_called()

    def test_updater_does_not_run_an_installer_that_fails_the_digest_check(self):
        with patch.object(Api, "_fetch_latest_release", return_value=self._release("sha256:" + "0" * 64)), \
                patch.object(main_module.requests, "get", return_value=_FakeDownload(self.installer)):
            result = self.api.download_and_install_app_update()

        self.assertEqual("error", result["status"])
        self.popen.assert_not_called()
        self.assertFalse((Path(tempfile.gettempdir()) / self.api.app_installer_name).exists())

    def test_updater_runs_an_installer_that_matches_the_digest(self):
        digest = "sha256:" + hashlib.sha256(self.installer).hexdigest()
        with patch.object(Api, "_fetch_latest_release", return_value=self._release(digest)), \
                patch.object(main_module.requests, "get", return_value=_FakeDownload(self.installer)):
            result = self.api.download_and_install_app_update()

        self.assertEqual("success", result["status"])
        self.popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
