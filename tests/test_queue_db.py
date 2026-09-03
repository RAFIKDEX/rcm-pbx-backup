import builtins
import io
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from unittest import mock

import rcm_queue_collector
import rcm_queue_db


class QueueDbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = rcm_queue_db.DB_PATH
        rcm_queue_db.DB_PATH = os.path.join(self.tmpdir.name, "queue.db")
        rcm_queue_db.init_queue_db()
        rcm_queue_db.db_sync_queue("6500", "Support", "rrmemory", 10, 15, 2)
        rcm_queue_db.db_sync_queue("6501", "Sales", "linear", 5, 20, 3)

    def tearDown(self):
        rcm_queue_db.DB_PATH = self.old_db_path
        self.tmpdir.cleanup()

    def fetchone(self, query, params=()):
        with closing(rcm_queue_db.get_db_connection()) as conn:
            return conn.execute(query, params).fetchone()

    def fetchall(self, query, params=()):
        with closing(rcm_queue_db.get_db_connection()) as conn:
            return conn.execute(query, params).fetchall()

    def set_call_times(self, uniqueid, entry_delta=60, answer_delta=None):
        entry_time = (datetime.now() - timedelta(seconds=entry_delta)).strftime("%Y-%m-%d %H:%M:%S")
        with closing(rcm_queue_db.get_db_connection()) as conn:
            if answer_delta is None:
                conn.execute("UPDATE queue_calls SET entry_time = ? WHERE uniqueid = ?", (entry_time, uniqueid))
            else:
                answer_time = (datetime.now() - timedelta(seconds=answer_delta)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE queue_calls SET entry_time = ?, answer_time = ? WHERE uniqueid = ?",
                    (entry_time, answer_time, uniqueid),
                )
            conn.commit()

    def test_queue_tables_are_created_with_expected_columns(self):
        expected = {
            "queues": {"queue_number", "queue_name", "strategy", "max_members", "timeout", "retry"},
            "queue_calls": {"uniqueid", "linkedid", "caller_number", "queue_id", "status", "wait_time", "talk_time"},
            "queue_agents": {"extension", "agent_name", "queue_id", "type", "status", "login_time", "logout_time"},
            "queue_agent_events": {"agent", "queue", "event_type", "uniqueid", "timestamp"},
            "queue_live": {"call_id", "queue", "caller", "position", "state", "agent", "start_time", "last_update"},
        }

        with closing(rcm_queue_db.get_db_connection()) as conn:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            for table, columns in expected.items():
                self.assertIn(table, tables)
                actual = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                self.assertTrue(columns.issubset(actual), f"{table} missing {columns - actual}")

    def test_inserted_queue_events_are_stored_correctly(self):
        rcm_queue_db.db_call_enter("uid-insert", "lid-insert", "2015550100", "6500")
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_agent_call_event("5001", "6500", "RING", "uid-insert")

        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-insert",))
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-insert",))
        agent = self.fetchone("SELECT * FROM queue_agents WHERE extension = ?", ("5001",))
        events = self.fetchall("SELECT event_type FROM queue_agent_events ORDER BY id")

        self.assertEqual(call["queue_id"], "6500")
        self.assertEqual(call["queue_name"], "Support")
        self.assertEqual(call["caller_number"], "2015550100")
        self.assertEqual(call["status"], "ENTERED")
        self.assertEqual(live["state"], "WAITING")
        self.assertEqual(agent["type"], "STATIC")
        self.assertEqual(agent["status"], "BUSY")
        self.assertIn("ENTERQUEUE", [e["event_type"] for e in events])
        self.assertIn("RING", [e["event_type"] for e in events])

    def test_queue_lifecycle_join_waiting_ringing_answer_talking_complete(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "DYNAMIC")

        rcm_queue_db.db_call_enter("uid-complete", "uid-complete", "2015550101", "6500")
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-complete",))
        self.assertEqual(live["state"], "WAITING")
        self.assertEqual(live["position"], 1)

        rcm_queue_db.db_call_ring("uid-complete", "5001")
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-complete",))
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-complete",))
        self.assertEqual(call["status"], "RINGING")
        self.assertEqual(live["state"], "RINGING")

        self.set_call_times("uid-complete", entry_delta=35)
        rcm_queue_db.db_call_answer("uid-complete", "5001")
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-complete",))
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-complete",))
        self.assertEqual(call["status"], "ANSWERED")
        self.assertGreaterEqual(call["wait_time"], 30)
        self.assertIsNotNone(live)
        self.assertEqual(live["state"], "TALKING")
        self.assertEqual(live["agent"], "5001")

        self.set_call_times("uid-complete", entry_delta=45, answer_delta=10)
        rcm_queue_db.db_call_hangup("uid-complete", "COMPLETECALLER")
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-complete",))
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-complete",))
        events = [r["event_type"] for r in self.fetchall("SELECT event_type FROM queue_agent_events ORDER BY id")]

        self.assertEqual(call["status"], "ANSWERED")
        self.assertGreaterEqual(call["talk_time"], 8)
        self.assertEqual(call["hangup_reason"], "COMPLETECALLER")
        self.assertIsNone(live)
        self.assertIn("COMPLETE", events)

    def test_queue_lifecycle_abandon_removes_live_call(self):
        rcm_queue_db.db_call_enter("uid-abandon", "uid-abandon", "2015550102", "6500")
        self.set_call_times("uid-abandon", entry_delta=25)

        rcm_queue_db.db_call_abandon("uid-abandon")

        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-abandon",))
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-abandon",))
        event = self.fetchone(
            "SELECT * FROM queue_agent_events WHERE uniqueid = ? AND event_type = 'ABANDON'",
            ("uid-abandon",),
        )
        self.assertEqual(call["status"], "ABANDONED")
        self.assertGreaterEqual(call["wait_time"], 20)
        self.assertIsNone(live)
        self.assertEqual(event["queue"], "6500")

    def test_agent_login_logout_pause_unpause_static_dynamic(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_agent_login("5002", "6500", "Bob", "DYNAMIC")
        rcm_queue_db.db_agent_pause("5001", "6500", True)
        rcm_queue_db.db_agent_pause("5001", "6500", False)
        rcm_queue_db.db_agent_logout("5002", "6500")

        static_agent = self.fetchone("SELECT * FROM queue_agents WHERE extension = ?", ("5001",))
        dynamic_agent = self.fetchone("SELECT * FROM queue_agents WHERE extension = ?", ("5002",))
        events = [r["event_type"] for r in self.fetchall("SELECT event_type FROM queue_agent_events ORDER BY id")]

        self.assertEqual(static_agent["type"], "STATIC")
        self.assertEqual(static_agent["status"], "AVAILABLE")
        self.assertEqual(dynamic_agent["type"], "DYNAMIC")
        self.assertEqual(dynamic_agent["status"], "OFFLINE")
        self.assertIn("LOGIN", events)
        self.assertIn("LOGOUT", events)
        self.assertIn("PAUSE", events)
        self.assertIn("UNPAUSE", events)

    @mock.patch('rcm_queue_db.sync_queue_log_to_db')
    def test_statistics_and_agent_performance_calculations(self, mock_sync):
        now = datetime.now()
        rows = [
            ("answered-fast", "6500", "Support", "5001", "ANSWERED", 10, 120),
            ("answered-slow", "6500", "Support", "5001", "ANSWERED", 30, 60),
            ("abandoned", "6500", "Support", None, "ABANDONED", 40, 0),
        ]
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute(
                """
                INSERT INTO queue_agents (extension, agent_name, queue_id, type, status, login_time)
                VALUES ('5001', 'Alice', '6500', 'DYNAMIC', 'AVAILABLE', ?)
                """,
                ((now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),),
            )
            conn.execute(
                """
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES ('5001', '6500', 'LOGIN', ?)
                """,
                ((now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),),
            )
            for uid, queue_id, queue_name, agent, status, wait_time, talk_time in rows:
                conn.execute(
                    """
                    INSERT INTO queue_calls
                    (uniqueid, linkedid, caller_number, queue_id, queue_name, agent, entry_time, status, wait_time, talk_time)
                    VALUES (?, ?, '2015550199', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uid,
                        uid,
                        queue_id,
                        queue_name,
                        agent,
                        now.strftime("%Y-%m-%d %H:%M:%S"),
                        status,
                        wait_time,
                        talk_time,
                    ),
                )
            conn.commit()

        calls = rcm_queue_db.get_filtered_queue_stats({"queue": "6500"})
        total = len(calls)
        answered = [c for c in calls if c["status"] == "ANSWERED"]
        abandoned = [c for c in calls if c["status"] == "ABANDONED"]
        avg_wait = int(sum(c["wait_time"] for c in calls) / total)
        avg_talk = int(sum(c["talk_time"] for c in answered) / len(answered))
        sla = round((sum(1 for c in answered if c["wait_time"] <= 20) / total) * 100, 1)
        agents = rcm_queue_db.get_agent_analytics({})

        self.assertEqual(total, 3)
        self.assertEqual(len(answered), 2)
        self.assertEqual(len(abandoned), 1)
        self.assertEqual(avg_wait, 26)
        self.assertEqual(avg_talk, 90)
        self.assertEqual(sla, 33.3)
        self.assertEqual(agents[0]["calls"], 2)
        self.assertEqual(agents[0]["talk_time"], 180)
        self.assertEqual(agents[0]["avg_talk"], 90)

    def test_live_dashboard_calls_and_agent_status_change_then_hangup(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "DYNAMIC")
        rcm_queue_db.db_call_enter("uid-live", "uid-live", "2015550103", "6500")

        dashboard = rcm_queue_db.get_live_dashboard_status()
        self.assertEqual(len(dashboard["active_calls"]), 1)
        self.assertEqual(dashboard["active_calls"][0]["status"], "WAITING")
        self.assertEqual(dashboard["queues"]["6500"]["calls"], 1)

        rcm_queue_db.db_call_ring("uid-live", "5001")
        rcm_queue_db.db_agent_call_event("5001", "6500", "RING", "uid-live")
        dashboard = rcm_queue_db.get_live_dashboard_status()
        member = dashboard["queues"]["6500"]["members"][0]
        self.assertEqual(dashboard["active_calls"][0]["status"], "RINGING")
        self.assertEqual(member["extension"], "5001")
        self.assertEqual(member["state"], 3)

        rcm_queue_db.db_call_hangup("uid-live", "Caller left")
        dashboard = rcm_queue_db.get_live_dashboard_status()
        self.assertEqual(dashboard["active_calls"], [])

    def test_collector_handles_ami_events(self):
        events = [
            {"Event": "QueueMemberAdded", "Queue": "6500", "Interface": "PJSIP/5001", "MemberName": "Alice", "Membership": "STATIC"},
            {"Event": "QueueCallerJoin", "Queue": "6500", "CallerIDNum": "2015550104", "Uniqueid": "uid-ami", "Linkedid": "lid-ami"},
            {"Event": "AgentCalled", "Queue": "6500", "Uniqueid": "uid-ami", "AgentCalled": "PJSIP/5001"},
            {"Event": "AgentConnect", "Queue": "6500", "Uniqueid": "uid-ami", "Member": "PJSIP/5001"},
            {"Event": "QueueMemberPause", "Queue": "6500", "Interface": "PJSIP/5001", "Paused": "1"},
            {"Event": "QueueMemberPause", "Queue": "6500", "Interface": "PJSIP/5001", "Paused": "0"},
            {"Event": "AgentComplete", "Queue": "6500", "Uniqueid": "uid-ami", "Member": "PJSIP/5001", "Reason": "COMPLETEAGENT"},
            {"Event": "QueueMemberRemoved", "Queue": "6500", "Interface": "PJSIP/5001"},
        ]
        for event in events:
            rcm_queue_collector.handle_event(event)

        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-ami",))
        agent = self.fetchone("SELECT * FROM queue_agents WHERE extension = ?", ("5001",))
        event_types = [r["event_type"] for r in self.fetchall("SELECT event_type FROM queue_agent_events ORDER BY id")]

        self.assertEqual(call["status"], "ANSWERED")
        self.assertEqual(call["agent"], "5001")
        self.assertEqual(agent["type"], "STATIC")
        self.assertEqual(agent["status"], "OFFLINE")
        self.assertIn("RING", event_types)
        self.assertIn("ANSWER", event_types)
        self.assertIn("COMPLETE", event_types)

    def test_answered_call_stays_visible_as_talking_until_hangup(self):
        rcm_queue_db.db_call_enter("uid-talking", "uid-talking", "2015550108", "6500", "PJSIP/trunk-0002", 1)
        rcm_queue_db.db_call_ring("uid-talking", "5001")
        rcm_queue_db.db_call_answer("uid-talking", "5001")

        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-talking",))
        dashboard = rcm_queue_db.get_live_dashboard_status()
        active = [c for c in dashboard["active_calls"] if c["call_id"] == "uid-talking"]

        self.assertIsNotNone(live)
        self.assertEqual(live["state"], "TALKING")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["status"], "TALKING")

        rcm_queue_db.db_call_hangup("uid-talking", "COMPLETEAGENT")
        dashboard = rcm_queue_db.get_live_dashboard_status()
        active = [c for c in dashboard["active_calls"] if c["call_id"] == "uid-talking"]
        self.assertEqual(active, [])

    def test_talking_agent_details_include_caller_for_pjsip_agent_value(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_call_enter("uid-agent-detail", "uid-agent-detail", "2015550109", "6500", "PJSIP/trunk-0003", 1)
        rcm_queue_db.db_call_ring("uid-agent-detail", "PJSIP/5001")
        rcm_queue_db.db_call_answer("uid-agent-detail", "PJSIP/5001")
        self.set_call_times("uid-agent-detail", entry_delta=90, answer_delta=30)

        dashboard = rcm_queue_db.get_live_dashboard_status()
        roster = dashboard["queues"]["6500"]["roster"]
        agent = next(m for m in roster if m["extension"] == "5001")

        self.assertEqual(agent["caller_id"], "2015550109")
        self.assertGreaterEqual(agent["call_duration"], 20)

    def test_static_agent_live_details_do_not_report_login_duration(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_agent_login("5002", "6500", "Bob", "DYNAMIC")

        dashboard = rcm_queue_db.get_live_dashboard_status()
        roster = dashboard["queues"]["6500"]["roster"]
        static_agent = next(m for m in roster if m["extension"] == "5001")
        dynamic_agent = next(m for m in roster if m["extension"] == "5002")

        self.assertIsNone(static_agent["login_duration"])
        self.assertIsInstance(dynamic_agent["login_duration"], int)

    def test_dynamic_agent_login_duration_can_exceed_one_day(self):
        rcm_queue_db.db_agent_login("5002", "6500", "Bob", "DYNAMIC")
        old_login = (datetime.now() - timedelta(days=2, minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute(
                "UPDATE queue_agents SET login_time = ? WHERE extension = ? AND queue_id = ?",
                (old_login, "5002", "6500"),
            )
            conn.commit()

        dashboard = rcm_queue_db.get_live_dashboard_status()
        roster = dashboard["queues"]["6500"]["roster"]
        dynamic_agent = next(m for m in roster if m["extension"] == "5002")

        self.assertGreaterEqual(dynamic_agent["login_duration"], 2 * 24 * 60 * 60)

    @mock.patch("subprocess.run")
    def test_reconcile_keeps_live_call_when_queue_show_has_waiting_caller(self, mock_run):
        rcm_queue_db.db_call_enter("uid-live-wait", "uid-live-wait", "2015550107", "6500", "PJSIP/trunk-0001", 1)

        def fake_run(cmd, *args, **kwargs):
            result = mock.Mock()
            result.returncode = 0
            if "core show version" in cmd:
                result.stdout = "Asterisk 20.0.0"
            elif "core show channels concise" in cmd:
                result.stdout = ""
            elif "queue show" in cmd:
                result.stdout = (
                    "6500 has 1 calls (max unlimited) in 'rrmemory' strategy\n"
                    "   Members:\n"
                    "      PJSIP/5001 (Not in use)\n"
                    "   Callers:\n"
                    "      1. PJSIP/trunk-0001 (wait: 0:03, prio: 0)\n"
                )
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = fake_run

        rcm_queue_db.reconcile_with_asterisk_state()
        live = self.fetchone("SELECT * FROM queue_live WHERE call_id = ?", ("uid-live-wait",))
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-live-wait",))

        self.assertIsNotNone(live)
        self.assertEqual(live["state"], "WAITING")
        self.assertIsNone(call["hangup_time"])

    def test_queue_log_events_are_imported(self):
        base = int(time.time()) - 100
        queue_log = "\n".join(
            [
                f"{base}|uid-log|6500|NONE|ENTERQUEUE|1|2015550105",
                f"{base + 5}|uid-log|6500|PJSIP/5001|CONNECT|5",
                f"{base + 65}|uid-log|6500|PJSIP/5001|COMPLETECALLER|5|60|1",
                f"{base + 10}|uid-ab-log|6500|NONE|ENTERQUEUE|1|2015550106",
                f"{base + 25}|uid-ab-log|6500|NONE|ABANDON|1|1|15",
                f"{base + 30}|NONE|6500|PJSIP/5002|ADDMEMBER|",
                f"{base + 35}|NONE|6500|PJSIP/5002|PAUSE|",
                f"{base + 40}|NONE|6500|PJSIP/5002|UNPAUSE|",
                f"{base + 45}|NONE|6500|PJSIP/5002|REMOVEMEMBER|",
            ]
        )

        written_offsets = []

        def fake_exists(path):
            return path == "/var/log/asterisk/queue_log"

        def fake_open(path, mode="r", *args, **kwargs):
            if path == "/var/log/asterisk/queue_log":
                return io.StringIO(queue_log)
            if path.endswith("queue_log_new.offset"):
                stream = io.StringIO()
                original_close = stream.close

                def close():
                    written_offsets.append(stream.getvalue())
                    original_close()

                stream.close = close
                return stream
            raise FileNotFoundError(path)

        with mock.patch.object(rcm_queue_db.os.path, "exists", side_effect=fake_exists):
            with mock.patch("builtins.open", side_effect=fake_open):
                rcm_queue_db.sync_queue_log_to_db()

        answered = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-log",))
        abandoned = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-ab-log",))
        agent = self.fetchone("SELECT * FROM queue_agents WHERE extension = ?", ("5002",))
        events = [r["event_type"] for r in self.fetchall("SELECT event_type FROM queue_agent_events ORDER BY id")]

        self.assertEqual(answered["status"], "ANSWERED")
        self.assertEqual(answered["wait_time"], 5)
        self.assertEqual(answered["talk_time"], 60)
        self.assertEqual(abandoned["status"], "ABANDONED")
        self.assertEqual(abandoned["wait_time"], 15)
        self.assertEqual(agent["status"], "OFFLINE")
        self.assertIn("LOGIN", events)
        self.assertIn("PAUSE", events)
        self.assertIn("UNPAUSE", events)
        self.assertIn("LOGOUT", events)
        self.assertTrue(written_offsets)

    def test_live_dashboard_static_and_dynamic_agent_login_logout(self):
        # 1. Login STATIC agent
        rcm_queue_db.db_agent_login("5000", "6500", "Static Agent", "STATIC")
        # 2. Login DYNAMIC agent
        rcm_queue_db.db_agent_login("4321", "6500", "Dynamic Agent", "DYNAMIC")

        # Both should show up in dashboard
        dashboard = rcm_queue_db.get_live_dashboard_status()
        members = dashboard["queues"]["6500"]["members"]
        member_exts = [m["extension"] for m in members]
        self.assertIn("5000", member_exts)
        self.assertIn("4321", member_exts)

        # 3. Logout DYNAMIC agent
        rcm_queue_db.db_agent_logout("4321", "6500")

        # Dynamic agent should disappear, Static agent should remain
        dashboard = rcm_queue_db.get_live_dashboard_status()
        members = dashboard["queues"]["6500"]["members"]
        member_exts = [m["extension"] for m in members]
        self.assertIn("5000", member_exts)
        self.assertNotIn("4321", member_exts)

        # 4. Logout STATIC agent (just to verify it disappears from active members)
        rcm_queue_db.db_agent_logout("5000", "6500")
        dashboard = rcm_queue_db.get_live_dashboard_status()
        members = dashboard["queues"]["6500"]["members"]
        member_exts = [m["extension"] for m in members]
        self.assertNotIn("5000", member_exts)

    def test_scenario_1_caller_abandons_stores_position(self):
        rcm_queue_db.db_call_enter("scen-1", "scen-1", "5555", "6500", position=3)
        rcm_queue_db.db_call_abandon("scen-1")
        
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("scen-1",))
        self.assertEqual(call["status"], "ABANDONED")
        self.assertEqual(call["initial_position"], 3)
        self.assertEqual(call["last_position"], 3)
        self.assertEqual(call["hangup_by"], "CALLER")
        
        positions = self.fetchall("SELECT position, event FROM queue_call_positions WHERE uniqueid = ? ORDER BY id", ("scen-1",))
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0]["event"], "ENTERQUEUE")
        self.assertEqual(positions[0]["position"], 3)
        self.assertEqual(positions[1]["event"], "ABANDON")
        self.assertEqual(positions[1]["position"], 3)

    def test_scenario_2_caller_hangs_up_answered_call(self):
        rcm_queue_db.db_call_enter("scen-2", "scen-2", "5555", "6500", position=1)
        rcm_queue_db.db_call_answer("scen-2", "5001")
        rcm_queue_db.db_call_hangup("scen-2", "COMPLETECALLER")
        
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("scen-2",))
        self.assertEqual(call["status"], "ANSWERED")
        self.assertEqual(call["hangup_by"], "CALLER")
        
    def test_scenario_3_agent_hangs_up_answered_call(self):
        rcm_queue_db.db_call_enter("scen-3", "scen-3", "5555", "6500", position=1)
        rcm_queue_db.db_call_answer("scen-3", "5001")
        rcm_queue_db.db_call_hangup("scen-3", "COMPLETEAGENT")
        
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("scen-3",))
        self.assertEqual(call["status"], "ANSWERED")
        self.assertEqual(call["hangup_by"], "AGENT")
        
    def test_scenario_4_agent_queue_login_logout(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "DYNAMIC")
        dashboard = rcm_queue_db.get_live_dashboard_status()
        members = dashboard["queues"]["6500"]["members"]
        member_exts = [m["extension"] for m in members]
        self.assertIn("5001", member_exts)
        
        rcm_queue_db.db_agent_logout("5001", "6500")
        dashboard = rcm_queue_db.get_live_dashboard_status()
        members = dashboard["queues"]["6500"]["members"]
        member_exts = [m["extension"] for m in members]
        self.assertNotIn("5001", member_exts)

    def test_fix_1_queue_log_rotation_offset_reset(self):
        offset_file = "/root/RCM_7021/queue_log_new.offset"
        with open(offset_file, "w") as f:
            f.write("999999")
            
        def fake_exists(path):
            return path == "/var/log/asterisk/queue_log" or path == offset_file
            
        original_open = builtins.open
        def fake_open(path, mode="r", *args, **kwargs):
            if path == "/var/log/asterisk/queue_log":
                return io.StringIO("")
            return original_open(path, mode, *args, **kwargs)
            
        with mock.patch("os.path.exists", side_effect=fake_exists), \
             mock.patch("builtins.open", side_effect=fake_open), \
             mock.patch("os.path.getsize", return_value=100):
            rcm_queue_db.sync_queue_log_to_db()
        
        with open(offset_file, "r") as f:
            new_offset = int(f.read().strip())
        self.assertEqual(new_offset, 0)

    def test_fix_2_enterqueue_parsing(self):
        # We test sync_queue_log_to_db parsing under different ENTERQUEUE formats.
        # We'll use mock.patch to simulate queue_log file contents
        base = int(time.time()) - 100
        
        # Test standard format with URL: url|callerid|position
        # Test standard format with empty URL: |callerid|position
        # Test non-standard format: position|callerid
        lines = [
            f"{base}|uid-std-url|6500|NONE|ENTERQUEUE|http://url|2015550110|3",
            f"{base + 5}|uid-std-no-url|6500|NONE|ENTERQUEUE||2015550111|4",
            f"{base + 10}|uid-test-fmt|6500|NONE|ENTERQUEUE|2|2015550112"
        ]
        
        # Simulate log file reading
        def fake_exists(path):
            return path == "/var/log/asterisk/queue_log" or path.endswith("queue_log_new.offset")
            
        original_open = builtins.open
        def fake_open(path, mode="r", *args, **kwargs):
            if path == "/var/log/asterisk/queue_log":
                return io.StringIO("\n".join(lines))
            return original_open(path, mode, *args, **kwargs)
            
        with mock.patch("os.path.exists", side_effect=fake_exists), \
             mock.patch("builtins.open", side_effect=fake_open), \
             mock.patch("os.path.getsize", return_value=1000):
            # Clean offset before test
            offset_file = "/root/RCM_7021/queue_log_new.offset"
            if os.path.exists(offset_file):
                os.remove(offset_file)
            rcm_queue_db.sync_queue_log_to_db()
            
        c1 = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-std-url",))
        c2 = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-std-no-url",))
        c3 = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("uid-test-fmt",))
        
        self.assertEqual(c1["caller_number"], "2015550110")
        self.assertEqual(c1["initial_position"], 3)
        
        self.assertEqual(c2["caller_number"], "2015550111")
        self.assertEqual(c2["initial_position"], 4)
        
        self.assertEqual(c3["caller_number"], "2015550112")
        self.assertEqual(c3["initial_position"], 2)

    def test_fix_3_and_4_agent_analytics_date_and_boundary_filtering(self):
        # Insert events for agent 5001
        # Login yesterday, logout today, pause today, unpause today
        now = datetime.now()
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        today_start_str = now.strftime("%Y-%m-%d") + " 00:00:00"
        today_noon_str = now.strftime("%Y-%m-%d") + " 12:00:00"
        
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute("DELETE FROM queue_agent_events")
            conn.execute("DELETE FROM queue_agents")
            # Create a dynamic agent entry
            conn.execute("INSERT INTO queue_agents (extension, agent_name, queue_id, type, status) VALUES ('5001', 'Alice', '6500', 'DYNAMIC', 'AVAILABLE')")
            conn.execute("INSERT INTO queue_agents (extension, agent_name, queue_id, type, status) VALUES ('5002', 'Bob', '6500', 'DYNAMIC', 'AVAILABLE')")
            
            # Events for Alice: logged in yesterday
            conn.execute("INSERT INTO queue_agent_events (agent, queue, event_type, timestamp) VALUES ('5001', '6500', 'LOGIN', ?)", (yesterday_str,))
            # Events for Bob: logged in today at noon
            conn.execute("INSERT INTO queue_agent_events (agent, queue, event_type, timestamp) VALUES ('5002', '6500', 'LOGIN', ?)", (today_noon_str,))
            conn.commit()
            
        # Test date filtering in agent analytics: only today
        filters = {
            "date_from": now.strftime("%Y-%m-%d"),
            "date_to": now.strftime("%Y-%m-%d"),
            "agent": "5001"
        }
        
        analytics = rcm_queue_db.get_agent_analytics(filters)
        self.assertEqual(len(analytics), 1)
        self.assertEqual(analytics[0]["extension"], "5001")
        # Alice was logged in before today, so boundary calculation should include her previous state
        # Her session duration today should be calculated from today_start_str to now (or end_boundary)
        self.assertGreater(analytics[0]["online_time"], 0)
        self.assertEqual(len(analytics[0]["sessions"]), 1)
        
        # Test dynamic agents filtering in sessions
        sessions = rcm_queue_db.get_all_agent_sessions(filters)
        # Should only return Alice's sessions since filter specified agent="5001"
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["extension"], "5001")

    def test_fix_5_queue_name_mapping(self):
        # Verify queue name uses queues table mapping
        # queues table mapping says '6500' -> 'Support'
        rcm_queue_db.db_call_enter("name-test-1", "name-test-1", "5555", "6500")
        
        stats = rcm_queue_db.get_filtered_queue_stats({"queue": "6500"})
        self.assertGreater(len(stats), 0)
        self.assertEqual(stats[0]["queue_name"], "Support")
        
        paginated = rcm_queue_db.get_paginated_queue_calls({"queue": "6500"})
        self.assertGreater(len(paginated["data"]), 0)
        self.assertEqual(paginated["data"][0]["queue_name"], "Support")
        
        timeline = rcm_queue_db.get_call_details_timeline("name-test-1")
        self.assertEqual(timeline["queue_name"], "Support")

    def test_transfer_target_queue_scope_includes_original_queue_leg(self):
        """A 6501-scoped user can list a call transferred into 6501."""
        rcm_queue_db.db_call_enter("transfer-visible", "transfer-linked", "5555", "6500")
        rcm_queue_db.db_call_transfer_event("transfer-visible", "6501", "6500")

        filters = {
            "queue": "all",
            "_scope_queue_ids": {"6501"},
            "date_from": "",
            "date_to": "",
        }
        stats = rcm_queue_db.get_filtered_queue_stats(dict(filters))
        paginated = rcm_queue_db.get_paginated_queue_calls({**filters, "page": 1, "limit": 50})

        self.assertIn("transfer-visible", {call["uniqueid"] for call in stats})
        self.assertIn("transfer-visible", {call["uniqueid"] for call in paginated["data"]})

    def test_agent_occupancy_contains_work_mix_and_transfer_counts(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "DYNAMIC")
        login_time = (datetime.now() - timedelta(seconds=180)).strftime("%Y-%m-%d %H:%M:%S")
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute(
                "UPDATE queue_agent_events SET timestamp = ? WHERE agent = '5001' AND queue = '6500' AND event_type = 'LOGIN'",
                (login_time,),
            )
            conn.commit()
        rcm_queue_db.db_call_enter("occupancy-call", "occupancy-linked", "5555", "6500")
        self.set_call_times("occupancy-call", entry_delta=60)
        rcm_queue_db.db_call_answer("occupancy-call", "5001")
        self.set_call_times("occupancy-call", entry_delta=90, answer_delta=30)
        rcm_queue_db.db_call_hangup("occupancy-call", "COMPLETECALLER")
        rcm_queue_db.db_call_transfer_event("occupancy-call", "6501", "6500")

        rows = rcm_queue_db.get_agent_occupancy({"queue": "6500"})
        agent = next(row for row in rows if row["extension"] == "5001")

        self.assertEqual(agent["answered_calls"], 1)
        self.assertGreater(agent["talk_time"], 0)
        self.assertGreaterEqual(agent["hold_time"], 0)
        self.assertGreaterEqual(agent["available_time"], 0)
        self.assertIsNotNone(agent["occupancy_percent"])
        self.assertEqual(agent["transfers_out"], 1)
        self.assertEqual(agent["transfers_in"], 0)
        self.assertEqual(agent["calls_detail"][0]["uniqueid"], "occupancy-call")

    def test_fix_6_ghost_call_talk_time_prevention(self):
        # Enter and answer a call
        rcm_queue_db.db_call_enter("ghost-1", "ghost-1", "5555", "6500")
        rcm_queue_db.db_call_answer("ghost-1", "5001")
        
        # Simulate time passing by artificially modifying answer_time to yesterday
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute("UPDATE queue_calls SET answer_time = ? WHERE uniqueid = ?", (yesterday_str, "ghost-1"))
            conn.commit()
            
        # Reconcile ghost call
        rcm_queue_db.db_call_hangup("ghost-1", "Ghost Call Auto-Reconciliation")
        
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("ghost-1",))
        # Talk time should be set to 0 to prevent fake huge values, not 86400+ seconds
        self.assertEqual(call["talk_time"], 0)

    def test_audit_duplicate_agent_events(self):
        # 1. Login twice, should only record 1 event
        rcm_queue_db.db_agent_login("5005", "6500", "Charlie", "DYNAMIC")
        rcm_queue_db.db_agent_login("5005", "6500", "Charlie", "DYNAMIC")
        
        events = self.fetchall("SELECT * FROM queue_agent_events WHERE agent = '5005' AND event_type = 'LOGIN'")
        self.assertEqual(len(events), 1)
        
        # 2. Pause twice, should only record 1 event
        rcm_queue_db.db_agent_pause("5005", "6500", True)
        rcm_queue_db.db_agent_pause("5005", "6500", True)
        
        events_pause = self.fetchall("SELECT * FROM queue_agent_events WHERE agent = '5005' AND event_type = 'PAUSE'")
        self.assertEqual(len(events_pause), 1)
        
        # 3. Unpause twice, should only record 1 event
        rcm_queue_db.db_agent_pause("5005", "6500", False)
        rcm_queue_db.db_agent_pause("5005", "6500", False)
        
        events_unpause = self.fetchall("SELECT * FROM queue_agent_events WHERE agent = '5005' AND event_type = 'UNPAUSE'")
        self.assertEqual(len(events_unpause), 1)
        
        # 4. Logout twice, should only record 1 event
        rcm_queue_db.db_agent_logout("5005", "6500")
        rcm_queue_db.db_agent_logout("5005", "6500")
        
        events_logout = self.fetchall("SELECT * FROM queue_agent_events WHERE agent = '5005' AND event_type = 'LOGOUT'")
        self.assertEqual(len(events_logout), 1)

    def test_audit_hold_time_calculation(self):
        now = datetime.now()
        twenty_seconds_ago = (now - timedelta(seconds=20)).strftime("%Y-%m-%d %H:%M:%S")
        ten_seconds_ago = (now - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
        five_seconds_ago = (now - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")

        # Setup call in DB
        rcm_queue_db.db_call_enter("hold-test-1", "hold-test-1", "5555", "6500")
        rcm_queue_db.db_call_answer("hold-test-1", "5005")
        
        # Artificially insert first hold and unhold events
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES ('5005', '6500', 'HOLD', 'hold-test-1', ?)
            """, (twenty_seconds_ago,))
            conn.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES ('5005', '6500', 'UNHOLD', 'hold-test-1', ?)
            """, (ten_seconds_ago,))
            conn.execute("UPDATE queue_calls SET hold_time = 10 WHERE uniqueid = ?", ("hold-test-1",))
            conn.commit()

        # Check initial hold time
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("hold-test-1",))
        self.assertEqual(call["hold_time"], 10)

        # Put on hold again
        rcm_queue_db.db_call_hold_event("hold-test-1", True)

        # Artificially update second HOLD event's timestamp to five_seconds_ago
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute("""
                UPDATE queue_agent_events 
                SET timestamp = ? 
                WHERE uniqueid = 'hold-test-1' AND event_type = 'HOLD' 
                  AND id = (SELECT MAX(id) FROM queue_agent_events WHERE uniqueid = 'hold-test-1' AND event_type = 'HOLD')
            """, (five_seconds_ago,))
            conn.commit()

        # Hang up call while on hold, should add ~5 seconds of second hold to hold_time
        rcm_queue_db.db_call_hangup("hold-test-1", "Hangup")

        # Check total hold time is cumulative (10s + ~5s = ~15s)
        call = self.fetchone("SELECT * FROM queue_calls WHERE uniqueid = ?", ("hold-test-1",))
        self.assertGreaterEqual(call["hold_time"], 14)
        self.assertLessEqual(call["hold_time"], 18)


if __name__ == "__main__":
    unittest.main()
