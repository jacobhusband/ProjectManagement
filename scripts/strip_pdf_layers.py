# --- strip_pdf_layers.py ---
# Removes PDF optional-content layer metadata while preserving page content.

import os
import sys
import tempfile

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:  # PyMuPDF older than 1.24.3
    import fitz


def _catalog_has_ocproperties(doc):
    value_type, _ = doc.xref_get_key(doc.pdf_catalog(), "OCProperties")
    return value_type != "null"


def _verify_layer_free(pdf_path):
    with fitz.open(pdf_path) as verify_doc:
        remaining = verify_doc.get_ocgs() or {}
        if remaining:
            raise RuntimeError(
                f"PDF layer cleanup verification failed: {len(remaining)} layer(s) remain."
            )
        if _catalog_has_ocproperties(verify_doc):
            raise RuntimeError(
                "PDF layer cleanup verification failed: OCProperties still exists."
            )


def strip_pdf_layers(pdf_path):
    """Remove optional-content groups from a PDF in place.

    Returns the number of OCG entries present before cleanup.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    temp_path = ""
    removed_count = 0
    should_rewrite = False

    with fitz.open(pdf_path) as doc:
        ocgs = doc.get_ocgs() or {}
        removed_count = len(ocgs)
        should_rewrite = removed_count > 0 or _catalog_has_ocproperties(doc)
        if not should_rewrite:
            return 0

        doc.xref_set_key(doc.pdf_catalog(), "OCProperties", "null")
        output_dir = os.path.dirname(os.path.abspath(pdf_path)) or "."
        fd, temp_path = tempfile.mkstemp(
            prefix=".strip-pdf-layers-",
            suffix=".pdf",
            dir=output_dir,
        )
        os.close(fd)
        doc.save(temp_path, garbage=4, deflate=True)

    try:
        _verify_layer_free(temp_path)
        os.replace(temp_path, pdf_path)
        temp_path = ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    return removed_count


def main(argv):
    if len(argv) != 2:
        print("Usage: python strip_pdf_layers.py <pdf_path>", file=sys.stderr)
        return 2

    pdf_path = argv[1]
    try:
        removed_count = strip_pdf_layers(pdf_path)
    except Exception as exc:
        print(f"Error removing PDF layers: {exc}", file=sys.stderr)
        return 1

    if removed_count:
        print(f"PDF layer cleanup: removed {removed_count} optional content group(s).")
    else:
        print("PDF layer cleanup: no optional content groups found.")
    print(f"PDF layer cleanup verified: {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
