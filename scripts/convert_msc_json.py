#!/usr/bin/env python3
"""
Convert the hierarchical dokumentation/msc2020.json into a flat lookup
table at static/msc_codes.json for use by the MathStudio UI.

Usage:
    python3 scripts/convert_msc_json.py
"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

INPUT = os.path.join(PROJECT_ROOT, "dokumentation", "msc2020.json")
OUTPUT = os.path.join(PROJECT_ROOT, "static", "msc_codes.json")


def flatten(data):
    flat = {}
    for top in data:
        # Top-level: "00-XX" → key "00"
        code = top["code"]
        prefix = code[:2]
        flat[prefix] = top["description"]

        # Top-level direct codes (like "00-01", "00-02")
        for c in top.get("codes", []):
            flat[c["code"]] = c["description"]

        # Subcategories
        for sub in top.get("subcategories", []):
            # Mid-level: "00Axx" → key "00A"
            mid_code = sub["code"][:3]
            flat[mid_code] = sub["description"]

            # Leaf codes
            for leaf in sub.get("codes", []):
                flat[leaf["code"]] = leaf["description"]

    return flat


if __name__ == "__main__":
    with open(INPUT, "r", encoding="utf-8") as f:
        data = json.load(f)

    flat = flatten(data)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(flat, f, indent=2, ensure_ascii=False)

    # Stats
    two_digit = sum(1 for k in flat if len(k) == 2)
    three_char = sum(1 for k in flat if len(k) == 3)
    five_char = sum(1 for k in flat if len(k) == 5)
    print(f"Written {len(flat)} MSC codes to {OUTPUT}")
    print(f"  Two-digit:  {two_digit}")
    print(f"  Three-char: {three_char}")
    print(f"  Five-char:  {five_char}")
