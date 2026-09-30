"""The publish script's PDF steps must not need a Python install on the user's PATH.

scripts/pdf_helper_runner.py is what the PyInstaller build ships as acies-pdf-tools.exe.
These tests run it the way PlotDWGs.ps1 does: `<interpreter> <script> <arguments>`.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz  # PyMuPDF, also what the helper scripts use

import main as main_module

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
RUNNER = SCRIPTS_DIR / "pdf_helper_runner.py"


def make_pdf(path, pages=1, size=(2592, 3456)):
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=size[0], height=size[1])
        page.insert_text((72, 72), f"page {index + 1}")
    document.save(str(path))
    document.close()
    return path


def run_runner(*args):
    return subprocess.run(
        [sys.executable, str(RUNNER), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=120,
    )


class PdfHelperRunnerTests(unittest.TestCase):
    def test_merges_pdfs_like_python_would(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-runner-") as temp_dir:
            root = Path(temp_dir)
            first = make_pdf(root / "a.pdf", pages=1)
            second = make_pdf(root / "b.pdf", pages=2)
            merged = root / "combined.pdf"

            # PlotDWGs.ps1 passes the full path to the script; only its name matters.
            result = run_runner(SCRIPTS_DIR / "merge_pdfs.py", merged, first, second)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("Successfully merged 2 PDF(s)", result.stdout)
            with fitz.open(str(merged)) as document:
                self.assertEqual(3, len(document))

    def test_shrinks_a_pdf(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-runner-") as temp_dir:
            root = Path(temp_dir)
            source = make_pdf(root / "full.pdf")
            output = root / "small.pdf"

            result = run_runner(SCRIPTS_DIR / "shrink_pdf.py", source, output, 50)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(output.is_file())

    def test_strips_layers_and_reports_success(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-runner-") as temp_dir:
            source = make_pdf(Path(temp_dir) / "plain.pdf")

            result = run_runner(SCRIPTS_DIR / "strip_pdf_layers.py", source)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("PDF layer cleanup", result.stdout)

    def test_detects_no_paper_size_without_project_pdfs(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-runner-") as temp_dir:
            drawing = Path(temp_dir) / "Electrical" / "E1.dwg"
            drawing.parent.mkdir()
            drawing.write_bytes(b"")

            result = run_runner(SCRIPTS_DIR / "detect_pdf_size.py", drawing)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            # PlotDWGs.ps1 reads this stdout as the paper size, so nothing else may
            # be printed (importing PyMuPDF as "fitz" prints a deprecation warning).
            self.assertEqual("", result.stdout.strip())

    def test_a_helper_keeps_its_own_exit_code(self):
        # merge_pdfs.py exits 1 when it is given no output path; PlotDWGs.ps1 relies on that.
        result = run_runner(SCRIPTS_DIR / "merge_pdfs.py")

        self.assertEqual(1, result.returncode)
        self.assertIn("Usage:", result.stderr)

    def test_refuses_scripts_that_are_not_pdf_helpers(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-runner-") as temp_dir:
            stray = Path(temp_dir) / "evil.py"
            stray.write_text("open('ran.txt', 'w').write('x')", encoding="utf-8")

            result = run_runner(stray)

            self.assertEqual(2, result.returncode)
            self.assertIn("Unknown helper", result.stderr)
            self.assertFalse((Path(temp_dir) / "ran.txt").exists())
            self.assertFalse(Path("ran.txt").exists())

    def test_prints_usage_without_arguments(self):
        result = run_runner()

        self.assertEqual(2, result.returncode)
        self.assertIn("Usage:", result.stderr)


class ResolvePdfHelperPythonTests(unittest.TestCase):
    def test_source_run_uses_the_running_interpreter(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(sys.executable, main_module.resolve_pdf_helper_python())

    def test_windowed_python_is_swapped_for_the_console_one(self):
        # PowerShell does not wait for, or read the output of, pythonw.exe.
        with tempfile.TemporaryDirectory(prefix="acies-pdf-python-") as temp_dir:
            root = Path(temp_dir)
            windowed = root / "pythonw.exe"
            console = root / "python.exe"
            windowed.write_bytes(b"")
            console.write_bytes(b"")
            with patch.object(sys, "frozen", False, create=True), patch.object(
                sys, "executable", str(windowed)
            ):
                self.assertEqual(str(console), main_module.resolve_pdf_helper_python())

    def test_installed_app_uses_the_bundled_helper_next_to_its_exe(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-frozen-") as temp_dir:
            root = Path(temp_dir).resolve()
            app_exe = root / "ACIES Scheduler.exe"
            helper = root / main_module.PDF_HELPER_EXE_NAME
            app_exe.write_bytes(b"")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(app_exe)
            ):
                self.assertEqual("", main_module.resolve_pdf_helper_python())
                helper.write_bytes(b"")
                self.assertEqual(str(helper), main_module.resolve_pdf_helper_python())

    def test_export_sets_the_variable_the_publish_script_reads(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(main_module.PDF_HELPER_ENV_VAR, None)
            with patch.object(main_module, "resolve_pdf_helper_python", return_value=r"C:\app\acies-pdf-tools.exe"):
                main_module._export_pdf_helper_python()
                self.assertEqual(r"C:\app\acies-pdf-tools.exe", os.environ[main_module.PDF_HELPER_ENV_VAR])

    def test_export_keeps_a_value_the_user_already_set(self):
        with patch.dict(os.environ, {main_module.PDF_HELPER_ENV_VAR: r"D:\mine\python.exe"}):
            with patch.object(main_module, "resolve_pdf_helper_python", return_value=r"C:\app\acies-pdf-tools.exe"):
                main_module._export_pdf_helper_python()
                self.assertEqual(r"D:\mine\python.exe", os.environ[main_module.PDF_HELPER_ENV_VAR])


@unittest.skipUnless(sys.platform == "win32", "The publish script runs in Windows PowerShell")
class PublishScriptInterpreterTests(unittest.TestCase):
    """PlotDWGs.ps1 runs the helpers with ACIES_PDF_PYTHON when the app provides it."""

    @classmethod
    def setUpClass(cls):
        script = (SCRIPTS_DIR / "PlotDWGs.ps1").read_text(encoding="utf-8")
        start = script.index('$pythonExecutable = "python"')
        end = script.index("$MaxCombinedPdfFullPathLength")
        cls.snippet = script[start:end]

    def interpreter_chosen(self, configured):
        environment = dict(os.environ)
        environment.pop("ACIES_PDF_PYTHON", None)
        if configured is not None:
            environment["ACIES_PDF_PYTHON"] = configured
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             self.snippet + "; Write-Output $pythonExecutable"],
            capture_output=True, text=True, timeout=60, env=environment,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout.strip()

    def test_uses_the_interpreter_the_app_provides(self):
        with tempfile.TemporaryDirectory(prefix="acies-pdf-interpreter-") as temp_dir:
            helper = Path(temp_dir) / "acies pdf tools.exe"
            helper.write_bytes(b"")
            self.assertEqual(str(helper), self.interpreter_chosen(str(helper)))

    def test_falls_back_to_python_on_path_otherwise(self):
        self.assertEqual("python", self.interpreter_chosen(None))
        self.assertEqual("python", self.interpreter_chosen(""))
        self.assertEqual("python", self.interpreter_chosen(r"C:\no\such\helper.exe"))


if __name__ == "__main__":
    unittest.main()
