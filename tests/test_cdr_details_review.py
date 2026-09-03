import unittest
from unittest import mock

import db
import rcm_queue_db


class CdrDetailsReviewTestCase(unittest.TestCase):
    def setUp(self):
        self.queues = [{"queue_number": "6500", "name": "Support"}]
        self.extensions = [
            {"ext": "5001", "name": "Alice"},
            {"ext": "5002", "name": "Bob"},
            {"ext": "5003", "name": "Carol"},
        ]
        self.patches = [
            mock.patch.object(db, "get_queues", return_value=self.queues),
            mock.patch.object(db, "get_all_extensions", return_value=self.extensions),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    def cdr(self, **overrides):
        record = {
            "src": "5001",
            "dst": "5002",
            "start_time": "2026-01-01 10:00:00",
            "end_time": "2026-01-01 10:00:15",
            "duration": 15,
            "userfield": "",
            "dcontext": "from-internal",
            "lastapp": "Dial",
        }
        record.update(overrides)
        return record

    def call(self, **overrides):
        info = {
            "caller": "5001",
            "caller_number": "5001",
            "agent": "5002",
            "status": "ANSWERED",
            "wait_time": 3,
            "talk_time": 12,
            "answer_time": "2026-01-01 10:00:03",
            "hangup_time": "2026-01-01 10:00:15",
            "ended_by": "CALLER",
            "timeline": [],
        }
        info.update(overrides)
        return info

    def journey(self, call, cdr):
        return rcm_queue_db.build_friendly_call_journey(call, cdr)

    def test_direct_answered_has_no_agent_or_queue_card(self):
        result = self.journey(self.call(), self.cdr())
        kinds = [step["kind"] for step in result["journey"]]
        direct = next(step for step in result["journey"] if step["kind"] == "direct")

        self.assertEqual(result["call_type"], "direct")
        self.assertNotIn("queue", kinds)
        self.assertNotIn("agent_attempts", direct)

    def test_direct_terminal_statuses_are_preserved(self):
        for status in ("NO ANSWER", "BUSY", "FAILED"):
            with self.subTest(status=status):
                result = self.journey(
                    self.call(status=status, talk_time=0, answer_time=""),
                    self.cdr(status=status),
                )
                direct = next(step for step in result["journey"] if step["kind"] == "direct")
                self.assertEqual(result["call_type"], "direct")
                self.assertNotIn("agent_attempts", direct)

    def test_queue_answered_shows_ivr_queue_and_attempts(self):
        result = self.journey(
            self.call(
                agent="5002",
                queue_id="6500",
                queue_name="Support",
                agent_attempts=[
                    {"extension": "5001", "agent_name": "Alice", "status": "No Answer", "status_key": "no_answer"},
                    {"extension": "5002", "agent_name": "Bob", "status": "Answered", "status_key": "answered"},
                ],
            ),
            self.cdr(
                dst="6500",
                dcontext="queue-6500",
                lastapp="Queue",
                userfield="~IVR:7001:Main menu~DIGIT:2~DEST:queue:6500",
            ),
        )
        kinds = [step["kind"] for step in result["journey"]]
        queue = next(step for step in result["journey"] if step["kind"] == "queue")

        self.assertEqual(result["call_type"], "queue")
        self.assertIn("ivr", kinds)
        self.assertNotIn("direct", kinds)
        self.assertNotIn("selection", kinds)
        self.assertEqual(queue["agent_attempts"][1]["talk_time_display"], "00:12")

    def test_queue_no_answer_has_no_fake_talk_time(self):
        result = self.journey(
            self.call(
                agent="",
                queue_id="6500",
                queue_name="Support",
                status="NO ANSWER",
                wait_time=20,
                talk_time=0,
                answer_time="",
                ended_by="CALLER",
            ),
            self.cdr(
                dst="6500",
                duration=20,
                end_time="2026-01-01 10:00:20",
                dcontext="queue-6500",
                lastapp="Queue",
            ),
        )
        self.assertEqual(result["call_type"], "queue")
        self.assertFalse(any(step.get("agent_attempts") for step in result["journey"]))
        self.assertEqual(result["journey"][-1]["subtitle"], "NO ANSWER")

    def test_agent_no_answer_and_cancelled_use_queue_event_type(self):
        events = [
            {"agent": "5001", "event_type": "RING", "timestamp": "2026-01-01 10:00:00"},
            {"agent": "5001", "event_type": "RINGNOANSWER", "timestamp": "2026-01-01 10:00:02"},
            {"agent": "5002", "event_type": "RING", "timestamp": "2026-01-01 10:00:02"},
            {"agent": "5002", "event_type": "RINGCANCELED", "timestamp": "2026-01-01 10:00:03"},
        ]
        attempts = rcm_queue_db._build_agent_attempts(
            events,
            {"status": "NO ANSWER", "agent": "", "answer_time": ""},
            {"5001": "Alice", "5002": "Bob"},
            10,
        )
        self.assertEqual([attempt["status"] for attempt in attempts], ["No Answer", "Cancelled"])

    def test_forwarded_call_describes_source_and_target(self):
        result = self.journey(
            self.call(agent="5002"),
            self.cdr(userfield="~FORWARD:5001:busy:5002"),
        )
        forward = next(step for step in result["journey"] if step["kind"] == "forward")
        self.assertEqual(result["call_type"], "forwarded")
        self.assertIn("Alice (5001) forwarded the call to Bob (5002)", forward["subtitle"])
        self.assertNotIn("agent_attempts", next(step for step in result["journey"] if step["kind"] == "direct"))

    def test_transfer_hold_and_unhold_are_visible(self):
        result = self.journey(
            self.call(
                timeline=[
                    {"event": "TRANSFER", "time": "2026-01-01 10:00:08", "details": "5002 transferred the call to 5003."},
                    {"event": "HOLD", "time": "2026-01-01 10:00:09", "details": "Call placed on hold."},
                    {"event": "UNHOLD", "time": "2026-01-01 10:00:11", "details": "Call resumed."},
                ]
            ),
            self.cdr(),
        )
        event_steps = [step for step in result["journey"] if step["kind"] in ("transfer", "hold")]
        self.assertEqual(result["call_type"], "direct")
        self.assertTrue(result["has_transfer"])
        self.assertEqual([step["kind"] for step in event_steps], ["transfer", "hold", "hold"])
        self.assertIn("5002 transferred the call to 5003", event_steps[0]["subtitle"])
        self.assertNotIn("agent_attempts", next(step for step in result["journey"] if step["kind"] == "direct"))


if __name__ == "__main__":
    unittest.main()
