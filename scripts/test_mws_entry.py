import requests

payload = """<mws:harvest xmlns:mws="http://search.mathweb.org/ns">
  <mws:entry id="test">
    <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>x</ci></math>
  </mws:entry>
</mws:harvest>"""

print("--- TESTING HARVEST WITH ENTRY ---")
try:
    r = requests.post("http://mathwebsearch:8080/harvest", data=payload.encode('utf-8'), headers={'Content-Type': 'application/xml'})
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")
except Exception as e:
    print(f"Error: {e}")
