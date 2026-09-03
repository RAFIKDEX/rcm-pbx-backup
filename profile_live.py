import time
from app import app
import rcm_queue_db
with app.test_request_context('/call-center/live'):
    start = time.time()
    for _ in range(10):
        rcm_queue_db.get_live_dashboard_status()
    print(f"Total for 10 calls: {time.time() - start:.3f} s")
