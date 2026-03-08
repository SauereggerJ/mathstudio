import requests

payload = """<mws:harvest xmlns:mws="http://www.mathweb.org/mws/ns">
  <mws:expr url="test_url">
    <math xmlns="http://www.w3.org/1998/Math/MathML">
      <apply><plus/><ci>x</ci><ci>y</ci></apply>
    </math>
  </mws:expr>
</mws:harvest>"""

print("--- TESTING HARVEST WITH NS AND EXPR ---")
try:
    r = requests.post("http://mathwebsearch:8080/harvest", data=payload.encode('utf-8'), headers={'Content-Type': 'application/xml'})
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")
except Exception as e:
    print(f"Error: {e}")
