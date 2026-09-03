import os
import tempfile
import unittest
from unittest import mock

import asterisk_helper


class DialplanGenerationTestCase(unittest.TestCase):
    def test_extension_codegen_writes_selected_codecs_only(self):
        data = {
            "ext": "2999",
            "enabled": 1,
            "secret": "pass",
            "name": "Codec Test",
            "callerid_number": "2999",
            "max_contacts": 3,
            "max_expiration": 120,
            "ring_time": 60,
            "record_mode": "noo",
            "vm_enabled": 0,
            "vm_password": "1234",
            "direct_media": 0,
            "nat": 0,
            "codecs": "alaw,g729,opus,badcodec",
            "followme": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(asterisk_helper, "EP_FILE", os.path.join(tmpdir, "endpoint.conf")), \
             mock.patch.object(asterisk_helper, "AUTH_FILE", os.path.join(tmpdir, "auth.conf")), \
             mock.patch.object(asterisk_helper, "AOR_FILE", os.path.join(tmpdir, "aor.conf")), \
             mock.patch.object(asterisk_helper, "DP_FILE", os.path.join(tmpdir, "extensions_gui.conf")), \
             mock.patch.object(asterisk_helper, "CTX_FILE", os.path.join(tmpdir, "context_exten.conf")), \
             mock.patch.object(asterisk_helper, "VM_FILE", os.path.join(tmpdir, "voicemail.conf")), \
             mock.patch.object(asterisk_helper, "FM_FILE", os.path.join(tmpdir, "followme.conf")), \
             mock.patch("db.get_outbound_routes", return_value=[]):
            asterisk_helper.write_extension_configs(data, reload=False)
            with open(os.path.join(tmpdir, "endpoint.conf"), "r", encoding="utf-8") as f:
                content = f.read()
        self.assertIn("allow=alaw,g729,opus", content)
        self.assertNotIn("badcodec", content)

    def test_active_call_source_uses_originating_trunk_name(self):
        trunk_rows = [{"name": "GSM", "username": "", "auth_id": "", "from_user": "", "context": "from-trunk"}]

        inbound = "\n".join([
            "PJSIP/GSM-00000001!from-trunk!23226054!1!Ring!AppDial!(Outgoing Line)!+201122385328!!PJSIP/2121-00000002!4!178!178",
            "PJSIP/2121-00000002!recording!2121!12!Ring!Dial!PJSIP/2121,60,TtHh!+201122385328!!PJSIP/GSM-00000001!4!178!179",
        ])
        with mock.patch("asterisk_helper.run_asterisk_cmd", return_value=inbound), \
             mock.patch("db.get_all_trunks", return_value=trunk_rows):
            calls = asterisk_helper.get_live_calls_list()
        self.assertEqual(calls[0]["source"], "GSM")
        self.assertEqual(calls[0]["source_type"], "trunk")
        self.assertEqual(calls[0]["duration_sec"], 0)
        self.assertEqual(calls[0]["caller"], "+201122385328")

        outbound = "\n".join([
            "PJSIP/2121-00000003!from-internal-2121!01200800770!1!Ring!Dial!PJSIP/01200800770@GSM,30,Tt!2121!!PJSIP/GSM-00000004!5!180!180",
            "PJSIP/GSM-00000004!from-internal-2121!01200800770!1!Ring!AppDial!(Outgoing Line)!2121!!PJSIP/2121-00000003!5!180!181",
        ])
        with mock.patch("asterisk_helper.run_asterisk_cmd", return_value=outbound), \
             mock.patch("db.get_all_trunks", return_value=trunk_rows):
            calls = asterisk_helper.get_live_calls_list()
        self.assertEqual(calls[0]["callee"], "01200800770")
        self.assertEqual(calls[0]["caller"], "2121")
        self.assertEqual(calls[0]["source"], "GSM")
        self.assertEqual(calls[0]["source_type"], "trunk")

    def test_active_call_enriches_inbound_ivr_queue_and_agent_names(self):
        trunk_rows = [{"name": "GSM", "username": "", "auth_id": "", "from_user": "", "context": "from-trunk"}]
        queues = [{"queue_number": "6500", "name": "Support"}]
        extensions = [{"ext": "5001", "name": "Alice"}]
        ivrs = [{
            "num": "7002",
            "name": "Main Menu",
            "mappings": [{"key": "2", "dest": "6500", "dest_type": "queue"}],
        }]

        queue_call = "\n".join([
            "PJSIP/GSM-00000001!from-trunk!7002!1!Up!Queue!6500,tT!2015550100!!Local/6500@queue-6500-00000002!4!100!100",
            "Local/6500@queue-6500-00000002!queue-6500!6500!1!Up!AppQueue!(Outgoing Line)!2015550100!!PJSIP/GSM-00000001!4!100!101",
        ])
        agent_call = "\n".join([
            "PJSIP/GSM-00000003!from-trunk!5001!1!Up!Dial!PJSIP/5001,60,Tt!2015550101!!PJSIP/5001-00000004!4!200!200",
            "PJSIP/5001-00000004!from-internal-5001!5001!1!Up!AppDial!(Outgoing Line)!2015550101!!PJSIP/GSM-00000003!4!200!201",
        ])

        def fake_cmd(cmd):
            if cmd.startswith("core show channel ") and "channels concise" not in cmd:
                return "RCM_IVR_NUM=7002\nRCM_IVR_NAME=Main Menu\nRCM_IVR_DIGIT=2\n"
            return queue_call

        with mock.patch("asterisk_helper.run_asterisk_cmd", side_effect=fake_cmd), \
             mock.patch("db.get_all_trunks", return_value=trunk_rows), \
             mock.patch("db.get_queues", return_value=queues), \
             mock.patch("db.get_all_extensions", return_value=extensions), \
             mock.patch("db.get_ivrs", return_value=ivrs):
            calls = asterisk_helper.get_live_calls_list()
        self.assertEqual(calls[0]["callee"], "Support")
        self.assertEqual(calls[0]["caller"], "2015550100")
        self.assertEqual(calls[0]["flow_type"], "queue")

        with mock.patch("asterisk_helper.run_asterisk_cmd", return_value=agent_call), \
             mock.patch("db.get_all_trunks", return_value=trunk_rows), \
             mock.patch("db.get_queues", return_value=queues), \
             mock.patch("db.get_all_extensions", return_value=extensions), \
             mock.patch("db.get_ivrs", return_value=ivrs):
            calls = asterisk_helper.get_live_calls_list()
        self.assertEqual(calls[0]["callee"], "Alice")
        self.assertEqual(calls[0]["caller"], "2015550101")
        self.assertEqual(calls[0]["flow_type"], "agent")

    def test_outbound_route_generates_transform_auth_record_limit_and_failover(self):
        route = {
            "name": "mobile",
            "context": "rcm-out-mobile",
            "enabled": True,
            "patterns": ["_9X."],
            "strip": 1,
            "prepend": "002",
            "pin": "1234",
            "record": True,
            "timeout": 45,
            "time_limit_sec": 60,
            "trunks": ["GSM", "BACKUP"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_conf = os.path.join(tmpdir, "outbound.conf")
            asterisk_helper.write_outbound_routes_dialplan([route], out_conf=out_conf)
            with open(out_conf, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("Set(RCM_DIAL=${RCM_DIAL:1})", content)
        self.assertIn("Set(RCM_DIAL=002${RCM_DIAL})", content)
        self.assertIn("Authenticate(1234)", content)
        self.assertIn("Gosub(rcm-recording,start,1)", content)
        self.assertIn("Dial(PJSIP/${RCM_DIAL}@GSM,45,TtL(60000))", content)
        self.assertIn("Dial(PJSIP/${RCM_DIAL}@BACKUP,45,TtL(60000))", content)
        self.assertLess(content.index("@GSM"), content.index("@BACKUP"))

    def test_inbound_route_generates_office_check_cid_fallback_and_trunk_aliases(self):
        office_times = [{
            "id": "morning",
            "name": "Morning",
            "enabled": 1,
            "rules": [{"day_of_week": "monday", "start_time": "08:00", "end_time": "17:00"}],
        }]
        route = {
            "id": "main",
            "name": "Main",
            "enabled": True,
            "trunks": ["GSM"],
            "did_patterns": ["23226054"],
            "cid_pattern": "_01X.",
            "priority": 1,
            "default_dest_type": "extension",
            "default_dest_val": "2121",
            "rules": [{
                "time_condition": "office",
                "office_profile": "morning",
                "dest_type": "announcement",
                "dest_val": "8001",
            }],
        }
        trunks = [{
            "name": "GSM",
            "username": "provider_ep",
            "auth_id": "",
            "from_user": "",
            "context": "from-gsm",
        }]

        mocked_file = mock.mock_open()
        with mock.patch("asterisk_helper.ensure_inbound_include"), \
             mock.patch("asterisk_helper.ensure_inbound_entry_contexts"), \
             mock.patch("asterisk_helper.run_asterisk_cmd"), \
             mock.patch("db.get_office_times", return_value=office_times), \
             mock.patch("db.get_holidays", return_value=[]), \
             mock.patch("db.get_inbound_routes", return_value=[route]), \
             mock.patch("db.get_all_trunks", return_value=trunks), \
             mock.patch("db.get_outbound_routes", return_value=[]), \
             mock.patch("builtins.open", mocked_file):
            asterisk_helper.sync_inbound_routes_dialplan()

        content = "".join(call.args[0] for call in mocked_file().write.call_args_list)
        self.assertIn("Gosub(rcm-check-office-morning,s,1)", content)
        self.assertIn('GotoIf($[ "${GOSUB_RETVAL}" = "1" ]?rule_0_dest)', content)
        self.assertIn('"${TRUNK}" != "GSM"', content)
        self.assertIn('"${TRUNK}" != "provider_ep"', content)
        self.assertIn('"${TRUNK_CTX}" != "from-gsm"', content)
        self.assertIn("[rcm-check-route-main-didonly]", content)
        self.assertIn("Goto(rcm-check-route-main-didonly-match,${DID},1)", content)
        self.assertIn("exten => 23226054,1,Set(ROUTE_MATCHED=1)", content)

    def test_ivr_generates_advanced_options_and_ultra_number(self):
        ivrs = [{
            "num": "7007",
            "name": "Main Menu",
            "prompt_id": "welcome",
            "response_timeout_prompt": "timeout_prompt",
            "invalid_input_prompt": "invalid_prompt",
            "timeout": 7,
            "digit_timeout": 4,
            "loops": 2,
            "fail_mode": "hangup",
            "fail_ext": "",
            "dial_extension": True,
            "replace_display_name": True,
            "auto_record": True,
            "mappings": [{"key": "1", "dest": "5001", "dest_type": "extension"}],
            "ultra_numbers": [{"number": "1234", "dest": "6500", "dest_type": "queue"}],
        }]

        def fake_prompt(prompt_id):
            return {
                "welcome": "rcm/media/welcome",
                "timeout_prompt": "rcm/media/timeout",
                "invalid_prompt": "rcm/media/invalid",
            }.get(prompt_id, "silence/1")

        mocked_file = mock.mock_open()
        with mock.patch("asterisk_helper.run_asterisk_cmd"), \
             mock.patch("asterisk_helper.resolve_asterisk_prompt", side_effect=fake_prompt), \
             mock.patch("builtins.open", mocked_file):
            asterisk_helper.sync_ivr_dialplan(ivrs)

        content = "".join(call.args[0] for call in mocked_file().write.call_args_list)
        self.assertIn("Set(CALLERID(name)=Main Menu)", content)
        self.assertIn("Set(TIMEOUT(digit)=4)", content)
        self.assertIn("Gosub(rcm-recording,start,1)", content)
        self.assertIn("Playback(rcm/media/invalid)", content)
        self.assertIn("Playback(rcm/media/timeout)", content)
        self.assertIn("exten => 1234,1,Set(__RCM_IVR_DIGIT=1234)", content)
        self.assertIn("Goto(queue-6500,6500,1)", content)
        self.assertIn("include => internal", content)


if __name__ == "__main__":
    unittest.main()
