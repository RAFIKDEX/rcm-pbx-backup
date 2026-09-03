import unittest

import cdr_journey


class CallJourneyTestCase(unittest.TestCase):
    def setUp(self):
        self.meta = {
            "extensions": {
                "5001": "Ahmed",
                "5002": "Mohamed",
                "5003": "Sara",
                "5004": "Ali",
                "555": "Dexter",
            },
            "queues": {"6501": {"name": "Sales", "timeout": 15, "max_wait_time": 60},
                       "6502": {"name": "Escalation", "timeout": 10, "max_wait_time": 30}},
            "ring_groups": {"6200": {"name": "Sales Team"}},
            "paging": {"6300": {"name": "Warehouse", "duplex": 0}},
            "speed_dials": {"22": {"destination_num": "01012345678"}},
            "announcements": {"6400": {"name": "Working Hours"}},
            "trunks": {"Vodafone", "GSM"},
        }

    def row(self, **values):
        defaults = {
            "uniqueid": "u1",
            "linkedid": "l1",
            "src": "5001",
            "dst": "5002",
            "clid": "5001",
            "channel": "PJSIP/5001-abc",
            "dstchannel": "PJSIP/5002-def",
            "dcontext": "from-internal",
            "lastapp": "Dial",
            "lastdata": "PJSIP/5002",
            "start_time": "2026-07-28 10:00:00",
            "answer_time": "2026-07-28 10:00:02",
            "end_time": "2026-07-28 10:00:10",
            "duration": 10,
            "billsec": 8,
            "status": "ANSWERED",
            "userfield": "",
        }
        defaults.update(values)
        return defaults

    def card_kinds(self, result):
        return [card["kind"] for card in result["journey"]]

    def test_internal_call_contains_only_meaningful_cards(self):
        result = cdr_journey.build_call_journey(
            [self.row()],
            metadata=self.meta,
        )

        self.assertEqual(result["call_type_label"], "Internal Call")
        self.assertEqual(self.card_kinds(result), ["start", "answered", "end"])
        self.assertEqual(result["final_callee"], "5002")
        self.assertEqual(result["ended_by"], "Callee")
        self.assertNotIn("hold", self.card_kinds(result))
        self.assertNotIn("bridge", self.card_kinds(result))

    def test_inbound_linked_legs_build_ivr_queue_and_agent_journey(self):
        rows = [
            self.row(
                uniqueid="u1",
                linkedid="l1",
                src="01012345678",
                dst="0221234567",
                channel="PJSIP/Vodafone-abc",
                dstchannel="",
                dcontext="from-trunk",
                lastapp="Goto",
                answer_time="0000-00-00 00:00:00",
                status="NO ANSWER",
                userfield="~INBOUND:Vodafone:0221234567~IVR:7001:Main Menu~DIGIT:1~DEST:queue:6501",
            ),
            self.row(
                uniqueid="u2",
                linkedid="l1",
                src="01012345678",
                dst="6501",
                channel="Local/6501@queue-1",
                dstchannel="PJSIP/5001-xyz",
                dcontext="queue-6501",
                lastapp="Queue",
                lastdata="6501",
                start_time="2026-07-28 10:00:20",
                answer_time="2026-07-28 10:00:35",
                end_time="2026-07-28 10:01:00",
                status="ANSWERED",
                userfield="~INBOUND:Vodafone:0221234567~IVR:7001:Main Menu~DIGIT:1~DEST:queue:6501",
            ),
        ]
        queue_call = {
            "uniqueid": "l1",
            "linkedid": "l1",
            "caller_number": "01012345678",
            "queue_id": "6501",
            "queue_name": "Sales",
            "entry_time": "2026-07-28 10:00:20",
            "answer_time": "2026-07-28 10:00:35",
            "hangup_time": "2026-07-28 10:01:00",
            "status": "ANSWERED",
            "agent": "5001",
        }
        queue_events = [
            {"agent": "5002", "event_type": "RING", "timestamp": "2026-07-28 10:00:21"},
            {"agent": "5002", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:31"},
            {"agent": "5001", "event_type": "RING", "timestamp": "2026-07-28 10:00:32"},
            {"agent": "5001", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:35"},
            {"agent": "5001", "event_type": "HOLD", "timestamp": "2026-07-28 10:00:40"},
            {"agent": "5001", "event_type": "BRIDGE", "timestamp": "2026-07-28 10:00:41"},
        ]

        result = cdr_journey.build_call_journey(rows, queue_call, queue_events, self.meta)

        self.assertEqual(result["call_type"], "inbound")
        self.assertEqual(self.card_kinds(result), ["start", "ivr", "digit", "queue", "answered", "end"])
        self.assertEqual(result["journey"][0]["details"][1]["value"], "Vodafone")
        self.assertEqual(result["journey"][1]["details"][0]["value"], "7001")
        self.assertEqual(result["journey"][2]["details"][0]["value"], "1")
        attempts = result["journey"][3]["agent_attempts"]
        self.assertEqual([(a["extension"], a["agent_name"], a["status"]) for a in attempts], [
            ("5002", "Mohamed", "Cancelled"),
            ("5001", "Ahmed", "Answered"),
        ])
        self.assertEqual(result["final_callee_display"], "5001 (Ahmed)")

    def test_outbound_call_identifies_trunk_and_destination(self):
        result = cdr_journey.build_call_journey([
            self.row(
                src="5001",
                dst="01012345678",
                channel="PJSIP/5001-abc",
                dstchannel="PJSIP/GSM-xyz",
                lastdata="PJSIP/01012345678@GSM",
            )
        ], metadata=self.meta)

        self.assertEqual(result["call_type_label"], "Outbound Call")
        self.assertEqual(result["trunk"], "GSM")
        start = result["journey"][0]
        self.assertEqual(start["details"][1], {"label": "Destination", "value": "01012345678"})
        self.assertEqual(start["details"][2], {"label": "Trunk", "value": "GSM"})

    def test_forward_is_business_event_and_final_destination_is_callee(self):
        rows = [
            self.row(dst="5002", answer_time="0000-00-00 00:00:00", end_time="2026-07-28 10:00:03", status="BUSY",
                     userfield="~FORWARD:5002:busy:555"),
            self.row(uniqueid="u2", src="5001", dst="555", channel="PJSIP/5001-a", dstchannel="PJSIP/555-b",
                     start_time="2026-07-28 10:00:03", answer_time="2026-07-28 10:00:04", status="ANSWERED",
                     userfield="~FORWARD:5002:busy:555"),
        ]
        result = cdr_journey.build_call_journey(rows, metadata=self.meta)

        self.assertIn("forward", self.card_kinds(result))
        self.assertIn("answered", self.card_kinds(result))
        self.assertEqual(result["final_callee"], "555")
        self.assertEqual(result["final_result"], "Answered")

    def test_transfer_card_uses_type_and_does_not_expose_hold(self):
        events = [{
            "event_type": "TRANSFER", "source": "5004", "agent": "555",
            "timestamp": "2026-07-28 10:00:05", "transfer_type": "Attended Transfer",
        }, {"event_type": "HOLD", "agent": "5004", "timestamp": "2026-07-28 10:00:04"}]
        result = cdr_journey.build_call_journey([
            self.row(src="5001", dst="5004", answer_time="2026-07-28 10:00:02")
        ], queue_events=events, metadata=self.meta)

        transfer = next(card for card in result["journey"] if card["kind"] == "transfer")
        self.assertEqual(transfer["details"][0], {"label": "Transfer Type", "value": "Attended Transfer"})
        self.assertNotIn("hold", self.card_kinds(result))
        self.assertIn("5004 (Ali)", transfer["subtitle"])
        self.assertIn("555 (Dexter)", transfer["subtitle"])

    def test_direct_transfer_legs_set_final_callee_and_failed_return(self):
        answered = self.row(
            src="5001", dst="5004", uniqueid="u1", end_time="2026-07-28 10:00:05"
        )
        transferred = self.row(
            src="5001", dst="555", uniqueid="u2", dcontext="from-internal-5004",
            start_time="2026-07-28 10:00:05", answer_time="2026-07-28 10:00:06",
        )
        result = cdr_journey.build_call_journey([answered, transferred], metadata=self.meta)
        transfer = next(card for card in result["journey"] if card["kind"] == "transfer")
        self.assertEqual(result["final_callee"], "555")
        self.assertIn("transferred the call", transfer["subtitle"])

        failed_target = dict(transferred, answer_time="0000-00-00 00:00:00", status="BUSY")
        failed = cdr_journey.build_call_journey([answered, failed_target], metadata=self.meta)
        failed_card = next(card for card in failed["journey"] if card["kind"] == "transfer")
        self.assertEqual(failed["final_callee"], "5004")
        self.assertEqual(failed_card["details"][1]["value"], "Transfer Failed")

    def test_queue_transfer_is_after_agent_answer_and_ignores_recording_leg(self):
        rows = [
            self.row(uniqueid="queue", src="2121", dst="6501", dcontext="queue-6501",
                     lastapp="Queue", status="NO ANSWER", answer_time="2026-07-28 10:00:00",
                     end_time="2026-07-28 10:00:05"),
            self.row(uniqueid="agent-leg", src="2121", dst="555", dcontext="from-internal-5002",
                     lastapp="Queue", start_time="2026-07-28 10:00:05", answer_time="2026-07-28 10:00:05",
                     end_time="2026-07-28 10:00:15", status="ANSWERED"),
            self.row(uniqueid="recording-leg", src="2121", dst="555", dcontext="recording",
                     lastapp="Dial", start_time="2026-07-28 10:00:05", answer_time="2026-07-28 10:00:05",
                     end_time="2026-07-28 10:00:15", status="ANSWERED"),
        ]
        queue_call = {
            "queue_id": "6501", "queue_name": "Sales", "agent": "5002",
            "answer_time": "2026-07-28 10:00:05", "status": "ANSWERED",
            "hangup_time": "2026-07-28 10:00:20",
        }
        events = [
            {"agent": "5001", "event_type": "RING", "timestamp": "2026-07-28 10:00:01"},
            {"agent": "5001", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:04"},
            {"agent": "5002", "event_type": "RING", "timestamp": "2026-07-28 10:00:04"},
            {"agent": "5002", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:05"},
            {"agent": "555", "event_type": "TRANSFER", "source": "5002",
             "transfer_type": "Blind Transfer", "timestamp": "2026-07-28 10:00:15"},
        ]
        result = cdr_journey.build_call_journey(rows, queue_call, events, self.meta)
        meaningful = [(card["kind"], card.get("subtitle")) for card in result["journey"]]
        self.assertEqual([kind for kind, _ in meaningful], ["start", "queue", "answered", "transfer", "answered", "end"])
        self.assertEqual(meaningful[2][1], "5002 (Mohamed)")
        self.assertEqual(meaningful[4][1], "555 (Dexter)")
        attempts = next(card["agent_attempts"] for card in result["journey"] if card["kind"] == "queue")
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [("5001", "Cancelled"), ("5002", "Answered")])

    def test_transfer_to_another_queue_separates_attempts_and_marks_source_transferred(self):
        rows = [
            self.row(uniqueid="q1", src="2121", dst="6501", dcontext="queue-6501",
                     start_time="2026-07-28 10:00:00", answer_time="2026-07-28 10:00:02",
                     end_time="2026-07-28 10:00:10", status="ANSWERED"),
            self.row(uniqueid="q2", src="2121", dst="6502", dcontext="queue-6502",
                     start_time="2026-07-28 10:00:10", answer_time="2026-07-28 10:00:13",
                     end_time="2026-07-28 10:00:20", status="ANSWERED"),
        ]
        events = [
            {"queue": "6501", "agent": "", "event_type": "ENTERQUEUE", "timestamp": "2026-07-28 10:00:00"},
            {"queue": "6501", "agent": "5001", "event_type": "RING", "timestamp": "2026-07-28 10:00:01"},
            {"queue": "6501", "agent": "5001", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
            {"queue": "6501", "agent": "6502", "event_type": "TRANSFER", "source": "5001", "timestamp": "2026-07-28 10:00:10", "transfer_type": "Blind Transfer"},
            {"queue": "6502", "agent": "", "event_type": "ENTERQUEUE", "timestamp": "2026-07-28 10:00:10"},
            {"queue": "6502", "agent": "5003", "event_type": "RING", "timestamp": "2026-07-28 10:00:11"},
            {"queue": "6502", "agent": "5003", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:13"},
        ]
        result = cdr_journey.build_call_journey(
            rows,
            self.queue_call(queue_id="6501", queue_name="Sales", status="ANSWERED", agent="5001"),
            events,
            self.meta,
        )
        queues = [card for card in result["journey"] if card["kind"] == "queue"]
        self.assertEqual([card["details"][0]["value"] for card in queues], ["6501", "6502"])
        transfer_index = next(index for index, card in enumerate(result["journey"]) if card["kind"] == "transfer")
        target_queue_index = next(
            index for index, card in enumerate(result["journey"])
            if card["kind"] == "queue" and card.get("queue_number") == "6502"
        )
        self.assertLess(transfer_index, target_queue_index)
        self.assertEqual([(a["extension"], a["status"], a.get("termination_reason")) for a in queues[0]["agent_attempts"]], [("5001", "Answered", "Transferred")])
        self.assertEqual([(a["extension"], a["status"]) for a in queues[1]["agent_attempts"]], [("5003", "Answered")])
        transfer = next(card for card in result["journey"] if card["kind"] == "transfer")
        self.assertEqual(transfer["title"], "TRANSFERRED")
        self.assertIn("Queue: Escalation", transfer["subtitle"])

    def test_repeated_queue_visits_have_independent_metrics_cards(self):
        rows = [
            self.row(uniqueid="q1", src="2121", dst="6501", dcontext="queue-6501",
                     start_time="2026-07-28 10:00:00", answer_time="2026-07-28 10:00:07",
                     end_time="2026-07-28 10:00:12", status="ANSWERED"),
            self.row(uniqueid="q2", src="2121", dst="6501", dcontext="queue-6501",
                     start_time="2026-07-28 10:00:20", answer_time="2026-07-28 10:00:28",
                     end_time="2026-07-28 10:00:40", status="ANSWERED"),
        ]
        primary = self.queue_call(
            uniqueid="q1", entry_time="2026-07-28 10:00:00", answer_time="2026-07-28 10:00:07",
            hangup_time="2026-07-28 10:00:12", status="ANSWERED", agent="5001",
            _related_queue_calls=[
                self.queue_call(uniqueid="q1", entry_time="2026-07-28 10:00:00",
                                answer_time="2026-07-28 10:00:07", hangup_time="2026-07-28 10:00:12",
                                status="ANSWERED", agent="5001"),
                self.queue_call(uniqueid="q2", entry_time="2026-07-28 10:00:20",
                                answer_time="2026-07-28 10:00:28", hangup_time="2026-07-28 10:00:40",
                                status="ANSWERED", agent="5002"),
            ],
        )
        events = [
            {"queue": "6501", "event_type": "ENTERQUEUE", "timestamp": "2026-07-28 10:00:00"},
            {"queue": "6501", "agent": "5001", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:07"},
            {"queue": "6501", "event_type": "CONNECT", "timestamp": "2026-07-28 10:00:07"},
            {"queue": "6501", "event_type": "HOLD", "timestamp": "2026-07-28 10:00:08"},
            {"queue": "6501", "event_type": "UNHOLD", "timestamp": "2026-07-28 10:00:10"},
            {"queue": "6501", "event_type": "COMPLETE", "timestamp": "2026-07-28 10:00:12"},
            {"queue": "6501", "event_type": "ENTERQUEUE", "timestamp": "2026-07-28 10:00:20"},
            {"queue": "6501", "agent": "5002", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:28"},
            {"queue": "6501", "event_type": "CONNECT", "timestamp": "2026-07-28 10:00:28"},
            {"queue": "6501", "event_type": "COMPLETE", "timestamp": "2026-07-28 10:00:40"},
        ]
        result = cdr_journey.build_call_journey(rows, primary, events, self.meta)
        queues = [card for card in result["journey"] if card["kind"] == "queue"]
        self.assertEqual(len(queues), 2)
        self.assertEqual([card["queue_leg_index"] for card in queues], [0, 1])
        self.assertEqual(queues[0]["queue_metrics"]["wait_time"], 7)
        self.assertEqual(queues[0]["queue_metrics"]["talk_time"], 3)
        self.assertEqual(queues[0]["queue_metrics"]["hold_time"], 2)
        self.assertEqual(queues[1]["queue_metrics"]["wait_time"], 8)
        self.assertEqual(result["wait_time"], 7)

    def test_target_queue_is_after_transfer_even_when_enterqueue_timestamp_is_early(self):
        events = [
            {"queue": "6501", "event_type": "ENTERQUEUE", "timestamp": "2026-07-28 10:00:00"},
            {"queue": "6501", "agent": "5001", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
            # Some queue-log/CEL combinations persist the target ENTERQUEUE
            # with the same second, or just before the transfer event.
            {"queue": "6502", "event_type": "ENTERQUEUE", "timestamp": "2026-07-28 10:00:09"},
            {"queue": "6501", "agent": "6502", "event_type": "TRANSFER", "source": "5001", "timestamp": "2026-07-28 10:00:10"},
        ]
        result = cdr_journey.build_call_journey(
            [self.row(dst="6501", dcontext="queue-6501", status="ANSWERED")],
            self.queue_call(queue_id="6501", queue_name="Sales", status="ANSWERED", agent="5001"),
            events,
            self.meta,
        )
        transfer_index = next(index for index, card in enumerate(result["journey"]) if card["kind"] == "transfer")
        target_queue_index = next(
            index for index, card in enumerate(result["journey"])
            if card["kind"] == "queue" and card.get("queue_number") == "6502"
        )
        self.assertLess(transfer_index, target_queue_index)

    def test_transfer_to_another_agent_in_same_queue_keeps_both_agent_attempts(self):
        events = [
            {"queue": "6501", "agent": "5001", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"queue": "6501", "agent": "5001", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
            {"queue": "6501", "agent": "5002", "event_type": "TRANSFER", "source": "5001", "timestamp": "2026-07-28 10:00:05", "transfer_type": "Attended Transfer"},
            {"queue": "6501", "agent": "5002", "event_type": "RING", "timestamp": "2026-07-28 10:00:06"},
            {"queue": "6501", "agent": "5002", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:08"},
        ]
        result = cdr_journey.build_call_journey(
            [self.row(src="2121", dst="6501", dcontext="queue-6501", status="ANSWERED")],
            self.queue_call(queue_id="6501", queue_name="Sales", status="ANSWERED", agent="5002"),
            events,
            self.meta,
        )
        queue = next(card for card in result["journey"] if card["kind"] == "queue")
        self.assertEqual([(a["extension"], a["agent_name"], a["status"], a.get("termination_reason")) for a in queue["agent_attempts"]], [
            ("5001", "Ahmed", "Answered", "Transferred"),
            ("5002", "Mohamed", "Answered", None),
        ])
        transfer = next(card for card in result["journey"] if card["kind"] == "transfer")
        self.assertIn("5002 (Mohamed)", transfer["subtitle"])
        self.assertIn("Attended Transfer", [detail["value"] for detail in transfer["details"]])

    def test_transfer_to_agent_in_another_queue_attaches_target_agent_to_target_queue(self):
        rows = [
            self.row(uniqueid="q1", src="2121", dst="6501", dcontext="queue-6501", status="ANSWERED"),
            self.row(uniqueid="q2", src="2121", dst="6502", dcontext="queue-6502", start_time="2026-07-28 10:00:05", answer_time="2026-07-28 10:00:08", status="ANSWERED"),
        ]
        events = [
            {"queue": "6501", "agent": "5001", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"queue": "6501", "agent": "5001", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
            {"queue": "6501", "agent": "5003", "event_type": "TRANSFER", "source": "5001", "timestamp": "2026-07-28 10:00:05"},
            {"queue": "6502", "agent": "5003", "event_type": "RING", "timestamp": "2026-07-28 10:00:06"},
            {"queue": "6502", "agent": "5003", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:08"},
        ]
        result = cdr_journey.build_call_journey(
            rows,
            self.queue_call(queue_id="6501", queue_name="Sales", status="ANSWERED", agent="5001"),
            events,
            self.meta,
        )
        queues = [card for card in result["journey"] if card["kind"] == "queue"]
        target_queue = next(card for card in queues if card["details"][0]["value"] == "6502")
        self.assertEqual([(a["extension"], a["queue_number"], a["status"]) for a in target_queue["agent_attempts"]], [("5003", "6502", "Answered")])
        transfer = next(card for card in result["journey"] if card["kind"] == "transfer")
        self.assertIn("5003 (Sara)", transfer["subtitle"])
        self.assertIn("Queue: Escalation", transfer["subtitle"])

    def test_destination_cards_are_inferred_without_raw_asterisk_events(self):
        cases = [
            ("rcm-ring-groups", "6200", "ring_group"),
            ("rcm-paging-intercom", "6300", "paging"),
            ("ann-6400", "6400", "announcement"),
            ("speed-dials", "22", "speed_dial"),
        ]
        for context, destination, expected_kind in cases:
            with self.subTest(expected_kind=expected_kind):
                result = cdr_journey.build_call_journey([
                    self.row(dst=destination, dcontext=context, lastapp="Dial", status="NO ANSWER",
                             answer_time="0000-00-00 00:00:00")
                ], metadata=self.meta)
                self.assertIn(expected_kind, self.card_kinds(result))

    def queue_call(self, **values):
        result = {
            "uniqueid": "l1", "linkedid": "l1", "caller_number": "2121",
            "queue_id": "6501", "queue_name": "Sales",
            "entry_time": "2026-07-28 10:00:00",
            "answer_time": "", "hangup_time": "",
            "status": "ENTERED", "agent": "", "hangup_by": "",
        }
        result.update(values)
        return result

    def attempts_for(self, events, **queue_values):
        result = cdr_journey.build_call_journey(
            [self.row(src="2121", dst="6501", dcontext="queue-6501", lastapp="Queue",
                      answer_time="0000-00-00 00:00:00", status="NO ANSWER")],
            self.queue_call(**queue_values), events, self.meta,
        )
        queue = next(card for card in result["journey"] if card["kind"] == "queue")
        return queue.get("agent_attempts", [])

    def test_agent_attempt_statuses_are_limited_to_the_five_supported_values(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:15"},
        ])
        self.assertEqual([item["status"] for item in attempts], ["No Answer"])
        self.assertTrue(set(item["status"] for item in attempts) <= cdr_journey.ATTEMPT_STATUSES)

    def test_agent_answers_only_after_a_real_answer_event(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
        ], status="ANSWERED", agent="5001", answer_time="2026-07-28 10:00:02")
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [("5001", "Answered")])

    def test_agent_timeout_is_no_answer(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:15"},
        ])
        self.assertEqual(attempts[0]["status"], "No Answer")
        self.assertEqual(attempts[0]["ring_duration_seconds"], 15)

    def test_early_ring_no_answer_is_cancelled_before_member_timeout(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:02"},
            {"agent": "5002", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:03"},
        ])
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [("5001", "Cancelled")])

    def test_duplicate_ring_records_stay_one_attempt(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:01"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:04"},
        ])
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [("5001", "Cancelled")])

    def test_explicit_agent_rejection_is_cancelled(self):
        attempts = self.attempts_for([
            {"agent": "5002", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5002", "queue": "6501", "event_type": "RINGCANCELED", "timestamp": "2026-07-28 10:00:04"},
        ])
        self.assertEqual(attempts[0]["status"], "Cancelled")

    def test_caller_hangup_resolves_all_active_unanswered_agents(self):
        events = [
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5002", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "", "queue": "6501", "event_type": "ABANDON", "timestamp": "2026-07-28 10:00:07"},
        ]
        attempts = self.attempts_for(events, status="ABANDONED", hangup_by="CALLER", hangup_time="2026-07-28 10:00:07")
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [
            ("5001", "Caller Hangup"), ("5002", "Caller Hangup")
        ])

    def test_queue_timeout_is_distinct_from_agent_ring_timeout(self):
        attempts = self.attempts_for([
            {"agent": "5004", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:50"},
            {"agent": "", "queue": "6501", "event_type": "EXITWITHTIMEOUT", "timestamp": "2026-07-28 10:01:00"},
        ], status="TIMEOUT", hangup_time="2026-07-28 10:01:00")
        self.assertEqual(attempts[0]["status"], "Queue Timeout")
        self.assertNotEqual(attempts[0]["status"], "No Answer")

    def test_simultaneous_non_answering_agent_is_not_marked_cancelled_without_evidence(self):
        events = [
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5002", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5002", "queue": "6501", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGCANCELED", "timestamp": "2026-07-28 10:00:02"},
        ]
        attempts = self.attempts_for(events, status="ANSWERED", agent="5002", answer_time="2026-07-28 10:00:02")
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [("5002", "Answered")])

    def test_same_agent_is_kept_as_two_chronological_attempts(self):
        events = [
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:15"},
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:20"},
            {"agent": "5001", "queue": "6501", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:22"},
        ]
        attempts = self.attempts_for(events, status="ANSWERED", agent="5001", answer_time="2026-07-28 10:00:22")
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [
            ("5001", "No Answer"), ("5001", "Answered")
        ])
        self.assertLess(attempts[0]["attempt_started_at"], attempts[1]["attempt_started_at"])

    def test_multiple_queues_keep_attempts_attached_to_their_queue(self):
        rows = [self.row(src="2121", dst="6501", dcontext="from-internal", userfield="~DEST:queue:6501~DEST:queue:6502")]
        queue_calls = [
            self.queue_call(queue_id="6501", queue_name="Sales", status="NO ANSWER", agent=""),
            self.queue_call(queue_id="6502", queue_name="Escalation", status="ANSWERED", agent="5003",
                            entry_time="2026-07-28 10:00:20", answer_time="2026-07-28 10:00:22"),
        ]
        events = [
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:01"},
            {"agent": "5001", "queue": "6501", "event_type": "RINGNOANSWER", "timestamp": "2026-07-28 10:00:15"},
            {"agent": "5003", "queue": "6502", "event_type": "RING", "timestamp": "2026-07-28 10:00:20"},
            {"agent": "5003", "queue": "6502", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:22"},
        ]
        primary = dict(queue_calls[0], _related_queue_calls=queue_calls)
        result = cdr_journey.build_call_journey(rows, primary, events, self.meta)
        queues = [card for card in result["journey"] if card["kind"] == "queue"]
        self.assertEqual(len(queues), 2)
        self.assertEqual([item["status"] for item in queues[0]["agent_attempts"]], ["No Answer"])
        self.assertEqual([item["status"] for item in queues[1]["agent_attempts"]], ["Answered"])

    def test_early_agent_channel_end_is_cancelled(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "HANGUP", "timestamp": "2026-07-28 10:00:04"},
        ])
        self.assertEqual([(item["extension"], item["status"]) for item in attempts], [("5001", "Cancelled")])

    def test_answered_attempt_stays_answered_when_caller_hangs_up_later(self):
        attempts = self.attempts_for([
            {"agent": "5001", "queue": "6501", "event_type": "RING", "timestamp": "2026-07-28 10:00:00"},
            {"agent": "5001", "queue": "6501", "event_type": "ANSWER", "timestamp": "2026-07-28 10:00:02"},
            {"agent": "", "queue": "6501", "event_type": "COMPLETECALLER", "timestamp": "2026-07-28 10:00:10"},
        ], status="ANSWERED", agent="5001", answer_time="2026-07-28 10:00:02", hangup_by="CALLER", hangup_time="2026-07-28 10:00:10")
        self.assertEqual([item["status"] for item in attempts], ["Answered"])


if __name__ == "__main__":
    unittest.main()
