import sqlite3
import os

DB_QUEUE_PATH = "/root/RCM_7021/rcm_queue.db"
DB_APP_PATH = "/root/RCM_7021/rcm_7021.db"

def inspect_and_clean():
    print("=========================================================")
    print(" Contact Center Analytics DB Cleanup Script")
    print("=========================================================")

    # 1. RCM Queue DB
    if os.path.exists(DB_QUEUE_PATH):
        print(f"\n[INFO] Connecting to RCM Queue DB: {DB_QUEUE_PATH}")
        conn = sqlite3.connect(DB_QUEUE_PATH)
        c = conn.cursor()
        
        # Before Counts
        c.execute("SELECT count(*) FROM queue_calls")
        calls_before = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queue_live")
        live_before = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queue_agent_events")
        events_before = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queue_agents")
        agents_before = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queues")
        queues_before = c.fetchone()[0]
        
        print("\nRow Counts BEFORE Cleanup:")
        print(f"  ● queue_calls: {calls_before}")
        print(f"  ● queue_live: {live_before}")
        print(f"  ● queue_agent_events: {events_before}")
        print(f"  ● queue_agents: {agents_before}")
        print(f"  ● queues (Config): {queues_before}")

        # Cleanup
        print("\nExecuting Cleanup Commands...")
        c.execute("DELETE FROM queue_calls")
        c.execute("DELETE FROM queue_live")
        c.execute("DELETE FROM queue_agent_events")
        c.execute("UPDATE queue_agents SET status = 'OFFLINE', login_time = NULL, logout_time = NULL")
        conn.commit()
        
        # After Counts
        c.execute("SELECT count(*) FROM queue_calls")
        calls_after = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queue_live")
        live_after = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queue_agent_events")
        events_after = c.fetchone()[0]
        c.execute("SELECT count(*) FROM queue_agents")
        agents_after = c.fetchone()[0]
        
        print("\nRow Counts AFTER Cleanup:")
        print(f"  ● queue_calls: {calls_after}")
        print(f"  ● queue_live: {live_after}")
        print(f"  ● queue_agent_events: {events_after}")
        print(f"  ● queue_agents: {agents_after}")
        
        conn.close()
    else:
        print(f"\n[WARNING] RCM Queue DB not found at {DB_QUEUE_PATH}")

    # 2. Main App DB
    if os.path.exists(DB_APP_PATH):
        print(f"\n[INFO] Connecting to Main App DB: {DB_APP_PATH}")
        conn = sqlite3.connect(DB_APP_PATH)
        c = conn.cursor()
        
        # Verify table existence first
        tables = []
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for t in c.fetchall():
            tables.append(t[0])
            
        print(f"Existing tables in main app DB: {tables}")
        
        for table_name in ["rcm_queue_calls", "rcm_queue_log", "rcm_queue_alerts"]:
            if table_name in tables:
                c.execute(f"SELECT count(*) FROM {table_name}")
                before = c.fetchone()[0]
                print(f"  ● Table {table_name} BEFORE count: {before}")
                c.execute(f"DELETE FROM {table_name}")
                print(f"    -> Cleared {table_name}")
            else:
                print(f"  ● Table {table_name} does not exist in main DB")
                
        conn.commit()
        conn.close()
    else:
        print(f"\n[WARNING] Main App DB not found at {DB_APP_PATH}")

    print("\nCleanup completed.")
    print("=========================================================")

if __name__ == "__main__":
    inspect_and_clean()
