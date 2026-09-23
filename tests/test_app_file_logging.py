"""The installed app has no console, so errors must reach a log file."""
import logging
import sys
import tempfile
import threading
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


_ensure_google_genai_stub()
_ensure_webview_stub()
_ensure_dotenv_stub()

import main as main_module


class AppLoggingSetupTests(unittest.TestCase):
    def test_info_messages_are_kept_and_http_request_logs_are_not(self):
        # A logging call during import used to lock the root logger at WARNING.
        self.assertLessEqual(logging.getLogger().level, logging.INFO)
        for name in ("httpx", "httpcore"):
            self.assertEqual(logging.WARNING, logging.getLogger(name).level)

    def test_problems_reported_by_the_page_are_logged_briefly(self):
        api = main_module.Api.__new__(main_module.Api)
        with self.assertLogs(level="WARNING") as captured:
            result = api.report_client_issue({
                "kind": "csp-violation",
                "directive": "script-src-elem",
                "sample": "x" * 5000,
            })

        self.assertEqual("success", result["status"])
        self.assertEqual(1, len(captured.records))
        message = captured.records[0].getMessage()
        self.assertIn("csp-violation", message)
        self.assertIn("script-src-elem", message)
        self.assertLess(len(message), 1000)


class AppFileLoggingTests(unittest.TestCase):
    def test_errors_and_uncaught_thread_exceptions_are_written_to_the_log_file(self):
        root_logger = logging.getLogger()
        handlers_before = list(root_logger.handlers)
        excepthook_before = sys.excepthook
        thread_excepthook_before = threading.excepthook
        with tempfile.TemporaryDirectory(prefix="acies-logs-") as temp_dir:
            try:
                with patch.object(main_module, "get_app_data_dir", return_value=temp_dir):
                    log_path = main_module._configure_file_logging()

                logging.error("Saving tasks failed: disk full")
                worker = threading.Thread(target=lambda: 1 / 0, name="api-worker")
                worker.start()
                worker.join()
                for handler in root_logger.handlers:
                    handler.flush()

                self.assertEqual(Path(temp_dir) / "logs" / main_module.APP_LOG_FILE_NAME, Path(log_path))
                text = Path(log_path).read_text(encoding="utf-8")
                self.assertIn("Saving tasks failed: disk full", text)
                self.assertIn("Uncaught exception in thread api-worker", text)
                self.assertIn("ZeroDivisionError", text)
            finally:
                for handler in list(root_logger.handlers):
                    if handler not in handlers_before:
                        root_logger.removeHandler(handler)
                        handler.close()
                sys.excepthook = excepthook_before
                threading.excepthook = thread_excepthook_before


if __name__ == "__main__":
    unittest.main()
