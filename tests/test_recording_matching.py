import os
import tempfile
import unittest
import csv

import db


class RecordingMatchingTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="rcm_recording_match_")
        self.original_dir = db.MONITOR_RECORDING_DIR
        db.MONITOR_RECORDING_DIR = self.temp_dir.name
        self.base = 1700000000

    def tearDown(self):
        db.MONITOR_RECORDING_DIR = self.original_dir
        self.temp_dir.cleanup()

    def add_recording(self, filename, offset=16):
        path = os.path.join(self.temp_dir.name, filename)
        with open(path, "wb") as stream:
            stream.write(b"0" * 128)
        os.utime(path, (self.base + offset, self.base + offset))

    def test_all_generated_recording_name_families_match_cdr(self):
        cases = [
            ("2121-5001-20231114-221336.wav", "2121", "5001", "", ()),
            ("queue-6501-2121-20231114-221336.wav", "2121", "6501", "~IVR:7001:main~DEST:queue:6501", ()),
            ("ivr-7001-2121-20231114-221336.wav", "2121", "6501", "~IVR:7001:main~DEST:queue:6501", ()),
            ("ringgroup-6400-2121-20231114-221336.wav", "2121", "6400", "~RINGGROUP:6400:team", ()),
            ("paging-258-2121-20231114-221336.wav", "2121", "258", "~PAGING:258:intercom", ()),
            ("in-main_route_id-7000-01012345678-20231114-221336.wav", "01012345678", "2121", "", ()),
        ]
        for filename, src, dst, userfield, extra in cases:
            with self.subTest(filename=filename):
                self.add_recording(filename)
                match = db.find_recording_for_cdr(
                    src=src,
                    dst=dst,
                    uniqueid=str(self.base),
                    duration=15,
                    billsec=15,
                    userfield=userfield,
                    extra_parties=extra,
                )
                self.assertEqual(match, filename)
                os.unlink(os.path.join(self.temp_dir.name, filename))

    def test_empty_wav_headers_are_not_reported_as_recordings(self):
        filename = "queue-6501-2121-20231114-221336.wav"
        path = os.path.join(self.temp_dir.name, filename)
        with open(path, "wb") as stream:
            stream.write(b"0" * 44)
        os.utime(path, (self.base + 16, self.base + 16))
        self.assertEqual(
            db.find_recording_for_cdr("2121", "6501", str(self.base), duration=15),
            "",
        )

    def test_new_filename_requires_exact_call_id(self):
        exact = f"rcm-{self.base}-queue-6501-2121-20231114-221336.wav"
        nearby = "rcm-1700000001-queue-6501-2121-20231114-221337.wav"
        self.add_recording(exact, offset=16)
        self.add_recording(nearby, offset=17)
        self.assertEqual(
            db.find_recording_for_cdr("2121", "6501", str(self.base), duration=15),
            exact,
        )
        self.assertEqual(
            db.find_recording_for_cdr("2121", "6501", str(self.base + 2), duration=15),
            "",
        )

    def test_cdr_sync_persists_queue_recording_path(self):
        old_db_path = db.DB_PATH
        old_cdr_path = db.CDR_CSV_PATH
        db_path = os.path.join(self.temp_dir.name, "main.db")
        cdr_path = os.path.join(self.temp_dir.name, "Master.csv")
        db.DB_PATH = db_path
        db.CDR_CSV_PATH = cdr_path
        try:
            db.init_db()
            filename = "queue-6501-2121-20231114-221336.wav"
            self.add_recording(filename)
            row = [
                "", "2121", "6501", "queue-6501", '"main menu" <2121>',
                "PJSIP/2121-1", "PJSIP/5000-2", "Queue", "6501",
                "2023-11-14 22:13:20", "2023-11-14 22:13:20", "2023-11-14 22:13:35",
                "15", "15", "ANSWERED", "", str(self.base),
                "~IVR:7001:main~DEST:queue:6501",
            ]
            with open(cdr_path, "w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(row)

            db.sync_cdr_records()
            conn = db.get_db()
            try:
                stored = conn.execute(
                    "SELECT recording FROM cdr_records WHERE uniqueid = ?", (str(self.base),)
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(stored["recording"], filename)
        finally:
            db.DB_PATH = old_db_path
            db.CDR_CSV_PATH = old_cdr_path


if __name__ == "__main__":
    unittest.main()
