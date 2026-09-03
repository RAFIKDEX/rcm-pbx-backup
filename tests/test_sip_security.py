import unittest
import os
import subprocess
import sqlite3
import time
import ipaddress
from unittest.mock import patch
import sys
sys.path.append('/root/RCM_7021')
import sip_security_manager

class TestSipSecurity(unittest.TestCase):
    def setUp(self):
        self.db_path = '/root/RCM_7021/rcm_7021.db'
        self.conn = sqlite3.connect(self.db_path)
        self.c = self.conn.cursor()
        
    def tearDown(self):
        self.conn.close()
        
    def test_enabled_false_jail_removal_and_sshd_active(self):
        # Set to disabled
        self.c.execute("UPDATE sip_security_settings SET enabled = 0 WHERE id = 1;")
        self.conn.commit()
        sip_security_manager.apply_configuration()
        
        # Verify rcm-pjsip-register does not exist but sshd does
        res = subprocess.run(['/usr/bin/fail2ban-client', 'status'], capture_output=True, text=True)
        self.assertNotIn('rcm-pjsip-register', res.stdout)
        self.assertIn('sshd', res.stdout)
        
        # Set to enabled again
        self.c.execute("UPDATE sip_security_settings SET enabled = 1 WHERE id = 1;")
        self.conn.commit()
        sip_security_manager.apply_configuration()

    @patch('sip_security_manager._run_helper')
    def test_failed_unban_retry(self, mock_helper):
        # Add test entry
        mock_helper.return_value = {'success': True}
        sip_security_manager.add_blacklist('1.2.3.4', 0, 'Test', 'system')
        self.c.execute("SELECT id FROM sip_security_blacklist WHERE value = '1.2.3.4' ORDER BY id DESC LIMIT 1")
        entry_id = self.c.fetchone()[0]
        
        self.c.execute("UPDATE sip_security_blacklist SET expires_at = datetime('now', '-1 minutes') WHERE id = ?", (entry_id,))
        self.conn.commit()
        
        # Simulate failure
        mock_helper.return_value = {'success': False, 'error': 'Simulated'}
        sip_security_manager.reconcile_bans()
        
        # Assert status is error, not expired
        self.c.execute("SELECT status FROM sip_security_blacklist WHERE id = ?", (entry_id,))
        self.assertEqual(self.c.fetchone()[0], 'error')
        
        # Simulate success
        mock_helper.return_value = {'success': True}
        sip_security_manager.reconcile_bans()
        
        # Assert status is expired
        self.c.execute("SELECT status FROM sip_security_blacklist WHERE id = ?", (entry_id,))
        self.assertEqual(self.c.fetchone()[0], 'expired')
        
        # Ensure single audit event for this specific entry id or time
        self.c.execute("SELECT count(*) FROM sip_security_events WHERE source_ip = '1.2.3.4' AND event_type = 'Automatic Expiry'")
        self.assertEqual(self.c.fetchone()[0], 1)
        
    def test_helper_negative_validation(self):
        helper_path = '/usr/local/bin/rcm_fail2ban_helper.py'
        # Invalid IP
        res = subprocess.run(['sudo', helper_path, 'ban'], input='{"ip": "999.999.999.999", "jail": "rcm-pjsip-blacklist"}', text=True, capture_output=True)
        self.assertIn('Invalid IP/CIDR', res.stdout)
        
        # Arbitrary Jail
        res = subprocess.run(['sudo', helper_path, 'ban'], input='{"ip": "1.1.1.1", "jail": "sshd"}', text=True, capture_output=True)
        self.assertIn('Disallowed jail', res.stdout)
        
        # File path
        res = subprocess.run(['sudo', helper_path, 'ban'], input='{"ip": "/etc/shadow", "jail": "rcm-pjsip-blacklist"}', text=True, capture_output=True)
        self.assertIn('Invalid IP/CIDR', res.stdout)
        
    def test_regex_ipv6_and_injection(self):
        import tempfile
        # IPv6
        log_line = "[Jul 10] NOTICE res_pjsip/pjsip_distributor.c: Request 'REGISTER' failed for '[2001:db8::1]:5060'"
        # Malicious Injection
        bad_log = "[Jul 10] NOTICE res_pjsip/pjsip_distributor.c: Request 'REGISTER' failed for '1.1.1.1; rm -rf /'"
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(log_line + "\n" + bad_log + "\n")
            f_name = f.name
            
        res = subprocess.run(['fail2ban-regex', f_name, '/etc/fail2ban/filter.d/rcm-pjsip-register.conf'], capture_output=True, text=True)
        os.unlink(f_name)
        
        self.assertIn('1 matched', res.stdout)

    def test_duplicate_reconciliation_locking(self):
        import fcntl
        subprocess.run(['rm', '-f', '/tmp/rcm_sip_reconcile.lock'])
        lock_file = open('/tmp/rcm_sip_reconcile.lock', 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            res = subprocess.run(['/usr/local/bin/rcm_sip_reconcile.py'], capture_output=True, text=True)
            self.assertIn('already running', res.stderr)
            self.assertEqual(res.returncode, 0)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

if __name__ == '__main__':
    unittest.main()
