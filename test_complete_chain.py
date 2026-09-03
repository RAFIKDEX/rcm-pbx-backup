import sys
import unittest

sys.path.insert(0, '/root/RCM_7021')
import app
import db
import asterisk_helper

class TestCompletePBXChain(unittest.TestCase):
    def test_database_extensions(self):
        # 1. Database Check
        exts = db.get_all_extensions()
        self.assertGreater(len(exts), 0, "No extensions found in SQLite database!")
        print(f"[OK] SQLite DB has {len(exts)} extensions configured.")

    def test_asterisk_registered_mailboxes(self):
        # 2. Voicemail check via Asterisk CLI
        res = asterisk_helper.run_asterisk_cmd("voicemail show users")
        self.assertNotIn("Error", res, "Failed to communicate with Asterisk CLI!")
        self.assertIn("default", res, "No default voicemail context found in Asterisk!")
        print("[OK] Asterisk voicemail users list retrieved successfully.")

    def test_dynamic_feature_codes_file(self):
        # 3. Feature codes file check
        import os
        fc_file = "/etc/asterisk/extensions.feature_codes.gui.conf"
        self.assertTrue(os.path.exists(fc_file), "extensions.feature_codes.gui.conf is missing!")
        with open(fc_file, "r") as f:
            content = f.read()
        self.assertIn("[rcm-feature-codes]", content)
        self.assertIn("*97", content) # Voicemail
        self.assertIn("*37", content) # DND On
        self.assertIn("*38", content) # DND Off
        self.assertIn("*55", content) # Spy
        self.assertIn("*56", content) # Whisper
        self.assertIn("*57", content) # Barge
        print("[OK] extensions.feature_codes.gui.conf is valid and populated.")

    def test_features_conf_mappings(self):
        # 4. features.conf checks
        import os
        feat_file = "/etc/asterisk/features.conf"
        self.assertTrue(os.path.exists(feat_file), "features.conf is missing!")
        with open(feat_file, "r") as f:
            content = f.read()
        self.assertIn("blindxfer => ##", content)
        self.assertIn("atxfer => *2", content)
        self.assertIn("automixmon => *1", content)
        print("[OK] features.conf DTMF transfer & recording maps are enabled.")

    def test_dialplan_parsing(self):
        # 5. Dialplan syntax check
        res = asterisk_helper.run_asterisk_cmd("dialplan show *97@rcm-feature-codes")
        self.assertNotIn("failed", res.lower(), "Context rcm-feature-codes not found in memory!")
        print("[OK] Asterisk dialplan context rcm-feature-codes is active in memory.")

if __name__ == '__main__':
    unittest.main()
