from pypdf import PdfReader
import sys

def extract_pages(pdf_path, pages):
    reader = PdfReader(pdf_path)
    content = ""
    for p in pages:
        if p < len(reader.pages):
            content += f"\n--- Page {p+1} ---\n"
            content += reader.pages[p].extract_text()
    return content

# Halmos: Page 140 in snippets corresponds to roughly page 140 in PDF (0-indexed 139)
# Wadsworth: Page 175 (0-indexed 174)
# McKee: Page 21 (0-indexed 20)

files = [
    ("../04_Algebra/00_Linear_Algebra/Linear Algebra Problem Book - Paul R. Halmos.pdf", [138, 139, 140, 141, 142]),
    ("../04_Algebra/01_Abstract_Algebra/Problems in Abstract Algebra - Adrian Wadsworth.pdf", [174, 175, 176]),
    ("../04_Algebra/05_Number_Theory/Around the Unit Circle - McKee & Smyth.pdf", [20, 21])
]

for path, pages in files:
    print(f"\nReading: {path}")
    try:
        print(extract_pages(path, pages))
    except Exception as e:
        print(f"Error reading {path}: {e}")

