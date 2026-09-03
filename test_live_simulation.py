import os
import sys
import time
import sqlite3
import subprocess

DB_PATH = "/root/RCM_7021/rcm_queue.db"

def run_asterisk_cmd(cmd):
    try:
        res = subprocess.run(["asterisk", "-rx", cmd], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception as e:
        print(f"Error running Asterisk command '{cmd}': {e}")
        return ""

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def print_db_status():
    conn = get_db_connection()
    c = conn.cursor()
    
    print("\n--- Current Database Live Calls ---")
    c.execute("SELECT * FROM queue_live")
    calls = c.fetchall()
    if not calls:
        print("No active calls in queue_live table.")
    for call in calls:
        print(f"Call ID: {call['call_id']} | Caller: {call['caller']} | State: {call['state']} | Agent: {call['agent']} | Start Time: {call['start_time']}")
        
    print("\n--- Current Database Agent Status ---")
    c.execute("SELECT * FROM queue_agents")
    agents = c.fetchall()
    if not agents:
        print("No agents in queue_agents table.")
    for ag in agents:
        print(f"Extension: {ag['extension']} | Name: {ag['agent_name']} | Status: {ag['status']} | Type: {ag['type']}")
    
    conn.close()

def main():
    print("=========================================================")
    print(" RCM Contact Center Queue Flow Simulation Test")
    print("=========================================================")
    
    # 1. Clean up existing live rows for safety
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM queue_live")
    conn.commit()
    conn.close()
    
    # 2. Add simulated agent to queue 6500
    print("\n[STEP 1] Logging in agent 'agent_answer' dynamically into Queue 6500...")
    run_asterisk_cmd("queue add member Local/agent_answer@rcm-simulation to 6500")
    
    print("Waiting 2 seconds for collector daemon to record event...")
    time.sleep(2)
    
    print_db_status()
    
    # Verify agent was logged in
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM queue_agents WHERE extension = 'agent_answer' AND status = 'AVAILABLE'")
    if c.fetchone()[0] == 0:
        print("[WARNING] Simulated agent not found as AVAILABLE in database. Ensure collector is running.")
    conn.close()
    
    # 3. Originate call to queue 6500
    print("\n[STEP 2] Originating call from Local/caller_wait to Queue 6500...")
    run_asterisk_cmd("channel originate Local/caller_wait@rcm-simulation extension 6500@queue-6500")
    
    # 4. Monitor state transitions for 22 seconds
    print("\n[STEP 3] Monitoring call state transitions in database in real-time...")
    start_time = time.time()
    call_completed = False
    
    while time.time() - start_time < 22:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM queue_live")
        calls = c.fetchall()
        
        if calls:
            print(f"\n[TIME {int(time.time() - start_time)}s]")
            for call in calls:
                print(f"  ● Call state: {call['state']} | Caller: {call['caller']} | Agent: {call['agent']}")
        else:
            if not call_completed:
                print(f"\n[TIME {int(time.time() - start_time)}s] Call no longer in queue_live. Checking historical records...")
                c.execute("SELECT * FROM queue_calls ORDER BY entry_time DESC LIMIT 1")
                last_call = c.fetchone()
                if last_call:
                    print(f"  ● Last Call UniqueID: {last_call['uniqueid']} | Status: {last_call['status']} | Wait Time: {last_call['wait_time']}s | Talk Time: {last_call['talk_time']}s | Hangup Reason: {last_call['hangup_reason']}")
                    call_completed = True
        conn.close()
        time.sleep(1)
        
    # 5. Check statistics update
    print("\n[STEP 4] Verifying single queue database statistics...")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='ANSWERED' THEN 1 ELSE 0 END) as answered, AVG(wait_time) as avg_wait, AVG(talk_time) as avg_talk FROM queue_calls WHERE queue_id = '6500'")
    stats = c.fetchone()
    print(f"  ● Total Calls: {stats['total']} | Answered: {stats['answered']} | Avg Wait: {int(stats['avg_wait'] or 0)}s | Avg Talk: {int(stats['avg_talk'] or 0)}s")
    conn.close()
    
    # 6. Log out simulated agent
    print("\n[STEP 5] Logging out agent 'agent_answer'...")
    run_asterisk_cmd("queue remove member Local/agent_answer@rcm-simulation from 6500")
    
    print("\nSimulation completed successfully.")
    print("=========================================================")

if __name__ == '__main__':
    main()
