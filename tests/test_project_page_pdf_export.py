import base64
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _ensure_optional_dependency_stubs():
    try:
        from google import genai as _genai  # noqa: F401
        from google.genai import types as _types  # noqa: F401
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

    try:
        import webview  # noqa: F401
    except Exception:
        webview_module = types.ModuleType("webview")
        webview_module.windows = []
        webview_module.create_window = lambda *args, **kwargs: None
        webview_module.start = lambda *args, **kwargs: None
        sys.modules["webview"] = webview_module

    try:
        from dotenv import load_dotenv as _load_dotenv  # noqa: F401
    except Exception:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: False
        sys.modules["dotenv"] = dotenv_module


_ensure_optional_dependency_stubs()

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz
import main as main_module
from main import Api


_PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_PNG_DATA_URL = "data:image/png;base64," + _PNG_1X1_B64


class ProjectPagePdfExportTests(unittest.TestCase):
    def test_theme_colors_resolve_to_print_colors(self):
        renderer = main_module._ProjectPagePdfHtmlRenderer(lambda _: None)
        renderer.feed('<p><span style="color:var(--notes-color-blue)">Blue note</span></p>')
        renderer.close()
        self.assertIn("#205c96", renderer.rendered_html())
        self.assertNotIn("var(--notes-color", renderer.rendered_html())

    def setUp(self):
        self.api = Api.__new__(Api)

    @staticmethod
    def _patched_data_path(temp_dir):
        return patch.object(
            main_module,
            "get_app_data_path",
            lambda name="tasks.json": str(Path(temp_dir) / name),
        )

    def test_publish_project_page_pdf_renders_rich_content_and_image(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-pdf-") as temp_dir:
            output_path = Path(temp_dir) / "Coordination Notes.pdf"
            with self._patched_data_path(temp_dir):
                saved_image = self.api.save_page_asset(
                    "proj_260243",
                    _PNG_DATA_URL,
                    "diagram.png",
                )
                self.assertEqual("success", saved_image["status"])

                result = self.api.publish_project_page_pdf({
                    "outputPath": str(output_path),
                    "kind": "subpage",
                    "title": "Coordination Notes",
                    "projectName": "260243 Example Project",
                    "html": (
                        "<h1>Electrical scope</h1>"
                        "<p>Coordinate the <strong>service equipment</strong>.</p>"
                        '<ul data-type="taskList">'
                        '<li data-type="taskItem" data-checked="true">'
                        "<label><input type=\"checkbox\" checked></label>"
                        "<div><p>Confirm utility location</p></div>"
                        "</li></ul>"
                        '<div class="page-callout" data-callout-color="blue">'
                        "<p>Issue before permit.</p></div>"
                        '<details data-type="details" open="open">'
                        '<summary data-type="detailsSummary">Design notes</summary>'
                        '<div data-type="detailsContent"><p>Keep working clearance.</p></div>'
                        "</details>"
                        "<table><tr><th>Item</th><th>Status</th></tr>"
                        "<tr><td>Meter</td><td>Reviewed</td></tr></table>"
                        f'<img data-asset="{saved_image["assetPath"]}" '
                        'data-width-percent="65" alt="Diagram">'
                        '<div class="page-workbook" '
                        'data-page-file="page_files/proj_260243/id/Load Calculations.xlsx" '
                        'data-file-name="Load Calculations.xlsx">'
                        '<span>Load Calculations.xlsx</span>'
                        '<button>Open</button><button>Delete</button></div>'
                    ),
                })

            self.assertEqual("success", result["status"])
            self.assertEqual(output_path.resolve(), Path(result["path"]).resolve())
            self.assertGreater(result["sizeBytes"], 0)
            self.assertTrue(output_path.is_file())

            with fitz.open(output_path) as document:
                self.assertGreaterEqual(len(document), 1)
                text = "\n".join(page.get_text() for page in document)
                self.assertIn("Coordination Notes", text)
                self.assertIn("260243 Example Project", text)
                self.assertIn("Electrical scope", text)
                self.assertIn("[x]", text)
                self.assertIn("utility location", text)
                self.assertIn("Issue before permit.", text)
                self.assertIn("Design notes", text)
                self.assertIn("Keep working clearance.", text)
                self.assertIn("Excel workbook: Load Calculations.xlsx", text)
                self.assertNotIn("OpenDelete", text)
                self.assertIn("Page 1 of", text)
                self.assertTrue(
                    any(page.get_images(full=True) for page in document),
                    "The published PDF should include stored page images.",
                )

    def test_publish_project_page_pdf_appends_pdf_extension(self):
        with tempfile.TemporaryDirectory(prefix="acies-page-pdf-extension-") as temp_dir:
            output_without_extension = Path(temp_dir) / "Project Overview"
            result = self.api.publish_project_page_pdf({
                "outputPath": str(output_without_extension),
                "kind": "project",
                "title": "Project Overview",
                "html": "<p>Ready to issue.</p>",
            })

            expected_path = output_without_extension.with_suffix(".pdf")
            self.assertEqual("success", result["status"])
            self.assertEqual(expected_path.resolve(), Path(result["path"]).resolve())
            self.assertTrue(expected_path.is_file())


if __name__ == "__main__":
    unittest.main()
