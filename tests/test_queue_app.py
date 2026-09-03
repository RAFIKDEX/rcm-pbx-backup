import csv
import importlib
import io
import os
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from unittest import mock

import db
import rcm_queue_db


class QueueAppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.old_main_db = db.DB_PATH
        cls.old_queue_db = rcm_queue_db.DB_PATH
        db.DB_PATH = os.path.join(cls.tmpdir.name, "main.db")
        rcm_queue_db.DB_PATH = os.path.join(cls.tmpdir.name, "queue.db")
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.flask_app = cls.app_module.app
        cls.flask_app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.old_main_db
        rcm_queue_db.DB_PATH = cls.old_queue_db
        cls.tmpdir.cleanup()

    def setUp(self):
        self.reset_queue_db()
        self.client = self.flask_app.test_client()
        self.queues = [
            {
                "queue_number": "6500",
                "name": "Support",
                "strategy": "rrmemory",
                "music_on_hold": "default",
                "ring_time": 15,
                "retry_time": 2,
                "wrapup_time": 5,
                "max_queue_length": 10,
                "static_agents": ["5001"],
                "servicelevel": 20,
            }
        ]
        self.extensions = [
            {"ext": "5001", "name": "Alice", "enabled": 1},
            {"ext": "5002", "name": "Bob", "enabled": 1},
        ]
        self.ami_commands = []
        self.patches = [
            mock.patch.object(self.app_module.db, "get_queues", side_effect=lambda: self.queues),
            mock.patch.object(self.app_module.db, "save_queues", side_effect=self.save_queues),
            mock.patch.object(self.app_module.db, "get_all_extensions", side_effect=lambda: self.extensions),
            mock.patch.object(self.app_module.db, "get_media_center_db", return_value={"prompts": [], "moh_classes": []}),
            mock.patch.object(self.app_module.db, "get_queue_alerts", return_value=[]),
            mock.patch.object(self.app_module.db, "add_queue_alert", return_value=None),
            mock.patch.object(self.app_module.db, "get_caller_lists", return_value=[]),
            mock.patch.object(self.app_module.db, "get_callback_requests", return_value=[]),
            mock.patch.object(self.app_module.db, "get_queue_sessions", side_effect=rcm_queue_db.get_queue_sessions),
            mock.patch.object(self.app_module.db, "get_queue_pauses", side_effect=rcm_queue_db.get_queue_pauses),
            mock.patch.object(self.app_module.db, "get_filtered_queue_stats", side_effect=rcm_queue_db.get_filtered_queue_stats),
            mock.patch.object(self.app_module.db, "get_agent_analytics", side_effect=rcm_queue_db.get_agent_analytics),
            mock.patch.object(self.app_module.asterisk_helper, "sync_queue_dialplan", return_value=None),
            mock.patch.object(self.app_module.asterisk_helper, "get_live_queue_status", side_effect=self.live_queue_status),
            mock.patch.object(self.app_module.asterisk_helper, "get_live_calls_list", return_value=[]),
            mock.patch.object(self.app_module.asterisk_helper, "send_ami_command", side_effect=self.send_ami_command),
            mock.patch.object(self.app_module.asterisk_helper, "run_asterisk_cmd", side_effect=self.mock_run_asterisk_cmd),
            mock.patch.object(self.app_module, "add_pending_change", return_value=None),
            mock.patch.object(self.app_module, "get_pending_changes", return_value=[]),
            mock.patch("rcm_queue_db.sync_queue_log_to_db", return_value=None),
        ]
        for patcher in self.patches:
            patcher.start()
        with self.client.session_transaction() as session:
            session["logged_in"] = True

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    def reset_queue_db(self):
        if os.path.exists(rcm_queue_db.DB_PATH):
            os.unlink(rcm_queue_db.DB_PATH)
        rcm_queue_db.init_queue_db()
        rcm_queue_db.db_sync_queue("6500", "Support", "rrmemory", 10, 15, 2, 20)

    def save_queues(self, queues):
        self.queues = queues
        for q in queues:
            rcm_queue_db.db_sync_queue(
                q["queue_number"],
                q["name"],
                q.get("strategy", "rrmemory"),
                q.get("max_queue_length", 10),
                q.get("ring_time", 15),
                q.get("retry_time", 2),
                q.get("servicelevel", 20),
            )

    def live_queue_status(self):
        status = rcm_queue_db.get_live_dashboard_status()["queues"]
        if "6500" not in status:
            status["6500"] = {
                "name": "Support",
                "calls": 0,
                "completed": 0,
                "abandoned": 0,
                "holdtime": 0,
                "talktime": 0,
                "servicelevelperf": 100.0,
                "members": [],
                "entries": [],
            }
        return status

    def send_ami_command(self, action, params):
        self.ami_commands.append((action, params))
        return "Response: Success"

    def mock_run_asterisk_cmd(self, cmd):
        import re
        pause_m = re.match(r"queue (pause|unpause) member (PJSIP/\w+) (?:from|queue) (\w+)", cmd)
        if pause_m:
            action, member, queue = pause_m.groups()
            self.ami_commands.append(("QueuePause", {"Interface": member, "Queue": queue, "Paused": "true" if action == "pause" else "false"}))
            return "Success"
            
        remove_m = re.match(r"queue remove member (PJSIP/\w+) from (\w+)", cmd)
        if remove_m:
            member, queue = remove_m.groups()
            self.ami_commands.append(("QueueRemove", {"Interface": member, "Queue": queue}))
            return "Success"
            
        add_m = re.match(r"queue add member (PJSIP/\w+) to (\w+)", cmd)
        if add_m:
            member, queue = add_m.groups()
            self.ami_commands.append(("QueueAdd", {"Interface": member, "Queue": queue}))
            return "Success"
            
        return ""

    def seed_calls_and_agents(self):
        now = datetime.now()
        with closing(rcm_queue_db.get_db_connection()) as conn:
            conn.execute(
                """
                INSERT INTO queue_agents (extension, agent_name, queue_id, type, status, login_time)
                VALUES ('5001', 'Alice', '6500', 'STATIC', 'AVAILABLE', ?)
                """,
                ((now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),),
            )
            conn.execute(
                """
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES ('5001', '6500', 'LOGIN', ?)
                """,
                ((now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),),
            )
            rows = [
                ("uid-api-1", "2015550111", "5001", "ANSWERED", 10, 100),
                ("uid-api-2", "2015550112", "5001", "ANSWERED", 25, 80),
                ("uid-api-3", "2015550113", None, "ABANDONED", 30, 0),
            ]
            for uniqueid, caller, agent, status, wait_time, talk_time in rows:
                entry_time = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
                answer_time = (now - timedelta(minutes=9)).strftime("%Y-%m-%d %H:%M:%S") if agent else None
                hangup_time = (now - timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """
                    INSERT INTO queue_calls
                    (uniqueid, linkedid, caller_number, queue_id, queue_name, agent, entry_time,
                     answer_time, hangup_time, status, wait_time, talk_time, hangup_reason)
                    VALUES (?, ?, ?, '6500', 'Support', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uniqueid,
                        uniqueid,
                        caller,
                        agent,
                        entry_time,
                        answer_time,
                        hangup_time,
                        status,
                        wait_time,
                        talk_time,
                        "COMPLETECALLER" if agent else "ABANDON",
                    ),
                )
            conn.execute(
                """
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES ('5001', '6500', 'RING', 'uid-api-1', ?)
                """,
                ((now - timedelta(minutes=9, seconds=30)).strftime("%Y-%m-%d %H:%M:%S"),),
            )
            conn.commit()

    def test_queue_gui_pages_load_and_show_data(self):
        self.seed_calls_and_agents()
        pages = [
            ("/queues", b"Support"),
            ("/call-center/stats", b"Contact Center Analytics"),
            ("/call-center/live", b"Queue Live Wallboard"),
            ("/call-center/queues/6500", b"Queue Details"),
        ]

        for path, expected in pages:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(expected, response.data, path)

    def test_queue_static_agent_buttons_add_and_remove(self):
        add_response = self.client.post("/queues/6500/agents/add", data={"agent": "5002"})
        self.assertEqual(add_response.status_code, 200)
        self.assertIn("5002", self.queues[0]["static_agents"])

        duplicate_response = self.client.post("/queues/6500/agents/add", data={"agent": "5002"})
        self.assertEqual(duplicate_response.status_code, 400)

        remove_response = self.client.post("/queues/6500/agents/remove", data={"agent": "5002"})
        self.assertEqual(remove_response.status_code, 200)
        self.assertNotIn("5002", self.queues[0]["static_agents"])

    def test_dynamic_agent_join_leave_and_pause_buttons_send_ami(self):
        join_response = self.client.post("/queues/6500/agents/join", data={"agent": "5002"})
        self.assertEqual(join_response.status_code, 200)
        self.assertEqual(self.ami_commands[-1][0], "QueueAdd")
        self.assertEqual(self.ami_commands[-1][1]["Interface"], "PJSIP/5002")

        rcm_queue_db.db_agent_login("5002", "6500", "Bob", "DYNAMIC")
        leave_response = self.client.post("/queues/6500/agents/leave", data={"agent": "5002"})
        self.assertEqual(leave_response.status_code, 200)
        self.assertEqual(self.ami_commands[-1][0], "QueueRemove")

        pause_response = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "pause", "agent": "5002", "queue": "6500", "reason": "Break"},
        )
        unpause_response = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "unpause", "agent": "5002", "queue": "6500"},
        )
        self.assertEqual(pause_response.status_code, 200)
        self.assertEqual(unpause_response.status_code, 200)
        self.assertEqual(self.ami_commands[-2][0], "QueuePause")
        self.assertEqual(self.ami_commands[-2][1]["Paused"], "true")
        self.assertEqual(self.ami_commands[-1][1]["Paused"], "false")

        hangup_res = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "hangup_call", "channel": "PJSIP/5001-000001"}
        )
        self.assertEqual(hangup_res.status_code, 200)

        logout_res = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "logout_agent", "agent": "5002", "queue": "6500"}
        )
        self.assertEqual(logout_res.status_code, 200)

        transfer_res = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "transfer_call", "channel": "PJSIP/5001-000001", "exten": "5003"}
        )
        self.assertEqual(transfer_res.status_code, 200)

    def test_static_agent_enable_disable_buttons_update_disabled_list(self):
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_agent_pause("5001", "6500", False)

        disable_response = self.client.post("/queues/6500/agents/disable", data={"agent": "5001"})
        self.assertEqual(disable_response.status_code, 200)
        self.assertIn("5001", self.queues[0]["disabled_agents"])
        self.assertEqual(self.ami_commands[-1][0], "QueuePause")
        self.assertEqual(self.ami_commands[-1][1]["Paused"], "true")

        rcm_queue_db.db_agent_pause("5001", "6500", True)
        enable_response = self.client.post("/queues/6500/agents/enable", data={"agent": "5001"})
        self.assertEqual(enable_response.status_code, 200)
        self.assertNotIn("5001", self.queues[0]["disabled_agents"])
        self.assertEqual(self.ami_commands[-1][1]["Paused"], "false")

    def test_queue_stats_api_returns_non_empty_statistics(self):
        self.seed_calls_and_agents()

        response = self.client.get("/call-center/stats/api?queue=6500")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(payload["kpis"]["total_calls"], 3)
        self.assertEqual(payload["kpis"]["answered"], 2)
        self.assertEqual(payload["kpis"]["abandoned"], 1)
        self.assertEqual(payload["kpis"]["cancelled"], 0)
        self.assertEqual(payload["kpis"]["no_answer"], 0)
        self.assertEqual(payload["kpis"]["avg_wait"], 21)
        self.assertEqual(payload["kpis"]["avg_talk"], 90)
        self.assertEqual(payload["kpis"]["sla_pct"], 33.3)
        self.assertEqual(payload["queues_table"][0]["queue"], "6500")
        self.assertEqual(payload["queues_table"][0]["queue_name"], "Support")
        self.assertIn("current_waiting", payload["queues_table"][0])
        self.assertIn("current_talking", payload["queues_table"][0])
        self.assertIn("available_agents", payload["queues_table"][0])
        self.assertEqual(payload["agent_analytics"][0]["calls"], 2)
        self.assertEqual(payload["agent_analytics"][0]["type"], "STATIC")
        self.assertEqual(payload["agent_analytics"][0]["status"], "AVAILABLE")
        self.assertIsNone(payload["agent_analytics"][0]["login_duration"])
        self.assertIsNone(payload["agent_analytics"][0]["online_time"])
        self.assertIsNone(payload["agent_analytics"][0]["pause_time"])
        self.assertIsNone(payload["agent_analytics"][0]["available_time"])
        self.assertEqual(payload["agent_analytics"][0]["sessions"], [])
        self.assertEqual(payload["agent_analytics"][0]["pauses"], [])

    def test_unified_stats_live_dashboard_details_and_timeline_apis(self):
        self.seed_calls_and_agents()
        rcm_queue_db.db_call_enter("uid-live-api", "uid-live-api", "2015550199", "6500")

        unified = self.client.get("/api/queue-stats?queue=6500")
        self.assertEqual(unified.status_code, 200)
        unified_payload = unified.get_json()
        self.assertGreaterEqual(len(unified_payload["calls"]), 3)
        self.assertEqual(len(unified_payload["live"]), 1)

        live = self.client.get("/call-center/live/api")
        self.assertEqual(live.status_code, 200)
        live_payload = live.get_json()
        self.assertIn("6500", live_payload["queues"])
        self.assertEqual(live_payload["active_calls"][0]["caller"], "2015550199")

        details = self.client.get("/call-center/queues/6500/api")
        self.assertEqual(details.status_code, 200)
        details_payload = details.get_json()
        self.assertEqual(details_payload["kpis"]["total_calls"], 3)
        self.assertTrue(details_payload["live_calls"])
        self.assertTrue(details_payload["agent_performance"])

        timeline = self.client.get("/call-center/call-details/uid-api-1")
        self.assertEqual(timeline.status_code, 200)
        timeline_payload = timeline.get_json()
        self.assertTrue(timeline_payload["success"])
        events = [item["event"] for item in timeline_payload["call"]["timeline"]]
        self.assertIn("Entered Queue", events)
        self.assertIn("Agent Ringing", events)
        self.assertIn("Answered", events)
        self.assertIn("Hangup", events)

        detailed_log = self.client.get("/api/calls/uid-api-1/events")
        self.assertEqual(detailed_log.status_code, 200)
        detailed_payload = detailed_log.get_json()
        self.assertIn("events", detailed_payload)
        self.assertIn("agent_attempts", detailed_payload)
        self.assertIsInstance(detailed_payload["events"], list)
        self.assertEqual(
            [(item["extension"], item["status"]) for item in detailed_payload["agent_attempts"]],
            [("5001", "Answered")],
        )

    def test_cdr_page_reads_asterisk_master_csv(self):
        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        row = [
            "",
            "5001",
            "6500",
            "from-internal",
            '"Alice" <5001>',
            "PJSIP/5001-00000001",
            "Local/6500@from-queue",
            "Queue",
            "6500",
            now_utc,
            now_utc,
            now_utc,
            "70",
            "60",
            "ANSWERED",
            "",
            "uid-cdr-1",
        ]
        cdr_buffer = io.StringIO()
        csv.writer(cdr_buffer).writerow(row)
        cdr_text = cdr_buffer.getvalue()

        def fake_exists(path):
            return path == "/var/log/asterisk/cdr-csv/Master.csv"

        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            if path == "/var/log/asterisk/cdr-csv/Master.csv":
                return io.StringIO(cdr_text)
            return real_open(path, mode, *args, **kwargs)

        with mock.patch.object(self.app_module.os.path, "exists", side_effect=fake_exists):
            with mock.patch("builtins.open", side_effect=fake_open):
                # 1. Test GUI page loads
                response_gui = self.client.get("/cdr")
                self.assertEqual(response_gui.status_code, 200)
                self.assertIn(b"Call Detail Records", response_gui.data)

                # 2. Test api endpoint returns the parsed record
                response_api = self.client.get("/api/cdr-list")
                self.assertEqual(response_api.status_code, 200)
                self.assertIn(b"uid-cdr-1", response_api.data)
                self.assertIn(b"ANSWERED", response_api.data)

    def test_cdr_sync_normalizes_all_lifecycle_timestamps_and_refreshes_existing_rows(self):
        raw_start = "2026-07-27 14:30:16"
        raw_answer = "2026-07-27 14:30:20"
        raw_end = "2026-07-27 14:30:51"
        expected = [
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            for value in (raw_start, raw_answer, raw_end)
        ]
        seed_conn = db.get_db()
        try:
            conn = seed_conn
            conn.execute(
                "INSERT INTO cdr_records (uniqueid, start_time, answer_time, end_time, status) VALUES (?, ?, ?, ?, ?)",
                ("uid-cdr-time", "old-start", "old-answer", "old-end", "NO ANSWER"),
            )
            conn.commit()
        finally:
            seed_conn.close()

        row = [
            "", "5001", "6500", "queue-6500", '"Alice" <5001>',
            "PJSIP/5001-00000001", "Local/6500@from-queue", "Queue", "6500",
            raw_start, raw_answer, raw_end, "35", "31", "ANSWERED", "",
            "uid-cdr-time", "~DEST:queue:6500",
        ]
        cdr_buffer = io.StringIO()
        csv.writer(cdr_buffer).writerow(row)
        cdr_text = cdr_buffer.getvalue()

        def fake_exists(path):
            return path == "/var/log/asterisk/cdr-csv/Master.csv"

        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            if path == "/var/log/asterisk/cdr-csv/Master.csv":
                return io.StringIO(cdr_text)
            return real_open(path, mode, *args, **kwargs)

        with mock.patch.object(self.app_module.os.path, "exists", side_effect=fake_exists):
            with mock.patch("builtins.open", side_effect=fake_open):
                db.sync_cdr_records()

        result_conn = db.get_db()
        try:
            conn = result_conn
            stored = conn.execute(
                "SELECT start_time, answer_time, end_time, status, userfield FROM cdr_records WHERE uniqueid = ?",
                ("uid-cdr-time",),
            ).fetchone()
        finally:
            result_conn.close()
        self.assertEqual([stored["start_time"], stored["answer_time"], stored["end_time"]], expected)
        self.assertEqual(stored["status"], "ANSWERED")
        self.assertEqual(stored["userfield"], "~DEST:queue:6500")

    def test_cdr_sync_keeps_all_same_uniqueid_channel_legs_in_one_linked_group(self):
        rows = [
            ["", "5001", "5002", "from-internal", '"Alice" <5001>',
             "PJSIP/5001-1", "PJSIP/5002-1", "Dial", "PJSIP/5002", "2026-07-28 10:00:00",
             "2026-07-28 10:00:02", "2026-07-28 10:00:10", "10", "8", "ANSWERED", "DOCUMENTATION",
             "1800000000.1", ""],
            ["", "5001", "5002", "from-internal", '"Alice" <5001>',
             "PJSIP/5001-1", "", "Hangup", "", "2026-07-28 10:00:10",
             "2026-07-28 10:00:10", "2026-07-28 10:00:10", "0", "0", "ANSWERED", "DOCUMENTATION",
             "1800000000.1", ""],
        ]
        cdr_text = io.StringIO()
        writer = csv.writer(cdr_text)
        writer.writerows(rows)

        def fake_exists(path):
            return path == "/var/log/asterisk/cdr-csv/Master.csv"

        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            if path == "/var/log/asterisk/cdr-csv/Master.csv":
                return io.StringIO(cdr_text.getvalue())
            return real_open(path, mode, *args, **kwargs)

        with mock.patch.object(self.app_module.os.path, "exists", side_effect=fake_exists):
            with mock.patch("builtins.open", side_effect=fake_open):
                db.sync_cdr_records()

        conn = db.get_db()
        try:
            stored = conn.execute(
                "SELECT uniqueid, linkedid, lastapp FROM cdr_records WHERE linkedid = ? ORDER BY uniqueid",
                ("1800000000.1",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["linkedid"], "1800000000.1")
        self.assertEqual({row["lastapp"] for row in stored}, {"Dial", "Hangup"})

    def test_call_details_endpoint_reconstructs_all_linked_cdr_legs(self):
        conn = db.get_db()
        try:
            conn.executemany(
                """
                INSERT INTO cdr_records
                (uniqueid, linkedid, src, dst, channel, dstchannel, dcontext, lastapp,
                 start_time, answer_time, end_time, duration, billsec, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("journey-leg-1", "journey-linked", "5001", "5002", "PJSIP/5001-a", "PJSIP/5002-b", "from-internal", "Dial", "2026-07-28 10:00:00", "2026-07-28 10:00:02", "2026-07-28 10:00:10", 10, 8, "ANSWERED"),
                    ("journey-leg-2", "journey-linked", "5001", "5002", "PJSIP/5001-a", "", "from-internal", "Hangup", "2026-07-28 10:00:10", "2026-07-28 10:00:10", "2026-07-28 10:00:10", 0, 0, "ANSWERED"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        with mock.patch.object(self.app_module.db, "sync_cdr_records", return_value=None):
            response = self.client.get("/call-center/call-details/journey-leg-1")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        call = payload["call"]
        self.assertEqual(call["linkedid"], "journey-linked")
        self.assertEqual(call["call_type_label"], "Internal Call")
        self.assertEqual([card["kind"] for card in call["journey"]], ["start", "answered", "end"])

    def test_queue_status_is_used_for_cdr_filter_and_statistics(self):
        main_conn = db.get_db()
        try:
            conn = main_conn
            conn.execute(
                "INSERT INTO cdr_records (uniqueid, src, dst, start_time, end_time, duration, billsec, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("uid-queue-effective-status", "5001", "6500", "2030-01-01 17:30:00", "2030-01-01 17:30:20", 20, 10, "NO ANSWER"),
            )
            conn.commit()
        finally:
            main_conn.close()

        queue_conn = rcm_queue_db.get_db_connection()
        try:
            conn = queue_conn
            conn.execute(
                "INSERT INTO queue_calls (uniqueid, linkedid, caller_number, queue_id, queue_name, status, talk_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("uid-queue-effective-status", "uid-queue-effective-status", "5001", "6500", "Support", "ANSWERED", 10),
            )
            conn.commit()
        finally:
            queue_conn.close()

        with mock.patch.object(self.app_module.db, "sync_cdr_records", return_value=None):
            answered = self.client.get("/api/cdr-list?status=ANSWERED&date_from=2030-01-01&date_to=2030-01-01")
            self.assertEqual(answered.status_code, 200)
            payload = answered.get_json()
            self.assertEqual(payload["stats"]["answered_ratio"], 100)
            self.assertEqual(payload["data"][0]["status"], "ANSWERED")
            self.assertEqual(payload["data"][0]["uniqueid"], "uid-queue-effective-status")

            missed = self.client.get("/api/cdr-list?status=NO%20ANSWER&date_from=2030-01-01&date_to=2030-01-01")
            self.assertEqual(missed.status_code, 200)
            self.assertEqual(missed.get_json()["total_rows"], 0)

    def test_agent_queue_membership_validation(self):
        # Clear command log
        self.ami_commands.clear()

        # 1. Non-member Logout/Leave
        response = self.client.post("/queues/6500/agents/leave", data={"agent": "5009"})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Agent is not a member of this queue", data["message"])
        self.assertEqual(len(self.ami_commands), 0)

        # 2. Non-member Pause/Disable
        response = self.client.post("/queues/6500/agents/disable", data={"agent": "5009"})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Agent is not a member of this queue", data["message"])
        self.assertEqual(len(self.ami_commands), 0)

        # 3. Non-member Unpause/Enable
        response = self.client.post("/queues/6500/agents/enable", data={"agent": "5009"})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Agent is not a member of this queue", data["message"])
        self.assertEqual(len(self.ami_commands), 0)

        # 4. Supervisor Control - Non-member Pause
        response = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "pause", "agent": "5009", "queue": "6500", "reason": "Break"}
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Agent is not a member of this queue", data["error"])
        self.assertEqual(len(self.ami_commands), 0)

        # 5. Supervisor Control - Non-member Unpause
        response = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "unpause", "agent": "5009", "queue": "6500"}
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Agent is not a member of this queue", data["error"])
        self.assertEqual(len(self.ami_commands), 0)

        # 6. Valid Member Pause/Disable (Static Agent 5001)
        rcm_queue_db.db_agent_login("5001", "6500", "Alice", "STATIC")
        rcm_queue_db.db_agent_pause("5001", "6500", False)
        
        response = self.client.post("/queues/6500/agents/disable", data={"agent": "5001"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ami_commands[-1][0], "QueuePause")
        self.assertEqual(self.ami_commands[-1][1]["Paused"], "true")

        # 7. Valid Member Unpause/Enable (Static Agent 5001)
        rcm_queue_db.db_agent_pause("5001", "6500", True)
        response = self.client.post("/queues/6500/agents/enable", data={"agent": "5001"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ami_commands[-1][0], "QueuePause")
        self.assertEqual(self.ami_commands[-1][1]["Paused"], "false")

    def test_queue_add_validation_max_wait_time(self):
        response = self.client.post("/queues/add", data={
            "queue_number": "6510",
            "name": "Test Queue Invalid Wait",
            "ring_time": "30",
            "max_wait_time": "10",
            "strategy": "rrmemory"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Queue Max Wait Time must be greater than or equal to Agent Ring Time", response.data)


if __name__ == "__main__":
    unittest.main()
