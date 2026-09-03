import sys
sys.path.append('/root/RCM_7021')
from app import app
import db

with app.test_request_context():
    # Let's mock a session
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
            sess['role'] = 'admin'
        
        # Now make a GET request to /queues
        response = client.get('/queues')
        print("Status code:", response.status_code)
        html = response.get_data(as_text=True)
        
        # Print lines around the script tags
        lines = html.splitlines()
        for idx, line in enumerate(lines):
            if "const ALL_EXTENSIONS" in line:
                for offset in range(-2, 10):
                    if 0 <= idx + offset < len(lines):
                        print(f"{idx+offset+1}: {lines[idx+offset]}")
