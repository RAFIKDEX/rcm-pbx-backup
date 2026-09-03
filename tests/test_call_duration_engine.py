import unittest

from cdr_journey import calculate_call_durations


class CallDurationEngineTestCase(unittest.TestCase):
    base = "2026-07-29 10:00:00"

    def ts(self, seconds):
        minutes, remainder = divmod(seconds, 60)
        return f"2026-07-29 10:{minutes:02d}:{remainder:02d}"

    def event(self, seconds, event_type, **extra):
        return {"event_type": event_type, "timestamp": self.ts(seconds), **extra}

    def row(self, start=0, end=100, status="ANSWERED", answer=10, billsec=90, **extra):
        value = {
            "uniqueid": "leg-1",
            "linkedid": "call-1",
            "src": "0100000000",
            "dst": "5001",
            "start_time": self.ts(start),
            "answer_time": self.ts(answer) if answer is not None else "",
            "end_time": self.ts(end),
            "status": status,
            "billsec": billsec,
        }
        value.update(extra)
        return value

    def queue(self, start=0, end=100, status="ANSWERED", answer=10, **extra):
        value = {
            "uniqueid": "leg-1",
            "linkedid": "call-1",
            "entry_time": self.ts(start),
            "answer_time": self.ts(answer) if answer is not None else "",
            "hangup_time": self.ts(end),
            "status": status,
            "talk_time": 0,
        }
        value.update(extra)
        return value

    def durations(self, events, row=None, queue=None, **kwargs):
        return calculate_call_durations(
            [row or self.row()], queue or self.queue(), events, **kwargs
        )

    def test_ivr_or_queue_wait_without_answer_has_only_call_time(self):
        result = self.durations([
            self.event(0, "ENTERQUEUE"),
            self.event(90, "ABANDON"),
        ], row=self.row(end=90, status="ABANDONED", answer=None), queue=self.queue(end=90, status="ABANDONED", answer=None))
        self.assertEqual((result["call_time"], result["talk_time"], result["hold_time"]), (90, 0, 0))

    def test_cdr_wait_continues_through_ivr_until_agent_answers(self):
        rows = [
            self.row(
                uniqueid="ivr-leg", start_time=self.ts(0), answer_time=self.ts(0),
                end_time=self.ts(35), status="ANSWERED", dcontext="from-trunk",
                lastapp="Answer",
            ),
            self.row(
                uniqueid="queue-leg", start_time=self.ts(20), answer_time=self.ts(35),
                end_time=self.ts(50), status="ANSWERED", dcontext="queue-6501",
            ),
        ]
        result = calculate_call_durations(
            rows,
            self.queue(start=20, end=50, answer=35, status="ANSWERED", agent="5001"),
            [self.event(35, "ANSWER", agent="5001"), self.event(35, "CONNECT"), self.event(50, "COMPLETE")],
        )
        self.assertEqual(result["wait_time"], 35)

    def test_ringing_without_answer_is_not_talk(self):
        result = self.durations([
            self.event(10, "RING"),
            self.event(30, "RINGNOANSWER"),
            self.event(40, "ABANDON"),
        ], row=self.row(end=40, status="NO ANSWER", answer=None), queue=self.queue(end=40, status="NO ANSWER", answer=None))
        self.assertEqual(result["call_time"], 40)
        self.assertEqual(result["talk_time"], 0)
        self.assertEqual(result["hold_time"], 0)

    def test_queue_timeout_while_agent_is_ringing_has_no_talk_or_hold(self):
        result = self.durations([
            self.event(20, "RING"),
            self.event(45, "EXITWITHTIMEOUT"),
        ], row=self.row(end=45, status="TIMEOUT", answer=None), queue=self.queue(end=45, status="TIMEOUT", answer=None))
        self.assertEqual((result["call_time"], result["talk_time"], result["hold_time"]), (45, 0, 0))

    def test_real_bridge_without_hold_is_net_talk(self):
        result = self.durations([self.event(10, "CONNECT"), self.event(100, "COMPLETE")])
        self.assertEqual(result["talk_time"], 90)
        self.assertEqual(result["hold_time"], 0)

    def test_answer_without_caller_bridge_does_not_start_talk(self):
        result = self.durations([self.event(10, "ANSWER"), self.event(100, "COMPLETE")])
        self.assertEqual(result["talk_time"], 0)

    def test_hold_after_answer_is_counted_even_when_connect_event_is_missing(self):
        result = self.durations([
            self.event(10, "ANSWER"),
            self.event(30, "HOLD"),
            self.event(50, "UNHOLD"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 0)
        self.assertEqual(result["hold_time"], 20)

    def test_persisted_queue_hold_is_used_only_when_raw_hold_events_are_missing(self):
        result = self.durations(
            [self.event(10, "ANSWER"), self.event(100, "COMPLETE")],
            queue=self.queue(hold_time=17),
        )
        self.assertEqual(result["hold_time"], 17)

    def test_hold_splits_talk_and_is_counted(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(40, "HOLD"),
            self.event(70, "UNHOLD"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 60)
        self.assertEqual(result["hold_time"], 30)

    def test_multiple_hold_periods_are_summed_once(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(20, "HOLD"),
            self.event(40, "UNHOLD"),
            self.event(50, "HOLD"),
            self.event(95, "UNHOLD"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 25)
        self.assertEqual(result["hold_time"], 65)

    def test_duplicate_hold_events_do_not_double_count(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(20, "HOLD"),
            self.event(20, "HOLD"),
            self.event(40, "UNHOLD"),
            self.event(40, "UNHOLD"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 70)
        self.assertEqual(result["hold_time"], 20)

    def test_queue_moh_before_answer_is_not_real_hold(self):
        result = self.durations([
            self.event(5, "HOLD"),
            self.event(20, "UNHOLD"),
            self.event(30, "CONNECT"),
            self.event(60, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 30)
        self.assertEqual(result["hold_time"], 0)

    def test_transfer_wait_without_hold_is_call_time_only(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(50, "TRANSFER"),
            self.event(65, "RING"),
            self.event(80, "CONNECT"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 60)
        self.assertEqual(result["hold_time"], 0)

    def test_transfer_wait_with_confirmed_hold_is_hold(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(50, "TRANSFER"),
            self.event(50, "HOLD"),
            self.event(65, "CONNECT"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 75)
        self.assertEqual(result["hold_time"], 15)

    def test_failed_transfer_returns_to_original_agent(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(50, "TRANSFER"),
            self.event(55, "RING"),
            self.event(70, "RINGNOANSWER"),
            self.event(75, "CONNECT"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 65)

    def test_caller_hangup_while_transfer_target_is_ringing_is_not_talk(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(40, "TRANSFER"),
            self.event(45, "RING"),
            self.event(60, "ABANDON"),
        ], row=self.row(end=60), queue=self.queue(end=60))
        self.assertEqual(result["talk_time"], 30)

    def test_transfer_to_second_queue_wait_and_ring_are_not_talk(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(40, "TRANSFER"),
            self.event(45, "ENTERQUEUE"),
            self.event(70, "RING"),
            self.event(80, "CONNECT"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 50)

    def test_attended_consultation_without_caller_is_not_talk(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(30, "HOLD"),
            self.event(40, "BRIDGE", caller_in_bridge=False),
            self.event(60, "TRANSFER"),
            self.event(70, "CONNECT"),
            self.event(100, "COMPLETE"),
        ])
        self.assertEqual(result["talk_time"], 50)
        self.assertEqual(result["hold_time"], 40)

    def test_caller_hangup_closes_open_hold(self):
        result = self.durations([
            self.event(10, "CONNECT"),
            self.event(30, "HOLD"),
            self.event(50, "HANGUP"),
        ], row=self.row(end=50), queue=self.queue(end=50))
        self.assertEqual(result["talk_time"], 20)
        self.assertEqual(result["hold_time"], 20)

    def test_overlapping_bridge_records_are_unioned(self):
        result = self.durations([
            self.event(10, "BRIDGE"),
            self.event(90, "BRIDGE", duplicate=True),
            self.event(100, "BRIDGELEAVE"),
        ])
        self.assertEqual(result["talk_time"], 90)

    def test_local_channels_do_not_double_talk(self):
        rows = [
            self.row(uniqueid="local-1", start_time=self.ts(10), answer_time=self.ts(10), end_time=self.ts(100), billsec=90),
            self.row(uniqueid="local-2", start_time=self.ts(10), answer_time=self.ts(10), end_time=self.ts(100), billsec=90),
        ]
        result = calculate_call_durations(rows, self.queue(), [self.event(10, "CONNECT"), self.event(100, "COMPLETE")])
        self.assertEqual(result["talk_time"], 90)

    def test_multiple_queue_legs_use_one_wall_clock_call_time(self):
        queue = self.queue(end=200)
        queue["_related_queue_calls"] = [
            self.queue(start=0, end=100, answer=10),
            self.queue(start=120, end=200, answer=140),
        ]
        rows = [self.row(end=100), self.row(uniqueid="leg-2", start=120, answer=140, end=200)]
        result = calculate_call_durations(rows, queue, [
            self.event(10, "CONNECT"), self.event(100, "TRANSFER"),
            self.event(140, "CONNECT"), self.event(200, "COMPLETE"),
        ])
        self.assertEqual(result["call_time"], 200)
        self.assertEqual(result["talk_time"], 150)

    def test_multiple_answered_destinations_sum_only_caller_bridges(self):
        result = self.durations([
            self.event(10, "CONNECT"), self.event(40, "TRANSFER"),
            self.event(60, "CONNECT"), self.event(90, "TRANSFER"),
            self.event(120, "CONNECT"), self.event(150, "COMPLETE"),
        ], row=self.row(end=150), queue=self.queue(end=150))
        self.assertEqual(result["talk_time"], 90)

    def test_historical_billsec_fallback_is_not_summed(self):
        rows = [self.row(uniqueid="a", billsec=40), self.row(uniqueid="b", billsec=40)]
        result = calculate_call_durations(rows, self.queue(), [], legacy_fallback=True)
        self.assertEqual(result["talk_time"], 40)
        self.assertEqual(result["hold_time"], 0)

    def test_active_call_uses_moving_end_without_persisting(self):
        row = self.row(end=100)
        row["end_time"] = ""
        queue = self.queue(end=100)
        queue["hangup_time"] = ""
        result = calculate_call_durations(
            [row],
            queue,
            [self.event(10, "CONNECT")],
            now=self._now(100),
        )
        self.assertEqual(result["call_time"], 100)
        self.assertEqual(result["talk_time"], 90)

    def test_active_call_with_open_hold_updates_hold_until_live_end(self):
        row = self.row(end=100)
        row["end_time"] = ""
        queue = self.queue(end=100)
        queue["hangup_time"] = ""
        result = calculate_call_durations(
            [row], queue,
            [self.event(10, "CONNECT"), self.event(20, "HOLD")],
            now=self._now(50),
        )
        self.assertEqual(result["talk_time"], 10)
        self.assertEqual(result["hold_time"], 30)

    def _now(self, seconds):
        from datetime import datetime
        return datetime.strptime(self.ts(seconds), "%Y-%m-%d %H:%M:%S")

    def test_complete_spec_example_without_transfer_hold(self):
        result = self.durations([
            self.event(55, "CONNECT"), self.event(120, "HOLD"), self.event(150, "UNHOLD"),
            self.event(210, "TRANSFER"), self.event(220, "CONNECT"),
            self.event(240, "HOLD"), self.event(260, "UNHOLD"), self.event(300, "COMPLETE"),
        ], row=self.row(end=300), queue=self.queue(end=300))
        self.assertEqual((result["call_time"], result["talk_time"], result["hold_time"]), (300, 185, 50))

    def test_complete_spec_example_with_transfer_hold(self):
        result = self.durations([
            self.event(55, "CONNECT"), self.event(120, "HOLD"), self.event(150, "UNHOLD"),
            self.event(210, "TRANSFER"), self.event(210, "HOLD"), self.event(220, "CONNECT"),
            self.event(240, "HOLD"), self.event(260, "UNHOLD"), self.event(300, "COMPLETE"),
        ], row=self.row(end=300), queue=self.queue(end=300))
        self.assertEqual((result["call_time"], result["talk_time"], result["hold_time"]), (300, 185, 60))


if __name__ == "__main__":
    unittest.main()
