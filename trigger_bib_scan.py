import requests
import json

try:
    url = "http://localhost:5002/api/v1/tools/bib-scan"
    data = {"book_id": 530}
    print(f"Triggering bib scan at {url} with data: {data}")
    
    response = requests.post(url, json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response (first 500 chars): {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
