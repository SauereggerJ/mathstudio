#!/usr/bin/env python3
"""
Extract MSC 2020 codes from the official PDF into a JSON lookup table.

Usage:
    python3 scripts/extract_msc.py dokumentation/msc2020.pdf static/msc_codes.json

Requires: PyMuPDF (fitz) — install with `pip install pymupdf`
"""
import json
import re
import sys

def extract_msc_from_pdf(pdf_path: str) -> dict:
    """Parse MSC 2020 PDF and return {code: description} dict."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("ERROR: PyMuPDF not installed. Run: pip install pymupdf")
        sys.exit(1)

    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text("text") + "\n"
    doc.close()

    codes = {}
    # Match patterns like "00-XX", "00Axx", "00A05", "46C05" etc.
    # MSC codes are: 2-digit, 3-char (e.g. 46C), or 5-char (e.g. 46C05)
    pattern = re.compile(
        r'^(\d{2}(?:-[A-Z]{2}|[A-Z](?:xx|\d{2})))\s+(.+?)$',
        re.MULTILINE
    )

    for match in pattern.finditer(full_text):
        code = match.group(1).strip()
        desc = match.group(2).strip()
        # Clean up multi-line descriptions
        desc = re.sub(r'\s+', ' ', desc)
        # Skip entries that are just cross-references like "{For...}"
        if desc.startswith('{') and desc.endswith('}'):
            continue
        codes[code] = desc

    return codes


def build_hierarchy(codes: dict) -> dict:
    """Build a hierarchical tree from flat MSC codes."""
    tree = {}
    for code, desc in sorted(codes.items()):
        if len(code) == 5 and code[2:] == '-XX':
            # Top-level: "00-XX" → "00"
            top = code[:2]
            if top not in tree:
                tree[top] = {"name": desc, "children": {}}
        elif len(code) == 5 and code.endswith('xx'):
            # Mid-level: "00Axx" → parent "00"
            top = code[:2]
            mid = code[:3]
            if top not in tree:
                tree[top] = {"name": "", "children": {}}
            tree[top]["children"][mid] = {"name": desc, "children": {}}
        elif len(code) == 5:
            # Leaf: "00A05" → parent "00A"
            top = code[:2]
            mid = code[:3]
            if top not in tree:
                tree[top] = {"name": "", "children": {}}
            if mid not in tree[top]["children"]:
                tree[top]["children"][mid] = {"name": "", "children": {}}
            tree[top]["children"][mid]["children"][code] = desc

    return tree


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <msc2020.pdf> <output.json>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2]

    print(f"Extracting MSC codes from {pdf_path}...")
    codes = extract_msc_from_pdf(pdf_path)
    print(f"Found {len(codes)} MSC codes")

    # Build both flat and hierarchical representations
    result = {
        "flat": codes,
        "tree": build_hierarchy(codes)
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Written to {output_path}")

    # Print stats
    top_level = sum(1 for c in codes if c.endswith('-XX'))
    mid_level = sum(1 for c in codes if c.endswith('xx') and not c.endswith('-XX'))
    leaf_level = len(codes) - top_level - mid_level
    print(f"  Top-level (2-digit): {top_level}")
    print(f"  Mid-level (3-char):  {mid_level}")
    print(f"  Leaf (5-char):       {leaf_level}")
