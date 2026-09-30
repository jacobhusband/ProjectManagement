# --- shrink_pdf.py ---
# Creates a lower-resolution copy of a PDF by rasterizing pages with PyMuPDF.

import os
import shutil
import sys
try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:  # PyMuPDF older than 1.24.3
    import fitz


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def shrink_pdf(input_path, output_path, percent):
    if percent >= 100:
        print("Percent is 100; no shrinking requested.")
        return

    # Map the percent slider to a safer DPI range to avoid extreme blurring.
    # 100% -> 200 DPI (AutoCAD default), 50% -> ~148 DPI, 5% -> ~101 DPI.
    min_dpi = 96
    max_dpi = 200
    target_dpi = min_dpi + (max_dpi - min_dpi) * (percent / 100.0)
    scale = target_dpi / 72.0  # 72 DPI is the PDF user space baseline.

    src = fitz.open(input_path)
    dst = fitz.open()

    for page in src:
        rect = page.rect
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(
            matrix=mat,
            alpha=True,
            colorspace=fitz.csRGB,
        )
        new_page = dst.new_page(width=rect.width, height=rect.height)
        new_page.insert_image(rect, pixmap=pix)

    tmp_output = output_path + ".tmp"
    dst.save(tmp_output, garbage=4, deflate=True, clean=True)
    dst.close()
    src.close()

    # If the rasterized output is larger, keep the original to avoid bloat.
    try:
        input_size = os.path.getsize(input_path)
        output_size = os.path.getsize(tmp_output)
        if output_size >= input_size:
            shutil.copyfile(input_path, output_path)
            os.remove(tmp_output)
            print("Shrunk PDF would be larger; kept the original instead.")
        else:
            os.replace(tmp_output, output_path)
    except OSError:
        # Fall back to the tmp output if size checks fail.
        try:
            os.replace(tmp_output, output_path)
        except OSError:
            pass


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: python shrink_pdf.py <input_pdf> <output_pdf> <percent>",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    try:
        percent = int(float(sys.argv[3]))
    except ValueError:
        print("Percent must be a number.", file=sys.stderr)
        sys.exit(1)

    percent = clamp(percent, 5, 100)
    if percent >= 100:
        print("Percent is 100; skipping shrink.")
        return

    shrink_pdf(input_path, output_path, percent)
    print(f"Shrunk PDF created at {output_path} ({percent}%).")


if __name__ == "__main__":
    main()
