"""Console entry point that runs the PDF helper scripts without a system Python.

PlotDWGs.ps1 merges, shrinks and strips the published PDFs with small Python
scripts. The installed app cannot assume the user has Python (or PyMuPDF) on
PATH, so the PyInstaller build ships this file as acies-pdf-tools.exe next to
the app. The app points the PowerShell scripts at it through ACIES_PDF_PYTHON,
and it accepts the same arguments as `python <script> <args>`:

    acies-pdf-tools.exe merge_pdfs.py <output_pdf> <input_pdf> [<input_pdf> ...]

Only the four helper scripts can be run. They are imported here (not loaded
from disk) so PyInstaller traces their imports and bundles PyMuPDF for them.
"""
import os
import runpy
import sys

import detect_pdf_size  # noqa: F401
import merge_pdfs  # noqa: F401
import shrink_pdf  # noqa: F401
import strip_pdf_layers  # noqa: F401

HELPER_MODULES = frozenset({
    "detect_pdf_size",
    "merge_pdfs",
    "shrink_pdf",
    "strip_pdf_layers",
})


def main(argv):
    if len(argv) < 2:
        print("Usage: acies-pdf-tools <helper script> [arguments...]", file=sys.stderr)
        return 2

    module_name = os.path.splitext(os.path.basename(argv[1]))[0]
    if module_name not in HELPER_MODULES:
        print(
            f"Unknown helper '{argv[1]}'. Expected one of: "
            + ", ".join(sorted(name + ".py" for name in HELPER_MODULES)),
            file=sys.stderr,
        )
        return 2

    # PowerShell decodes this output with the console code page. A path that code
    # page cannot encode must not abort a merge that already succeeded.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    # The helpers read sys.argv exactly as they do under `python <script> <args>`.
    sys.argv = [argv[1]] + list(argv[2:])
    runpy.run_module(module_name, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
