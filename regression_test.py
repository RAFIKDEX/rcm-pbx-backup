import os
import sys
import uuid
import time
import subprocess

sys.path.insert(0, '/root/RCM_7021')
import db
import asterisk_helper

def run_cmd(args):
    res = subprocess.run(args, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr

def asterisk_cli(cmd):
    return run_cmd(['asterisk', '-rx', cmd])

def test_cycle(cycle_num):
    print(f"\n--- STARTING CYCLE {cycle_num} ---")
    
    # 1. Generate unique identifiers for this cycle
    ext = f"888{cycle_num % 10}"
    queue_num = f"880{cycle_num % 10}"
    ivr_num = f"881{cycle_num % 10}"
    ann_num = f"882{cycle_num % 10}"
    trunk_name = f"TTRUNK_{cycle_num}"
    route_id = f"R_{cycle_num}"
    out_route_name = f"OUT_{cycle_num}"
    
    print(f"Entities: Ext={ext}, Queue={queue_num}, IVR={ivr_num}, Ann={ann_num}, Trunk={trunk_name}")
    
    # 2. Setup database entities
    # Create Extension
    ext_data = {
        "ext": ext,
        "enabled": 1,
        "name": f"Test Ext {cycle_num}",
        "secret": "Pass1234!",
        "callerid_number": ext,
        "max_contacts": 3,
        "max_expiration": 120,
        "ring_time": 30,
        "vm_enabled": 0,
        "vm_password": "1234",
        "record_mode": "noo",
        "direct_media": 0,
        "nat": 0,
        "followme": [],
        "mobile": ""
    }
    db.add_extension(ext_data)
    asterisk_helper.write_extension_configs(ext_data)
    
    # Create Trunk
    trunk_data = {
        "name": trunk_name,
        "enabled": 1,
        "type": "pjsip",
        "register_mode": "none",
        "server_addr": "127.0.0.1",
        "server_port": 5060,
        "keepalive": 60,
        "transport": "transport-udp",
        "outproxy_addr": "",
        "outproxy_port": 5060,
        "username": f"user_{cycle_num}",
        "password": "pass",
        "auth_id": f"auth_{cycle_num}",
        "from_user": f"user_{cycle_num}",
        "from_domain": "127.0.0.1",
        "identify_by": "username"
    }
    db.add_trunk(trunk_data)
    asterisk_helper.write_trunk_configs(trunk_data)
    
    # Create Announcement (referencing the prompt if present)
    anns = db.get_announcements()
    new_ann = {
        "num": ann_num,
        "name": f"Ann_{cycle_num}",
        "prompt_id": "prompt_1",
        "destination_type": "extension",
        "destination_value": ext
    }
    anns.append(new_ann)
    db.save_announcements(anns)
    asterisk_helper.sync_announcement_dialplan(anns)
    
    # Create Queue (with static agent referencing the extension, and failover to announcement)
    queues = db.get_queues()
    new_queue = {
        "queue_number": queue_num,
        "name": f"Queue_{cycle_num}",
        "strategy": "ringall",
        "music_on_hold": "default",
        "static_agents": [ext],
        "destination_type": "announcement",
        "destination_value": ann_num
    }
    queues.append(new_queue)
    db.save_queues(queues)
    asterisk_helper.sync_queue_dialplan(queues)
    
    # Create IVR (with failover to queue, mapping 1 to extension)
    ivrs = db.get_ivrs()
    new_ivr = {
        "num": ivr_num,
        "name": f"IVR_{cycle_num}",
        "prompt_id": "prompt_1",
        "timeout": 10,
        "loops": 3,
        "fail_mode": "queue",
        "fail_ext": queue_num,
        "mappings": [
            {"digit": "1", "dest_type": "extension", "dest_val": ext}
        ]
    }
    ivrs.append(new_ivr)
    db.save_ivrs(ivrs)
    asterisk_helper.sync_ivr_dialplan(ivrs)
    
    # Create Inbound Route (trunk to IVR)
    inbound_routes = db.get_inbound_routes()
    new_inbound = {
        "id": route_id,
        "name": f"Inbound_{cycle_num}",
        "enabled": True,
        "trunks": [trunk_name],
        "did_patterns": [f"999{cycle_num}"],
        "cid_pattern": "",
        "auto_record": False,
        "enable_dial_trunk": False,
        "default_dest_type": "ivr",
        "default_dest_val": ivr_num,
        "rules": [],
        "priority": len(inbound_routes) + 1
    }
    inbound_routes.append(new_inbound)
    db.save_inbound_routes(inbound_routes)
    asterisk_helper.sync_inbound_routes_dialplan()
    
    # Create Outbound Route (referencing the trunk)
    outbound_routes = db.get_outbound_routes()
    new_outbound = {
        "name": out_route_name,
        "description": f"Outbound_{cycle_num}",
        "prefix": "9",
        "match_pattern": "X.",
        "strip": 1,
        "prepend": "",
        "pin": "",
        "record": False,
        "timeout": 30,
        "time_limit_sec": 0,
        "trunks": [trunk_name],
        "permission_type": "whitelist",
        "allowed_extensions": [ext],
        "allowed_ring_groups": []
    }
    outbound_routes.append(new_outbound)
    db.save_outbound_routes(outbound_routes)
    asterisk_helper.sync_outbound_routes(outbound_routes)
    
    # 3. Reload Asterisk
    print("Reloading Asterisk configuration...")
    code1, out1, err1 = asterisk_cli("pjsip reload")
    code2, out2, err2 = asterisk_cli("dialplan reload")
    code3, out3, err3 = asterisk_cli("queue reload")
    
    if code1 != 0 or code2 != 0 or code3 != 0:
        print(f"Asterisk reload FAILED! code1={code1}, code2={code2}, code3={code3}")
        return False
        
    # 4. Verify Dialplan in Asterisk
    print("Verifying loaded dialplan paths in Asterisk...")
    # Verify extension
    code, out, _ = asterisk_cli(f"dialplan show {ext}@internal")
    if f"Goto(dexter," not in out:
        print(f"Extension {ext} dialplan verification FAILED!\nOutput: {out}")
        return False
        
    # Verify IVR
    code, out, _ = asterisk_cli(f"dialplan show {ivr_num}@internal")
    if f"Goto(ivr-{ivr_num}" not in out:
        print(f"IVR {ivr_num} dialplan verification FAILED!\nOutput: {out}")
        return False
        
    # Verify Queue
    code, out, _ = asterisk_cli(f"dialplan show {queue_num}@internal")
    if f"Goto(queue-{queue_num}" not in out:
        print(f"Queue {queue_num} dialplan verification FAILED!\nOutput: {out}")
        return False

    # Verify Announcement
    code, out, _ = asterisk_cli(f"dialplan show {ann_num}@internal")
    if f"Goto(ann-{ann_num}" not in out:
        print(f"Announcement {ann_num} dialplan verification FAILED!\nOutput: {out}")
        return False
        
    # 5. Verify reference checking / deletion prevention logic
    print("Verifying deletion prevention validation...")
    import app
    
    # Try deleting the extension (should fail because queue static agents and ivr mappings reference it)
    in_use_ext, reason_ext = app.check_destination_in_use("extension", ext)
    if not in_use_ext:
        print("Reference Check FAILED: Extension allowed deletion while in use by queue/ivr!")
        return False
    else:
        print(f"Reference Check SUCCESS: Extension deletion prevented. Reason: {reason_ext}")
        
    # Try deleting Trunk (should fail because outbound and inbound routes reference it)
    in_use_trunk, reason_trunk = app.check_trunk_in_use(trunk_name)
    if not in_use_trunk:
        print("Reference Check FAILED: Trunk allowed deletion while in use by outbound/inbound routes!")
        return False
    else:
        print(f"Reference Check SUCCESS: Trunk deletion prevented. Reason: {reason_trunk}")
        
    # Try deleting IVR (should fail because inbound route references it)
    in_use_ivr, reason_ivr = app.check_destination_in_use("ivr", ivr_num)
    if not in_use_ivr:
        print("Reference Check FAILED: IVR allowed deletion while in use by inbound route!")
        return False
    else:
        print(f"Reference Check SUCCESS: IVR deletion prevented. Reason: {reason_ivr}")
        
    # Try deleting Announcement (should fail because queue references it)
    in_use_ann, reason_ann = app.check_destination_in_use("announcement", ann_num)
    if not in_use_ann:
        print("Reference Check FAILED: Announcement allowed deletion while in use by queue!")
        return False
    else:
        print(f"Reference Check SUCCESS: Announcement deletion prevented. Reason: {reason_ann}")
        
    # Try deleting Queue (should fail because IVR references it)
    in_use_queue, reason_queue = app.check_destination_in_use("queue", queue_num)
    if not in_use_queue:
        print("Reference Check FAILED: Queue allowed deletion while in use by IVR!")
        return False
    else:
        print(f"Reference Check SUCCESS: Queue deletion prevented. Reason: {reason_queue}")

    # 6. Clean up / Remove config
    print("Cleaning up entities...")
    # Delete outbound route
    routes = db.get_outbound_routes()
    routes = [r for r in routes if r.get('name') != out_route_name]
    db.save_outbound_routes(routes)
    asterisk_helper.sync_outbound_routes(routes)
    
    # Delete inbound route
    inbound_routes = db.get_inbound_routes()
    inbound_routes = [r for r in inbound_routes if r.get('id') != route_id]
    db.save_inbound_routes(inbound_routes)
    asterisk_helper.sync_inbound_routes_dialplan()
    
    # Delete IVR
    ivrs = db.get_ivrs()
    ivrs = [i for i in ivrs if i.get('num') != ivr_num]
    db.save_ivrs(ivrs)
    asterisk_helper.sync_ivr_dialplan(ivrs)
    
    # Delete Queue
    queues = db.get_queues()
    queues = [q for q in queues if q.get('queue_number') != queue_num]
    db.save_queues(queues)
    asterisk_helper.sync_queue_dialplan(queues)
    
    # Delete Announcement
    anns = db.get_announcements()
    anns = [a for a in anns if a.get('num') != ann_num]
    db.save_announcements(anns)
    asterisk_helper.sync_announcement_dialplan(anns)
    
    # Delete Trunk
    db.delete_trunk(trunk_name)
    asterisk_helper.delete_trunk_configs(trunk_name)
    
    # Delete Extension
    db.delete_extension(ext)
    asterisk_helper.delete_extension_configs(ext)
    
    # Reload Asterisk again
    asterisk_cli("pjsip reload")
    asterisk_cli("dialplan reload")
    asterisk_cli("queue reload")
    
    # Verify cleanup in Asterisk
    code, out, _ = asterisk_cli(f"dialplan show {ext}@internal")
    if f"Goto(dexter," in out:
        print(f"Extension cleanup verification FAILED! Destination route still exists.\nOutput: {out}")
        return False
        
    print(f"--- CYCLE {cycle_num} COMPLETED SUCCESSFULLY ---")
    return True

def main():
    success_count = 0
    total_cycles = 20
    for i in range(1, total_cycles + 1):
        try:
            res = test_cycle(i)
            if res:
                success_count += 1
            else:
                print(f"Test cycle {i} failed!")
                sys.exit(1)
        except Exception as e:
            print(f"Exception in cycle {i}: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
    print(f"\n==========================================")
    print(f"REGRESSION TEST PASSED: {success_count}/{total_cycles} cycles successful!")
    print(f"==========================================")

if __name__ == "__main__":
    main()
