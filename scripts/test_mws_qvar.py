import requests

payload = """<mws:query xmlns:mws="http://www.mathweb.org/mws/ns">
<mws:expr>
<math xmlns="http://www.w3.org/1998/Math/MathML">
  <apply><plus/><mws:qvar name="a"/><mws:qvar name="b"/></apply>
</math>
</mws:expr>
</mws:query>"""

r = requests.post("http://localhost:8085/search", data=payload.encode('utf-8'), headers={'Content-Type': 'application/xml'})
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:500]}")
