# --- merge_pdfs.py ---
# This version uses the PyMuPDF (fitz) library, which is more robust for
# handling complex PDFs from applications like AutoCAD.

import sys
try:
    import pymupdf as fitz  # The PyMuPDF library
except ImportError:  # PyMuPDF older than 1.24.3
    import fitz

def merge_pdfs(output_path, input_paths):
    """
    Merges multiple PDF files into a single PDF document using PyMuPDF.

    Args:
        output_path (str): The file path for the combined PDF.
        input_paths (list): A list of file paths for the PDFs to merge.
    """
    if not input_paths:
        print("Error: No input PDF files were provided.", file=sys.stderr)
        return

    try:
        # Create a new, empty PDF document object
        result_pdf = fitz.open()

        # Iterate through each input PDF file path
        for pdf_path in input_paths:
            try:
                # Open the source PDF
                with fitz.open(pdf_path) as source_pdf:
                    # Append all pages from the source PDF to the result PDF.
                    # This method is very effective at preserving all content.
                    result_pdf.insert_pdf(source_pdf)
                print(f"Successfully processed: {pdf_path}")
            except Exception as e:
                print(f"Error processing file {pdf_path}: {e}", file=sys.stderr)
                # Continue to the next file even if one fails
                pass

        # Check if any pages were added before saving
        if len(result_pdf) > 0:
            # Save the combined PDF to the specified output path
            result_pdf.save(output_path)
            print(f"\nSuccessfully merged {len(input_paths)} PDF(s) into: {output_path}")
        else:
            print("No pages were successfully merged. Output file not created.", file=sys.stderr)

        # Close the final PDF document object
        result_pdf.close()

    except Exception as e:
        print(f"A critical error occurred during the PDF merging process: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # The script expects at least two arguments after the script name:
    # sys.argv[1]: output_path
    # sys.argv[2:]: one or more input_paths
    if len(sys.argv) < 3:
        print("Usage: python merge_pdfs.py <output_path> <input_path1> <input_path2> ...", file=sys.stderr)
        sys.exit(1)

    output_file = sys.argv[1]
    input_files = sys.argv[2:]
    
    merge_pdfs(output_file, input_files)