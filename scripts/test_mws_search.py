import requests

payload = """<mws:query xmlns:mws="http://search.mathweb.org/ns">
<math xmlns="http://www.w3.org/1998/Math/MathML">
  <apply><plus/><ci>x</ci><ci>y</ci></apply>
</math>
</mws:query>"""

print("--- TESTING SEARCH ENDPOINT ---")
try:
    r = requests.post("http://localhost:8085/search", data=payload.encode('utf-8'), headers={'Content-Type': 'application/xml'})
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")
except Exception as e:
    print(f"Error: {e}")
