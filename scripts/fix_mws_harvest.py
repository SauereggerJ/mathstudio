import sys
import os
import subprocess
from elasticsearch import Elasticsearch

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import ELASTICSEARCH_URL

# Configuration
ES_CLIENT = Elasticsearch(ELASTICSEARCH_URL)
INDEX_NAME = "mathstudio_terms"
HARVEST_FILE_PATH = "/library/mathstudio/mathstudio.harvest"

def convert_latex_to_mathml(latex_str):
    """Strictly converts LaTeX to Content MathML using latexmlmath."""
    try:
        # We need to ensure we get CLEAN Content MathML
        # Some LaTeX snippets are actually full paragraphs, latexmlmath fails on them
        result = subprocess.run(
            ["latexmlmath", "--cmml=-", "-"],
            input=latex_str,
            capture_output=True,
            text=True,
            check=True,
            timeout=15
        )
        output = result.stdout.strip()
        
        # QUALITY CHECK:
        # If the output contains <cerror> or "ltx_math_unparsed", it's garbage for MWS
        if "<cerror" in output or "ltx_math_unparsed" in output:
            return None, "Unparsed/Error MathML"
            
        if "<math" not in output:
            return None, "No math tag in output"
            
        return output, None
    except Exception as e:
        return None, str(e)

def fix_harvest_file():
    print(f"--- Starting MWS File-Based Harvest (Canonical Namespace) ---")
    
    print("Fetching term IDs from Elasticsearch...")
    query = {"query": {"match_all": {}}, "_source": ["latex_content"]}
    res = ES_CLIENT.search(index=INDEX_NAME, body=query, size=5000)
    hits = res['hits']['hits']
    total_hits = len(hits)
    print(f"Found {total_hits} terms.")

    total_converted = 0
    total_failed = 0
    
    with open(HARVEST_FILE_PATH, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        # Using canonical namespace
        f.write('<mws:harvest xmlns:mws="http://www.mathweb.org/mws/ns">\n')
        
        for i, hit in enumerate(hits):
            term_id = hit['_id']
            latex = hit['_source'].get('latex_content')
            if not latex: continue
                
            mathml, error = convert_latex_to_mathml(latex)
            if mathml:
                # Ensure MathML namespace is present and clean attributes
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(mathml, "xml")
                math_tag = soup.find('math')
                if math_tag:
                    # Clear IDs and set namespace
                    for attr in ['id', 'xml:id', 'xref']:
                        if math_tag.has_attr(attr): del math_tag[attr]
                    math_tag['xmlns'] = "http://www.w3.org/1998/Math/MathML"
                    
                    expr_xml = f'    <mws:expr url="term_{term_id}">\n        {str(math_tag)}\n    </mws:expr>\n'
                    f.write(expr_xml)
                    total_converted += 1
                else:
                    total_failed += 1
            else:
                total_failed += 1
            
            if (i + 1) % 50 == 0:
                print(f"  Processed {i+1}/{total_hits} terms... Converted: {total_converted}")

        f.write('</mws:harvest>\n')

    print("\n--- MWS File-Based Harvest Summary ---")
    print(f"Total Hits:             {total_hits}")
    print(f"Successfully Converted: {total_converted}")
    print(f"Failed/Filtered:        {total_failed}")
    print(f"Harvest file written to: {HARVEST_FILE_PATH}")

if __name__ == "__main__":
    fix_harvest_file()
