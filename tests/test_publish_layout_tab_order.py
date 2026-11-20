"""Publish must print a drawing's sheets in AutoCAD's tab order, not by name.

The plot LISP used to walk the ACAD_LAYOUT dictionary (alphabetical by name) and
PowerShell then sorted the per-layout PDFs by file name before merging, so a single
DWG with tabs E-001, E-201, E-101 came out as E-001, E-101, E-201.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLOT_SCRIPT = REPO_ROOT / "scripts" / "PlotDWGs.ps1"


def _plot_text():
    return PLOT_SCRIPT.read_text(encoding="utf-8")


def _function_source(text, name):
    start = text.index(f"function {name} {{")
    end = text.index("\nfunction ", start + 1)
    return text[start:end]


class PublishLayoutTabOrderTests(unittest.TestCase):
    def test_lisp_plots_layouts_by_tab_order_and_reports_it(self):
        text = _plot_text()
        helper = text[text.index("(defun AciesLayoutsInTabOrder"):text.index("(defun PlotLayoutsAfterPreflight")]
        self.assertIn("(assoc 71 layout-data)", helper)
        self.assertIn("(vl-sort", helper)
        self.assertIn('(/= (strcase layout-name) "MODEL")', helper)

        body = text[text.index("(defun PlotLayoutsAfterPreflight"):text.index("(defun c:PlotAllLayouts")]
        self.assertIn("(foreach layout-name (AciesLayoutsInTabOrder)", body)
        self.assertNotIn("(foreach item layout-dict", body)
        self.assertIn('(AciesLog (strcat "$layoutOrderMarker" (itoa layout-index) ":" layout-name "|"))', body)
        self.assertIn('$layoutOrderMarker = "ACIES_LAYOUT_ORDER:"', text)

    def test_merge_uses_reported_tab_order_instead_of_name_sort(self):
        text = _plot_text()
        self.assertNotIn("$pdfPaths = @($newPerDwgPdfs | ForEach-Object { $_.FullName } | Sort-Object)", text)
        self.assertIn("$pdfPaths = @(Get-LayoutPdfPathsInTabOrder `", text)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_pdf_paths_follow_tab_order_with_unreported_pdfs_last(self):
        function = _function_source(_plot_text(), "Get-LayoutPdfPathsInTabOrder")
        # Core Console output can carry NUL characters (one is built into a line below).
        command = function + r"""
$pdfs = @(
  'C:\out\E-Power-E-001.pdf',
  'C:\out\E-Power-E-101.pdf',
  'C:\out\E-Power-E-201.pdf',
  'C:\out\E-Power-Zeta.pdf',
  'C:\out\E-Power-Alpha.pdf',
  'C:\out\E-Power-cover sheet.pdf'
)
$lines = @(
  'Command: (load "x")',
  'ACIES_LAYOUT_ORDER:1:Cover Sheet|',
  'ACIES_LAYOUT_ORDER:2:E-201|Command: -PLOT',
  "A$([char]0)CIES_LAYOUT_ORDER:3:E-001|",
  'ACIES_LAYOUT_ORDER:4:E-101|'
)
$result = Get-LayoutPdfPathsInTabOrder -PdfPaths $pdfs -OutputLines $lines -DwgNameWithoutExt 'E-Power'
ConvertTo-Json -Compress -InputObject @($result)
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([
            r"C:\out\E-Power-cover sheet.pdf",
            r"C:\out\E-Power-E-201.pdf",
            r"C:\out\E-Power-E-001.pdf",
            r"C:\out\E-Power-E-101.pdf",
            r"C:\out\E-Power-Alpha.pdf",
            r"C:\out\E-Power-Zeta.pdf",
        ], json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
