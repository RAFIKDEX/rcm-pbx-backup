import time
import db
import rcm_queue_db
from app import app
with app.test_request_context('/call-center/stats'):
    filters = {"date_from": "2026-08-01", "date_to": "2026-08-17"}
    start = time.time()
    rcm_queue_db.get_filtered_queue_stats(filters)
    print(f"Total: {time.time() - start:.3f} s")
