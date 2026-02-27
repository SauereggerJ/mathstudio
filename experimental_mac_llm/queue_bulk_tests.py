import os
import json
import sys
import random

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db

def queue_bulk_random_tasks(num_tasks=100):
    print(f"Queuing {num_tasks} random MLX extraction tasks for stress testing...")
    queued = 0
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all valid book IDs with page counts
        cursor.execute("SELECT id, page_count FROM books WHERE page_count IS NOT NULL AND page_count > 10")
        valid_books = cursor.fetchall()
        
        if not valid_books:
            print("Error: No valid books with >10 pages found in database.")
            return

        for _ in range(num_tasks):
            # Select random book
            book = random.choice(valid_books)
            book_id = book['id']
            # Select a random page between 1 and the total page length
            page_number = random.randint(1, int(book['page_count']))
            
            payload = json.dumps({
                "book_id": book_id,
                "page_number": page_number,
                "mode": "benchmark_stress_test"
            })
            
            import time
            cursor.execute('''
                INSERT INTO llm_tasks (task_type, payload, status, priority, created_at)
                VALUES (?, ?, 'pending', 1, ?)
            ''', ("extract_page_mlx", payload, int(time.time())))
            queued += 1

    print(f"Successfully queued {queued} 'extract_page_mlx' tasks.")
    print("Run `python experimental_worker.py` to begin the stream.")

if __name__ == "__main__":
    count = 100
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    queue_bulk_random_tasks(count)
