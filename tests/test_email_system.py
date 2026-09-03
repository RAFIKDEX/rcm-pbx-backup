import unittest
import os
import sqlite3
import datetime
import json
import shutil
import tempfile
import db
import mail_service
import scheduler_service
from unittest.mock import patch

class TestEmailSystem(unittest.TestCase):

    def setUp(self):
        # Never mutate the live PBX database while running tests. The email
        # tests clear settings and queues as part of their fixture setup.
        self.original_db_path = db.DB_PATH
        self.temp_dir = tempfile.mkdtemp(prefix="rcm_email_test_")
        self.test_db = os.path.join(self.temp_dir, "rcm.db")
        shutil.copy2(self.original_db_path, self.test_db)
        db.DB_PATH = self.test_db

        # Force re-initialization of DB to ensure all schema alterations are active
        db.init_db()
        
        # Clear mail logs, mail settings, otp records, and test extensions
        conn = db.get_db()
        c = conn.cursor()
        c.execute("DELETE FROM mail_settings")
        c.execute("DELETE FROM mail_logs")
        c.execute("DELETE FROM mail_queue")
        c.execute("DELETE FROM otp_records")
        c.execute("DELETE FROM extensions WHERE ext = '5599'")
        c.execute("DELETE FROM users WHERE username = 'testuser'")
        conn.commit()
        conn.close()

    def tearDown(self):
        # Cleanup test entries
        conn = db.get_db()
        c = conn.cursor()
        c.execute("DELETE FROM mail_settings")
        c.execute("DELETE FROM mail_logs")
        c.execute("DELETE FROM mail_queue")
        c.execute("DELETE FROM otp_records")
        c.execute("DELETE FROM extensions WHERE ext = '5599'")
        c.execute("DELETE FROM users WHERE username = 'testuser'")
        conn.commit()
        conn.close()
        db.DB_PATH = self.original_db_path
        shutil.rmtree(self.temp_dir)

    def test_mail_settings_saving_and_masking(self):
        # Test saving and retrieval
        settings_data = {
            "provider": "google",
            "smtp_server": "smtp.gmail.com",
            "smtp_port": "587",
            "encryption": "tls",
            "sender_email": "pbx@example.com",
            "display_name": "RCM 7021 PBX",
            "username": "mypbx",
            "password": mail_service.encrypt_password("my-app-password"),
            "missed_calls_alert_enabled": 1,
            "missed_calls_threshold": "3",
            "cdr_report_enabled": 1,
            "cdr_report_email": "admin@example.com",
            "cdr_report_schedule": "weekly",
            "cdr_report_time": "14:30",
            "cdr_report_weekday": "2",
            "cdr_report_month_day": "15"
        }
        db.save_mail_settings(settings_data)

        fetched = db.get_mail_settings()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["provider"], "google")
        self.assertEqual(fetched["smtp_server"], "smtp.gmail.com")
        self.assertEqual(fetched["smtp_port"], 587)
        self.assertEqual(fetched["encryption"], "tls")
        self.assertEqual(fetched["sender_email"], "pbx@example.com")
        self.assertEqual(fetched["display_name"], "RCM 7021 PBX")
        self.assertEqual(fetched["username"], "mypbx")
        self.assertEqual(fetched["missed_calls_alert_enabled"], 1)
        self.assertEqual(fetched["missed_calls_threshold"], 3)
        self.assertEqual(fetched["cdr_report_enabled"], 1)
        self.assertEqual(fetched["cdr_report_email"], "admin@example.com")
        self.assertEqual(fetched["cdr_report_schedule"], "weekly")
        self.assertEqual(fetched["cdr_report_time"], "14:30")
        self.assertEqual(fetched["cdr_report_weekday"], 2)
        self.assertEqual(fetched["cdr_report_month_day"], 15)

        # Decrypt password check
        decrypted = mail_service.decrypt_password(fetched["password"])
        self.assertEqual(decrypted, "my-app-password")

    def test_display_name_is_used_in_from_header(self):
        class FakeSMTP:
            def __init__(self):
                self.message = ""

            def starttls(self, context=None):
                pass

            def login(self, username, password):
                pass

            def sendmail(self, sender, recipients, message):
                self.message = message

            def quit(self):
                pass

        fake_server = FakeSMTP()
        with patch.object(mail_service.smtplib, "SMTP", return_value=fake_server):
            success, error = mail_service.send_email(
                receiver_email="admin@example.com",
                subject="Header Test",
                body_html="<p>Test</p>",
                body_text="Test",
                feature="Test",
                config_override={
                    "smtp_server": "smtp.example.com",
                    "smtp_port": "587",
                    "encryption": "tls",
                    "sender_email": "pbx@example.com",
                    "display_name": "RCM 7021 PBX",
                    "username": "pbx@example.com",
                    "password": "app-password",
                },
            )

        self.assertTrue(success, error)
        self.assertIn("From: RCM 7021 PBX <pbx@example.com>", fake_server.message)

    def test_missed_call_identity_and_status_are_normalized(self):
        number, name = scheduler_service.parse_caller_identity('"Mostafa Alaa" <135>', "135")
        self.assertEqual(number, "135")
        self.assertEqual(name, "Mostafa Alaa")

        number, name = scheduler_service.parse_caller_identity("5002", "5002")
        self.assertEqual(number, "5002")
        self.assertEqual(name, "")

        self.assertEqual(scheduler_service.normalize_missed_call_status("NO ANSWER"), "No Answer")
        self.assertEqual(scheduler_service.normalize_missed_call_status("BUSY"), "Busy")
        self.assertEqual(scheduler_service.normalize_missed_call_status("CHANUNAVAIL"), "Unavailable")

        unavailable_row = [""] * 18
        unavailable_row[7] = "Playback"
        unavailable_row[8] = "This_extension_is_unavailable"
        unavailable_row[14] = "ANSWERED"
        self.assertEqual(scheduler_service.missed_status_from_cdr(unavailable_row), "Unavailable")

        answered_row = [""] * 18
        answered_row[7] = "Dial"
        answered_row[14] = "ANSWERED"
        self.assertIsNone(scheduler_service.missed_status_from_cdr(answered_row))

    def test_cdr_report_schedule_waits_for_configured_occurrence(self):
        monday_before = datetime.datetime(2026, 7, 20, 8, 59)
        monday_after = datetime.datetime(2026, 7, 20, 9, 0)
        self.assertFalse(scheduler_service.is_cdr_report_due(
            monday_before, None, "daily", "09:00"
        ))
        self.assertTrue(scheduler_service.is_cdr_report_due(
            monday_after, None, "daily", "09:00"
        ))
        self.assertFalse(scheduler_service.is_cdr_report_due(
            monday_after, monday_after, "daily", "09:00"
        ))

        weekly_occurrence = scheduler_service.scheduled_report_occurrence(
            datetime.datetime(2026, 7, 22, 15, 0), "weekly", "10:00", 2
        )
        self.assertEqual(weekly_occurrence, datetime.datetime(2026, 7, 22, 10, 0))

        monthly_occurrence = scheduler_service.scheduled_report_occurrence(
            datetime.datetime(2026, 2, 28, 12, 0), "monthly", "10:00", 0, 31
        )
        self.assertEqual(monthly_occurrence, datetime.datetime(2026, 2, 28, 10, 0))

    def test_cdr_workbook_has_no_recording_link_and_supports_direction(self):
        path = os.path.join(self.temp_dir, "extension_report.xlsx")
        scheduler_service.write_cdr_workbook([
            {
                "Date": "2026-07-22", "Time": "10:00:00", "Caller": "2121",
                "Destination": "5001", "Direction": "Outbound",
                "Duration (s)": 12, "Status": "ANSWERED",
            }
        ], "Weekly Extension 2121", path, include_direction=True)

        import openpyxl
        workbook = openpyxl.load_workbook(path, read_only=True)
        headers = [cell.value for cell in next(workbook.active.iter_rows())]
        self.assertIn("Direction", headers)
        self.assertNotIn("Recording Link", headers)
        workbook.close()

    def test_otp_lifecycle(self):
        username = "testuser"
        email = "testuser@example.com"
        otp = "123456"

        # 1. Create OTP
        db.create_otp(username, email, otp, expires_in_minutes=5)

        # 2. Verify with wrong OTP
        success, err = db.verify_otp(username, "654321")
        self.assertFalse(success)
        self.assertIn("Invalid OTP", err)
        self.assertIn("2 attempts remaining", err)

        # 3. Verify with correct OTP
        success, err = db.verify_otp(username, "123456")
        self.assertTrue(success)
        self.assertEqual(err, "")

    def test_otp_expiry(self):
        username = "testuser"
        email = "testuser@example.com"
        otp = "999999"

        # Create expired OTP (expires in -1 minutes)
        db.create_otp(username, email, otp, expires_in_minutes=-1)

        success, err = db.verify_otp(username, otp)
        self.assertFalse(success)
        self.assertIn("expired", err.lower())

    def test_otp_attempt_limits(self):
        username = "testuser"
        email = "testuser@example.com"
        otp = "888888"

        db.create_otp(username, email, otp, expires_in_minutes=5)

        # Attempt 1
        success, _ = db.verify_otp(username, "111111")
        self.assertFalse(success)

        # Attempt 2
        success, _ = db.verify_otp(username, "222222")
        self.assertFalse(success)

        # Attempt 3 - will leave 0 remaining
        success, err = db.verify_otp(username, "333333")
        self.assertFalse(success)
        self.assertIn("0 attempts remaining", err)

        # Attempt 4 - will block
        success, err = db.verify_otp(username, "444444")
        self.assertFalse(success)
        self.assertIn("Too many wrong attempts", err)

    def test_extension_email_field(self):
        ext_data = {
            "ext": "5599",
            "enabled": 1,
            "name": "Test Extension",
            "callerid_number": "5599",
            "secret": "Secret123!",
            "max_contacts": 3,
            "max_expiration": 120,
            "ring_time": 60,
            "vm_enabled": 0,
            "vm_password": "1234",
            "record_mode": "noo",
            "direct_media": 0,
            "nat": 0,
            "followme": [],
            "mobile": "+3161234567",
            "email": "user5599@example.com",
            "allow_spy": 1
        }

        # Save extension
        db.add_extension(ext_data)

        # Retrieve extension and verify email column
        fetched = db.get_extension("5599")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["email"], "user5599@example.com")
        self.assertEqual(fetched["mobile"], "+3161234567")

        # Update extension email
        ext_data["email"] = "updated5599@example.com"
        db.update_extension("5599", ext_data)

        fetched_updated = db.get_extension("5599")
        self.assertEqual(fetched_updated["email"], "updated5599@example.com")

    def test_email_outbox_logging(self):
        db.log_email(
            receiver="rcv@example.com",
            sender="snd@example.com",
            subject="Test Log Entry",
            status="Success",
            error_msg="",
            feature="Test"
        )

        logs = db.get_mail_logs(limit=5)
        self.assertGreater(len(logs), 0)
        self.assertEqual(logs[0]["receiver_email"], "rcv@example.com")
        self.assertEqual(logs[0]["sender_email"], "snd@example.com")
        self.assertEqual(logs[0]["subject"], "Test Log Entry")
        self.assertEqual(logs[0]["status"], "Success")
        self.assertEqual(logs[0]["feature"], "Test")

    def test_mail_queue_retry(self):
        # 1. Add item to queue
        db.add_to_mail_queue(
            receiver="fail@example.com",
            subject="Failed Mail",
            body_html="<p>Failed</p>",
            body_text="Failed",
            attachments=[],
            feature="OTP"
        )

        # 2. Check pending queue
        queue = db.get_pending_mail_queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["attempts"], 0)

        # 3. Process the queue (will fail to send since no SMTP settings are configured)
        scheduler_service.process_mail_queue()

        # 4. Check attempts increments
        queue_after = db.get_pending_mail_queue()
        # Since it failed, attempts should increment to 1 (but wait, it updates next_retry with backoff, so it might not show in get_pending_mail_queue() because next_retry is set to +5 minutes)
        # Let's query directly from DB
        conn = db.get_db()
        c = conn.cursor()
        c.execute("SELECT attempts FROM mail_queue WHERE receiver_email = 'fail@example.com'")
        row = c.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["attempts"], 1)

    def test_xlsx_report_generation(self):
        import openpyxl
        # Compile a test workbook using same openpyxl commands as scheduler
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "CDR Report"
        headers = ["Date", "Time", "Caller", "Destination", "Extension", "Queue", "Duration (s)", "Status", "Recording Link"]
        ws.append(headers)
        ws.append(["2026-06-28", "14:10:02", "5001", "6500", "5001", "6500", 30, "ANSWERED", ""])
        
        path = "/tmp/test_report.xlsx"
        wb.save(path)
        
        # Reload and verify
        wb_loaded = openpyxl.load_workbook(path)
        self.assertIn("CDR Report", wb_loaded.sheetnames)
        ws_loaded = wb_loaded["CDR Report"]
        self.assertEqual(ws_loaded.cell(row=1, column=1).value, "Date")
        self.assertEqual(ws_loaded.cell(row=2, column=3).value, "5001")
        
        # Cleanup
        os.remove(path)
