import sys
import os
import json
import time

sys.path.append('/root/RCM_7021')
from app import app

def main():
    with app.test_request_context():
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
            sess['role'] = 'admin'

        print("--- Testing Static Disable (Pause) ---")
        res = client.post('/queues/6500/agents/disable', data={'agent': '5001'})
        print("Disable 5001 Response:", res.get_json())

        print("--- Testing Static Enable (Unpause) ---")
        res = client.post('/queues/6500/agents/enable', data={'agent': '5001'})
        print("Enable 5001 Response:", res.get_json())

        print("--- Testing Dynamic Login (5004) ---")
        res = client.post('/queues/6500/agents/join', data={'agent': '5004'})
        print("Join 5004 Response:", res.get_json())

        print("--- Testing Dynamic Pause (5004) ---")
        res = client.post('/queues/6500/agents/leave', data={'agent': '5004', 'action': 'pause'})
        print("Pause 5004 Response:", res.get_json())

        print("--- Testing Dynamic Unpause (5004) ---")
        res = client.post('/queues/6500/agents/join', data={'agent': '5004', 'action': 'unpause'})
        print("Unpause 5004 Response:", res.get_json())

        print("--- Testing Dynamic Logout (5004) ---")
        res = client.post('/queues/6500/agents/leave', data={'agent': '5004'})
        print("Logout 5004 Response:", res.get_json())

if __name__ == '__main__':
    main()
