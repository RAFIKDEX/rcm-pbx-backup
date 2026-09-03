import sys
import os
import sqlite3
import random
import unittest
from datetime import datetime

# Setup paths
sys.path.insert(0, '/root/RCM_7021')

import rcm_queue_db
import rcm_queue_collector
from app import app

class StressTestSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        
    def setUp(self):
        # Clean up database tables for testing
        conn = rcm_queue_db.get_db_connection()
        conn.execute("DELETE FROM queue_live")
        conn.execute("DELETE FROM queue_calls")
        conn.execute("DELETE FROM queue_agents")
        conn.execute("DELETE FROM queue_agent_events")
        conn.commit()
        conn.close()
        
        # Ensure static agent 5001 is set up
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_agent_pause("5001", "6500", False)

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['role'] = 'admin'

    def test_55_iterations_stress_loop(self):
        print("\nStarting 55-iteration stress test loop...")
        
        # Define call distribution
        # Total calls = 55
        # Answered = 15
        # Abandoned = 10
        # Cancelled = 10
        # No Answer = 10
        # Timeout = 10
        call_types = (
            ["ANSWERED"] * 15 +
            ["ABANDONED"] * 10 +
            ["CANCELLED"] * 10 +
            ["NO_ANSWER"] * 10 +
            ["TIMEOUT"] * 10
        )
        random.shuffle(call_types)
        
        for i, ctype in enumerate(call_types, start=1):
            uniqueid = f"uid-stress-{i}"
            caller_num = f"1000{i}"
            
            # --- 1. Dynamic Login/Logout ---
            if i % 2 == 1:
                # Login agent 5002 dynamically
                rcm_queue_collector.handle_event({
                    "Event": "QueueMemberAdded",
                    "Queue": "6500",
                    "Interface": "PJSIP/5002",
                    "MemberName": "Bob",
                    "Membership": "DYNAMIC"
                })
                # Check status
                conn = rcm_queue_db.get_db_connection()
                row = conn.execute("SELECT status, type FROM queue_agents WHERE extension = '5002' AND queue_id = '6500'").fetchone()
                conn.close()
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "AVAILABLE")
                self.assertEqual(row["type"], "DYNAMIC")
            else:
                # Logout agent 5002 dynamically
                rcm_queue_collector.handle_event({
                    "Event": "QueueMemberRemoved",
                    "Queue": "6500",
                    "Interface": "PJSIP/5002"
                })
                # Check status
                conn = rcm_queue_db.get_db_connection()
                row = conn.execute("SELECT status FROM queue_agents WHERE extension = '5002' AND queue_id = '6500'").fetchone()
                conn.close()
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "OFFLINE")

            # --- 2. Static Agent Sanity ---
            conn = rcm_queue_db.get_db_connection()
            static_rows = conn.execute("SELECT type, logout_time FROM queue_agents WHERE extension = '5001'").fetchall()
            conn.close()
            for s_row in static_rows:
                self.assertEqual(s_row["type"], "STATIC")
                # Static agents should not have logout time set during dynamic logouts
                self.assertIsNone(s_row["logout_time"])

            # --- 3. Pause/Unpause Restrictions ---
            # Try to pause extension 5009 (not a member of the queue)
            res = self.client.post("/call-center/supervisor/control", json={
                "command": "pause",
                "agent": "5009",
                "queue": "6500",
                "reason": "Break"
            })
            self.assertEqual(res.status_code, 400)
            self.assertIn("Agent is not a member of this queue", res.get_json()["error"])
            
            # Verify 5009 is not in database as paused
            conn = rcm_queue_db.get_db_connection()
            cnt = conn.execute("SELECT COUNT(*) FROM queue_agents WHERE extension = '5009'").fetchone()[0]
            conn.close()
            self.assertEqual(cnt, 0)
            
            # Pause valid static agent 5001
            res = self.client.post("/call-center/supervisor/control", json={
                "command": "pause",
                "agent": "5001",
                "queue": "6500",
                "reason": "Break"
            })
            self.assertEqual(res.status_code, 200)
            # Simulate collector pause event
            rcm_queue_collector.handle_event({
                "Event": "QueueMemberPause",
                "Queue": "6500",
                "Interface": "PJSIP/5001",
                "Paused": "1"
            })
            conn = rcm_queue_db.get_db_connection()
            status = conn.execute("SELECT status FROM queue_agents WHERE extension = '5001' AND queue_id = '6500'").fetchone()["status"]
            conn.close()
            self.assertEqual(status, "PAUSED")

            # Unpause valid static agent 5001
            res = self.client.post("/call-center/supervisor/control", json={
                "command": "unpause",
                "agent": "5001",
                "queue": "6500"
            })
            self.assertEqual(res.status_code, 200)
            # Simulate collector unpause event
            rcm_queue_collector.handle_event({
                "Event": "QueueMemberPause",
                "Queue": "6500",
                "Interface": "PJSIP/5001",
                "Paused": "0"
            })
            conn = rcm_queue_db.get_db_connection()
            status = conn.execute("SELECT status FROM queue_agents WHERE extension = '5001' AND queue_id = '6500'").fetchone()["status"]
            conn.close()
            self.assertEqual(status, "AVAILABLE")

            # --- 4. Call Completions & Drops ---
            if ctype == "ANSWERED":
                # Join
                rcm_queue_collector.handle_event({
                    "Event": "QueueCallerJoin",
                    "Queue": "6500",
                    "CallerIDNum": caller_num,
                    "Uniqueid": uniqueid
                })
                # Ring
                rcm_queue_collector.handle_event({
                    "Event": "AgentCalled",
                    "Queue": "6500",
                    "Uniqueid": uniqueid,
                    "AgentCalled": "PJSIP/5001"
                })
                # Connect
                rcm_queue_collector.handle_event({
                    "Event": "AgentConnect",
                    "Queue": "6500",
                    "Uniqueid": uniqueid,
                    "Member": "PJSIP/5001"
                })
                # Hangup
                rcm_queue_collector.handle_event({
                    "Event": "Hangup",
                    "Uniqueid": uniqueid,
                    "Cause-txt": "Normal Clearing"
                })
            elif ctype == "ABANDONED":
                # Join
                rcm_queue_collector.handle_event({
                    "Event": "QueueCallerJoin",
                    "Queue": "6500",
                    "CallerIDNum": caller_num,
                    "Uniqueid": uniqueid
                })
                # Abandon
                rcm_queue_collector.handle_event({
                    "Event": "QueueCallerAbandon",
                    "Uniqueid": uniqueid
                })
                # Hangup
                rcm_queue_collector.handle_event({
                    "Event": "Hangup",
                    "Uniqueid": uniqueid,
                    "Cause-txt": "Normal Clearing"
                })
            elif ctype == "CANCELLED":
                # Join
                rcm_queue_collector.handle_event({
                    "Event": "QueueCallerJoin",
                    "Queue": "6500",
                    "CallerIDNum": caller_num,
                    "Uniqueid": uniqueid
                })
                # Hangup Cancel
                rcm_queue_collector.handle_event({
                    "Event": "Hangup",
                    "Uniqueid": uniqueid,
                    "Cause-txt": "Cancel"
                })
            elif ctype == "NO_ANSWER":
                # Join
                rcm_queue_collector.handle_event({
                    "Event": "QueueCallerJoin",
                    "Queue": "6500",
                    "CallerIDNum": caller_num,
                    "Uniqueid": uniqueid
                })
                # Hangup No Answer
                rcm_queue_collector.handle_event({
                    "Event": "Hangup",
                    "Uniqueid": uniqueid,
                    "Cause-txt": "No Answer"
                })
            elif ctype == "TIMEOUT":
                # Join
                rcm_queue_collector.handle_event({
                    "Event": "QueueCallerJoin",
                    "Queue": "6500",
                    "CallerIDNum": caller_num,
                    "Uniqueid": uniqueid
                })
                # Ring
                rcm_queue_collector.handle_event({
                    "Event": "AgentCalled",
                    "Queue": "6500",
                    "Uniqueid": uniqueid,
                    "AgentCalled": "PJSIP/5001"
                })
                # Hangup Timeout
                rcm_queue_collector.handle_event({
                    "Event": "Hangup",
                    "Uniqueid": uniqueid,
                    "Cause-txt": "Timeout"
                })

            # Check that live call was immediately deleted from queue_live table
            conn = rcm_queue_db.get_db_connection()
            live_cnt = conn.execute("SELECT COUNT(*) FROM queue_live").fetchone()[0]
            conn.close()
            self.assertEqual(live_cnt, 0, f"Live call not deleted on hangup at iteration {i}")
            
            # Fetch from live API and verify Waiting and Talking calls are 0
            live_res = self.client.get("/call-center/live/api")
            live_data = live_res.get_json()
            self.assertEqual(len(live_data["active_calls"]), 0)

        print("Completed 55 iterations. Running mathematical verification of stats...")
        
        # Fetch Stats API
        stats_res = self.client.get("/call-center/stats/api?queue=6500")
        self.assertEqual(stats_res.status_code, 200)
        
        payload = stats_res.get_json()
        kpis = payload["kpis"]
        
        total_calls = kpis["total_calls"]
        answered = kpis["answered"]
        abandoned = kpis["abandoned"]
        standard_abandoned = kpis["standard_abandoned"]
        cancelled = kpis["cancelled"]
        no_answer = kpis["no_answer"]
        timeout = kpis["timeout"]
        
        print(f"Total: {total_calls} | Answered: {answered} | Abandoned: {abandoned}")
        print(f"Breakdown -> Standard Abandoned: {standard_abandoned} | Cancelled: {cancelled} | No Answer: {no_answer} | Timeout: {timeout}")
        
        # Assertions
        # 1. Total Calls = Answered + Abandoned
        self.assertEqual(total_calls, answered + abandoned)
        
        # 2. Abandoned Calls = Standard Abandoned + Cancelled + No Answer + Timeout
        self.assertEqual(abandoned, standard_abandoned + cancelled + no_answer + timeout)
        
        # 3. Distributions verification
        self.assertEqual(total_calls, 55)
        self.assertEqual(answered, 15)
        self.assertEqual(standard_abandoned, 10)
        self.assertEqual(cancelled, 10)
        self.assertEqual(no_answer, 10)
        self.assertEqual(timeout, 10)
        self.assertEqual(abandoned, 40)
        
        print("Mathematical Verification succeeded 100%!")

if __name__ == '__main__':
    unittest.main()