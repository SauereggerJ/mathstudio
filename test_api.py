import requests
import json
import sys

BASE_URL = "http://192.168.178.2:5002/api/v1"

def print_result(name, url, response):
    print(f"\n{'='*50}")
    print(f"TEST: {name}")
    print(f"URL: {url}")
    print(f"STATUS: {response.status_code}")
    if response.status_code != 200:
        print(f"ERROR: {response.text}")
        return
    
    try:
        data = response.json()
        print(json.dumps(data, indent=2)[:500] + "\n... [TRUNCATED] ...")
        
        # Specific checks
        if "results" in data:
            print(f"-> Found {len(data['results'])} items.")
            if data['results']:
                sample = data['results'][0]
                print(f"-> Sample Keys: {list(sample.keys())}")
    except Exception as e:
        print(f"Failed to parse JSON: {e}")

def run_tests():
    print(f"Starting API Validation against {BASE_URL}...\n")
    
    # 1. Hybrid Search
    url = f"{BASE_URL}/search?q=algebra&limit=2"
    res = requests.get(url)
    print_result("Hybrid Search (q=algebra)", url, res)
    
    # 2. Vector Search
    url = f"{BASE_URL}/search/vector?q=algebra&limit=2"
    res = requests.get(url)
    print_result("Vector Search (q=algebra)", url, res)
    
    # 3. Browse (Strict Metadata Filter)
    # Testing with MSC code for linear algebra (15A) or just a limit
    url = f"{BASE_URL}/browse?limit=2&author=Axler"
    res = requests.get(url)
    print_result("Browse Filter (author=Axler)", url, res)
    
    # 4. MSC Stats
    url = f"{BASE_URL}/msc-stats"
    res = requests.get(url)
    print_result("MSC Stats", url, res)
    
    # 5. MSC Tree
    url = f"{BASE_URL}/msc-tree"
    res = requests.get(url)
    print_result("MSC Tree", url, res)
    
    # 6. Book Details (Let's try to get a book ID from the first search)
    book_id = 1
    try:
        search_data = requests.get(f"{BASE_URL}/search?q=algebra&limit=1").json()
        if search_data.get('results'):
            book_id = search_data['results'][0]['id']
    except:
        pass
        
    url = f"{BASE_URL}/books/{book_id}"
    res = requests.get(url)
    print_result(f"Book Details (ID={book_id})", url, res)

if __name__ == "__main__":
    run_tests()
