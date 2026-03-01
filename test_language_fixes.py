from services.library import library_service
import json

def test_amann_mismatch():
    print("=== Amann/Escher Language Check ===")
    mismatches = library_service.find_language_mismatches(limit=50)
    
    amann_mismatches = [m for m in mismatches if "Amann" in m['author']]
    print(f"Found {len(amann_mismatches)} Amann mismatches out of {len(mismatches)} total.")
    
    for m in amann_mismatches:
        print(f" - ID {m['id']}: {m['title']}")
        print(f"   Path: {m['path']}")
        
        # Test detection
        print(f"   Detecting actual language...")
        lang = library_service.detect_book_language(m['id'])
        print(f"   AI says: {lang}")
        
        # Suggest fix
        if lang == 'german':
            print(f"   Suggested fix: Restore German title from filename")
            fn = m['filename']
            if ' - ' in fn:
                potential = fn.split(' - ')[1].rsplit('.', 1)[0].strip()
                print(f"   Potential German Title: {potential}")
        print("-" * 30)

if __name__ == "__main__":
    test_amann_mismatch()
