import os
import sys
import subprocess
import json

# Set correct paths
sys.path.insert(0, '/root/RCM_7021')

from app import app
import rcm_queue_db

def run_asterisk_cmd(cmd):
    res = subprocess.run(["asterisk", "-rx", cmd], capture_output=True, text=True)
    return res.stdout

def main():
    print("=== STEP 1: Verify Initial Asterisk Queue Members ===")
    print(run_asterisk_cmd("queue show 6500"))

    print("=== STEP 2: Trigger Dynamic Join Action via Flask Route ===")
    with app.test_client() as client:
        # Authenticate and set session
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
            sess['role'] = 'admin'

        # Join agent 5003
        res = client.post('/queues/6500/agents/join', data={'agent': '5003'})
        print("Join Route Response Status:", res.status_code)
        print("Join Route Response Body:", res.get_data(as_text=True))

        print("\n=== STEP 3: Verify Member Registered on Asterisk Core ===")
        queue_show_out = run_asterisk_cmd("queue show 6500")
        print(queue_show_out)
        
        # Assert membership in output
        if "PJSIP/5003" in queue_show_out:
            print("SUCCESS: Extension 5003 successfully registered as a member on Asterisk!")
        else:
            print("FAILED: Extension 5003 not found in Asterisk queue members!")

        print("\n=== STEP 4: Query Performance Report API for STATIC Agents ===")
        # Get statistics
        stats_res = client.get('/call-center/stats/api?queue=6500')
        print("Stats Route Response Status:", stats_res.status_code)
        stats_payload = stats_res.get_json()
        
        # Find agent 5001 (configured as STATIC) in the agent_analytics list
        agent_5001 = None
        for agent in stats_payload.get("agent_analytics", []):
            if agent.get("extension") == "5001":
                agent_5001 = agent
                break
        
        if agent_5001:
            print("Found Agent 5001 Analytics:")
            print(json.dumps(agent_5001, indent=2))
            
            # Assert dynamic login/logout fields are null/empty/omitted
            is_valid = (
                agent_5001.get("login_duration") is None and
                agent_5001.get("online_time") is None and
                agent_5001.get("pause_time") is None and
                agent_5001.get("available_time") is None and
                agent_5001.get("sessions") == [] and
                agent_5001.get("pauses") == []
            )
            if is_valid:
                print("SUCCESS: Static agent metrics correctly nullified/omitted!")
            else:
                print("FAILED: Static agent metrics contain dynamic leaks!")
        else:
            print("FAILED: Agent 5001 not found in analytics!")

        print("\n=== STEP 5: Clean up (Leave Queue) ===")
        leave_res = client.post('/queues/6500/agents/leave', data={'agent': '5003'})
        print("Leave Route Response Status:", leave_res.status_code)
        print("Leave Route Response Body:", leave_res.get_data(as_text=True))
        
        print("\n=== STEP 6: Final Asterisk Queue Status ===")
        print(run_asterisk_cmd("queue show 6500"))

if __name__ == '__main__':
    main()
