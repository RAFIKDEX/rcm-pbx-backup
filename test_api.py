import sys
sys.path.append('/root/RCM_7021')
import time

print("Importing app...")
from app import app
print("App imported. Setting up test client...")

with app.test_request_context():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
            sess['role'] = 'admin'
        
        print("Sending GET request to /api/queues-list...")
        t0 = time.time()
        response = client.get('/api/queues-list')
        t1 = time.time()
        print(f"Response status code: {response.status_code} in {t1-t0:.4f} seconds")
        print("Response body:", response.get_data(as_text=True))
