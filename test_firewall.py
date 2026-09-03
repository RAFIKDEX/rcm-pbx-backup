import unittest
from unittest.mock import patch, MagicMock
import os
import sqlite3
import json
import subprocess
import sys

sys.path.append('/root/RCM_7021')
from firewall_manager import ip_to_cidr, get_all_rules, add_rule, delete_rules, validate_rule, apply_firewall

class TestFirewallManager(unittest.TestCase):
    def setUp(self):
        # Create an in-memory DB for tests
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS rcm_firewall_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                subnet_mask TEXT NOT NULL,
                direction TEXT NOT NULL,
                protocol TEXT NOT NULL,
                port TEXT,
                action TEXT NOT NULL,
                comment TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS rcm_firewall_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        
        # Patch get_db to return our in-memory connection
        self.db_patcher = patch('firewall_manager.get_db', return_value=self.conn)
        self.mock_get_db = self.db_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()
        self.conn.close()

    def test_ip_to_cidr(self):
        self.assertEqual(ip_to_cidr("192.168.1.0", "255.255.255.0"), "24")
        self.assertEqual(ip_to_cidr("10.0.0.0", "255.0.0.0"), "8")
        self.assertEqual(ip_to_cidr("10.0.0.5", "255.255.255.255"), "32")
        with self.assertRaises(ValueError):
            ip_to_cidr("invalid_ip", "255.255.255.0")
        with self.assertRaises(ValueError):
            ip_to_cidr("192.168.1.0", "invalid_mask")

    def test_validate_rule_valid(self):
        valid_data = {
            "ip_address": "192.168.1.0",
            "subnet_mask": "255.255.255.0",
            "direction": "in",
            "protocol": "tcp",
            "port": "80",
            "action": "accept"
        }
        # Should not raise exception
        validate_rule(valid_data)

    def test_validate_rule_invalid_fields(self):
        invalid_data = {
            "ip_address": "192.168.1.0",
            "subnet_mask": "255.255.255.0",
            "direction": "invalid",
            "protocol": "tcp",
            "port": "80",
            "action": "accept"
        }
        with self.assertRaisesRegex(ValueError, "Invalid direction"):
            validate_rule(invalid_data)

    def test_admin_lockout_prevention(self):
        lockout_data = {
            "ip_address": "0.0.0.0",
            "subnet_mask": "0.0.0.0",
            "direction": "all",
            "protocol": "tcp",
            "port": "22",
            "action": "drop"
        }
        with self.assertRaisesRegex(ValueError, "Admin lockout prevention"):
            validate_rule(lockout_data)

    def test_add_and_get_rules(self):
        rule = {
            "ip_address": "10.0.0.0",
            "subnet_mask": "255.255.255.0",
            "direction": "out",
            "protocol": "udp",
            "port": "53",
            "action": "accept",
            "comment": "DNS"
        }
        add_rule(rule)
        rules = get_all_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["ip_address"], "10.0.0.0")
        self.assertEqual(rules[0]["direction"], "out")

    def test_duplicate_rule(self):
        rule = {
            "ip_address": "10.0.0.0",
            "subnet_mask": "255.255.255.0",
            "direction": "out",
            "protocol": "udp",
            "port": "53",
            "action": "accept",
            "comment": "DNS"
        }
        add_rule(rule)
        with self.assertRaisesRegex(ValueError, "duplicate rule"):
            add_rule(rule)

    def test_delete_rules(self):
        rule = {
            "ip_address": "10.0.0.0",
            "subnet_mask": "255.255.255.0",
            "direction": "out",
            "protocol": "udp",
            "port": "53",
            "action": "accept",
            "comment": "DNS"
        }
        add_rule(rule)
        rules = get_all_rules()
        self.assertEqual(len(rules), 1)
        delete_rules([rules[0]["id"]])
        self.assertEqual(len(get_all_rules()), 0)

    @patch('subprocess.run')
    def test_apply_firewall(self, mock_run):
        rule = {
            "ip_address": "192.168.1.0",
            "subnet_mask": "255.255.255.0",
            "direction": "in",
            "protocol": "tcp",
            "port": "443",
            "action": "accept",
            "comment": ""
        }
        add_rule(rule)
        
        class MockResult:
            returncode = 0
            stdout = '{"success": true}'
            stderr = ''
        mock_run.return_value = MockResult()
        
        self.assertTrue(apply_firewall())

    @patch('subprocess.run')
    def test_apply_firewall_failure(self, mock_run):
        rule = {
            "ip_address": "192.168.1.0",
            "subnet_mask": "255.255.255.0",
            "direction": "in",
            "protocol": "tcp",
            "port": "443",
            "action": "accept",
            "comment": ""
        }
        add_rule(rule)
        
        class MockResult:
            returncode = 1
            stdout = '{"success": false, "error": "nftables error"}'
            stderr = 'nftables error'
        mock_run.return_value = MockResult()
        
        with self.assertRaisesRegex(RuntimeError, "Failed to apply firewall"):
            apply_firewall()

if __name__ == '__main__':
    unittest.main()
