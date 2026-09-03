import unittest
import os
import sqlite3
import datetime
import json
import db
import mail_service
import scheduler_service

class TestEmailSystem(unittest.TestCase):

    def setUp(self):
        # Force re-initialization of DB to ensure all schema alterations are active
        db.init_db()
        
        # Clear mail logs, mail settings, otp records, and test extensions
        conn = db.get_db()
        c = conn.cursor()
        c.execute("DELETE FROM mail_settings")
        c.execute("DELETE FROM mail_logs")
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
        c.execute("DELETE FROM otp_records")
        c.execute("DELETE FROM extensions WHERE ext = '5599'")
        c.execute("DELETE FROM users WHERE username = 'testuser'")
        conn.commit()
        conn.close()

    def test_mail_settings_saving_and_masking(self):
        # Test saving and retrieval
        settings_data = {
            "provider": "google",
            "smtp_server": "smtp.gmail.com",
            "smtp_port": "587",
            "encryption": "tls",
            "sender_email": "pbx@example.com",
            "username": "mypbx",
            "password": mail_service.encrypt_password("my-app-password"),
            "missed_calls_alert_enabled": 1,
            "missed_calls_threshold": "3",
            "cdr_report_enabled": 1,
            "cdr_report_email": "admin@example.com",
            "cdr_report_schedule": "weekly"
        }
        db.save_mail_settings(settings_data)

        fetched = db.get_mail_settings()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["provider"], "google")
        self.assertEqual(fetched["smtp_server"], "smtp.gmail.com")
        self.assertEqual(fetched["smtp_port"], 587)
        self.assertEqual(fetched["encryption"], "tls")
        self.assertEqual(fetched["sender_email"], "pbx@example.com")
        self.assertEqual(fetched["username"], "mypbx")
        self.assertEqual(fetched["missed_calls_alert_enabled"], 1)
        self.assertEqual(fetched["missed_calls_threshold"], 3)
        self.assertEqual(fetched["cdr_report_enabled"], 1)
        self.assertEqual(fetched["cdr_report_email"], "admin@example.com")
        self.assertEqual(fetched["cdr_report_schedule"], "weekly")

        # Decrypt password check
        decrypted = mail_service.decrypt_password(fetched["password"])
        self.assertEqual(decrypted, "my-app-password")

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

        # Attempt 3 - will block
        success, err = db.verify_otp(username, "333333")
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
