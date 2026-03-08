import requests
import subprocess
from bs4 import BeautifulSoup

def convert_to_mathml(latex_str):
    result = subprocess.run(
        ["latexmlmath", "--cmml=-", "-"],
        input=latex_str,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()

def test_search(q):
    mathml_raw = convert_to_mathml(q)
    soup = BeautifulSoup(mathml_raw, "xml")
    for tag in soup.find_all(True):
        for attr in ['id', 'xml:id', 'xref']:
            if tag.has_attr(attr):
                del tag[attr]
    math_tag = soup.find('math')
    mathml_clean = str(math_tag)
    
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<mws:query xmlns:mws="http://www.mathweb.org/mws/ns">
    <mws:expr>
        {mathml_clean}
    </mws:expr>
</mws:query>"""
    
    print("--- PAYLOAD ---")
    print(payload)
    
    r = requests.post("http://mathwebsearch:8080/search", data=payload.encode('utf-8'), headers={'Content-Type': 'application/xml'})
    print("\n--- RESPONSE ---")
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")

if __name__ == "__main__":
    test_search("X")
