#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path

# Scenarios to test
SCENARIOS = [
    {
        "name": "Theorem Comparison",
        "prompt": "Compare the definition of 'Riemann Integral' between two different books. Cite the book IDs and page numbers."
    },
    {
        "name": "Exercise Discovery",
        "prompt": "Find 3 exercises related to 'Baire Category Theorem' in the Knowledge Base. List their IDs and sources."
    },
    {
        "name": "Note Drafting",
        "prompt": "Research 'Heine-Borel Theorem', draft a short summary using append_to_draft, and then publish_research_report."
    }
]

GEMINI_PATH = "/usr/local/bin/gemini"
CWD = "/home/jure/math_research"

def run_scenario(name, prompt):
    print(f"\n=== Running Scenario: {name} ===")
    print(f"Prompt: {prompt}")
    
    try:
        # Run the gemini command in the correct CWD
        result = subprocess.run(
            [GEMINI_PATH, "-p", prompt],
            cwd=CWD,
            capture_output=True,
            text=True,
            timeout=180
        )
        
        if result.returncode == 0:
            print("✓ Execution Successful")
            # Filter output for readability (strip noise)
            print("-" * 40)
            print(result.stdout)
            print("-" * 40)
            return True
        else:
            print(f"✗ Execution Failed (Code {result.returncode})")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print("✗ Execution Timed Out after 180s")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    print("Starting One-Shot LLM + MCP Integration Test Suite")
    results = []
    for s in SCENARIOS:
        success = run_scenario(s["name"], s["prompt"])
        results.append((s["name"], success))
    
    print("\n=== FINAL TEST SUMMARY ===")
    for name, success in results:
        status = "PASSED" if success else "FAILED"
        print(f"{name}: {status}")

if __name__ == "__main__":
    main()
