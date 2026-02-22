import subprocess
import os

def find_exercises(rel_path, start_page):
    print(f"Searching for exercises in {rel_path} starting at page {start_page}...")
    try:
        # Get 10 pages to find the exercises section
        cmd = ["pdftotext", "-f", str(start_page), "-l", str(start_page + 10), rel_path, "-"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        text = result.stdout
        
        # Look for "Übungsaufgaben" or "Beispiel" or "Aufgabe"
        if "Aufgabe" in text:
            print("\nFound 'Aufgabe' in text.")
            # Print the context around the first Aufgabe
            idx = text.find("Aufgabe")
            print(text[idx:idx+1500])
        else:
            print("\nNo explicit 'Aufgabe' in this range.")
            print("Preview of page content:")
            print(text[:1000])
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    find_exercises("../04_Algebra/00_Linear_Algebra/Pruefungstraining Lineare Algebra (Vol 2) - Michaels & Liechti.pdf", 605)

