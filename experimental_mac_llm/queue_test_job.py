import os
import sys
import json

# Add the parent directory to sys.path to import mathstudio modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db

def queue_mock_task(book_id=1205, page_number=30):
    """
    Inserts a dummy 'extract_page_mlx' task into the actual MathStudio llm_tasks table.
    We'll use book_id 1205 (Geometric Algebra for Physicists) and page 30 by default.
    """
    payload = json.dumps({
        "book_id": book_id, 
        "page_number": page_number
    })
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO llm_tasks (task_type, payload, status, priority, retry_count)
            VALUES (?, ?, 'pending', 5, 0)
        ''', ('extract_page_mlx', payload))
        new_id = cursor.lastrowid
        conn.commit()
        print(f"Successfully queued mock MLX experimental task! (Task ID: {new_id}, Book ID: {book_id}, Page: {page_number})")
        print("Run `python experimental_worker.py` to process it.")

if __name__ == "__main__":
    b_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1205
    p_num = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    queue_mock_task(b_id, p_num)
