import subprocess
import requests

def convert_latex_to_mathml(latex_str):
    try:
        result = subprocess.run(
            ["latexmlmath", "--cmml=-", "-"],
            input=latex_str,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        return str(e)

latex = "a^2 + b^2 = c^2"
mathml = convert_latex_to_mathml(latex)

print("--- RAW MATHML ---")
print(mathml)

# Exact schema test
payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<mws:harvest xmlns:mws="http://search.mathweb.org/ns">
    <mws:expr url="test_url">
        {mathml}
    </mws:expr>
</mws:harvest>"""

print("\n--- FULL PAYLOAD ---")
print(payload)

try:
    r = requests.post("http://mathwebsearch:8080/harvest", data=payload.encode('utf-8'), headers={'Content-Type': 'application/xml'})
    print("\n--- RESPONSE ---")
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")
except Exception as e:
    print(f"Error: {e}")
