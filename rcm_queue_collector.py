import socket
import time
import sys
import os
from datetime import datetime

# Add project path
sys.path.insert(0, '/root/RCM_7021')
import rcm_queue_db

def parse_block(block):
    headers = {}
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            parts = line.split(":", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            headers[k] = v
    return headers


def event_time(headers):
    """Use Asterisk's event timestamp instead of collector processing time."""
    for key in ("EventTV", "Timestamp", "EventTimestamp"):
        value = str(headers.get(key) or "").strip().strip('"')
        if not value:
            continue
        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1_000_000.0
            return numeric
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None

def sync_queue_status(s):
    print("Requesting initial queue status...")
    cmd = "Action: QueueStatus\r\n\r\n"
    s.sendall(cmd.encode('utf-8'))
    
    # Read response blocks
    res = ""
    timeout = time.time() + 5.0
    while time.time() < timeout:
        chunk = s.recv(4096).decode('utf-8', errors='ignore')
        if not chunk:
            break
        res += chunk
        if "QueueStatusComplete" in res or "Response: Error" in res:
            break
            
    # Parse blocks
    blocks = res.split("\r\n\r\n")
    trailing = blocks.pop() if res and not res.endswith("\r\n\r\n") else ""
    for block in blocks:
        block = block.replace("\r\n", "\n")
        headers = parse_block(block)
        evt = headers.get("Event")
        if evt == "QueueMember":
            q_num = headers.get("Queue")
            interface = headers.get("Location") or headers.get("Interface")
            name = headers.get("Name", "Agent") or headers.get("MemberName", "Agent")
            paused = headers.get("Paused") # "1" or "0"
            membership = headers.get("Membership", "DYNAMIC").upper()
            status = headers.get("Status") # Status integer
            if interface:
                agent_ext = interface.split("/")[-1].split("@")[0]
                rcm_queue_db.db_agent_login(agent_ext, q_num, name, membership)
                
                # Map status code to status string
                status_map = {
                    "0": "UNKNOWN",
                    "1": "NOT IN USE",
                    "2": "IN USE",
                    "3": "BUSY",
                    "4": "UNAVAILABLE",
                    "5": "UNAVAILABLE",
                    "6": "RINGING",
                    "7": "IN USE",
                    "8": "BUSY"
                }
                status_str = status_map.get(status, "UNKNOWN")
                rcm_queue_db.db_agent_status_update(agent_ext, q_num, status_str, paused == "1")
        elif evt == "QueueEntry":
            q_num = headers.get("Queue")
            uniqueid = headers.get("Uniqueid")
            caller = headers.get("CallerIDNum")
            channel = headers.get("Channel")
            if uniqueid:
                rcm_queue_db.db_call_enter(uniqueid, uniqueid, caller, q_num, channel)

def sync_active_channels_with_asterisk(s):
    print("Running active channels sync...")
    cmd = "Action: CoreShowChannels\r\n\r\n"
    s.sendall(cmd.encode('utf-8'))
    
    # Read response until CoreShowChannelsComplete or response times out
    res = ""
    timeout = time.time() + 5.0
    s.settimeout(2.0)
    while time.time() < timeout:
        try:
            chunk = s.recv(4096).decode('utf-8', errors='ignore')
            if not chunk:
                break
            res += chunk
            if "CoreShowChannelsComplete" in res or "Response: Error" in res:
                break
        except socket.timeout:
            break
            
    # Restore standard timeout
    s.settimeout(10.0)
    
    # Parse blocks to find active uniqueids AND process any events received during sync
    active_uids = set()
    blocks = res.split("\r\n\r\n")
    for block in blocks:
        block = block.replace("\r\n", "\n")
        headers = parse_block(block)
        evt = headers.get("Event")
        if evt == "CoreShowChannel":
            uid = headers.get("Uniqueid")
            lid = headers.get("Linkedid")
            if uid:
                active_uids.add(uid)
            if lid:
                active_uids.add(lid)
        elif evt:
            handle_event(headers)
                
    print(f"[SYNC] Active uniqueids in Asterisk: {active_uids}")
    rcm_queue_db.reconcile_active_calls(active_uids)

def clean_agent_ext(raw_str):
    if not raw_str:
        return ""
    part = raw_str.split("/")[-1]
    part = part.split("@")[0]
    part = part.split(";")[0]
    if "-" in part and not part.startswith("-"):
        part = part.rsplit("-", 1)[0]
    return part.strip()

def handle_event(headers):
    evt = headers.get("Event")

    if not evt:
        return
    occurred_at = event_time(headers)
        
    if evt in ("QueueCallerJoin", "Join"):
        q_num = headers.get("Queue") or headers.get("queue") or headers.get("QueueName")
        caller = headers.get("CallerIDNum") or headers.get("CallerIDnum") or headers.get("CallerID") or headers.get("Callerid") or headers.get("CallerIDName") or "Unknown"
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        linkedid = headers.get("Linkedid", uniqueid)
        channel = headers.get("Channel") or headers.get("CallerChannel")
        position = headers.get("Position")
        if uniqueid and q_num:
            print(f"[EVENT] Caller {caller} entered queue {q_num} (UID: {uniqueid}, Pos: {position})")
            rcm_queue_db.db_call_enter(uniqueid, linkedid, caller, q_num, channel, position, occurred_at)
        
    elif evt == "AgentCalled":
        q_num = headers.get("Queue") or headers.get("queue")
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        agent_called = headers.get("AgentCalled") or headers.get("Interface") or headers.get("DestinationChannel") or headers.get("Member") or headers.get("MemberName")
        if uniqueid and agent_called:
            agent_ext = clean_agent_ext(agent_called)
            print(f"[EVENT] Queue {q_num} ringing agent {agent_ext} for call {uniqueid}")
            rcm_queue_db.db_call_ring(uniqueid, agent_ext, occurred_at)
            rcm_queue_db.db_agent_call_event(agent_ext, q_num, "RING", uniqueid, occurred_at)
            
    elif evt == "AgentConnect":
        q_num = headers.get("Queue") or headers.get("queue")
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        member = headers.get("Member") or headers.get("Interface") or headers.get("DestinationChannel") or headers.get("BridgedChannel") or headers.get("MemberName")
        if uniqueid and member:
            agent_ext = clean_agent_ext(member)
            print(f"[EVENT] Queue {q_num} call {uniqueid} answered by agent {agent_ext}")
            rcm_queue_db.db_call_answer(uniqueid, agent_ext, occurred_at)
            rcm_queue_db.db_agent_call_event(agent_ext, q_num, "ANSWER", uniqueid, occurred_at)
            
    elif evt == "QueueCallerAbandon":
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        if uniqueid:
            print(f"[EVENT] Call {uniqueid} abandoned by caller")
            rcm_queue_db.db_call_abandon(uniqueid, event_time=occurred_at)
            
    elif evt == "AgentComplete":
        q_num = headers.get("Queue") or headers.get("queue")
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        member = headers.get("Member") or headers.get("Interface") or headers.get("DestinationChannel") or headers.get("MemberName")
        reason = headers.get("Reason", "Hangup")
        if uniqueid:
            print(f"[EVENT] Queue call {uniqueid} completed. Reason: {reason}")
            rcm_queue_db.db_call_hangup(uniqueid, reason, occurred_at)
        if member and q_num:
            agent_ext = clean_agent_ext(member)
            rcm_queue_db.db_agent_call_event(agent_ext, q_num, "HANGUP", uniqueid, occurred_at)
            
    elif evt in ("Hangup", "SoftHangup"):
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        cause_txt = headers.get("Cause-txt", "Hangup")
        if uniqueid:
            rcm_queue_db.db_call_hangup(uniqueid, cause_txt, occurred_at)
            
    elif evt == "AgentDump":
        q_num = headers.get("Queue") or headers.get("queue")
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        member = headers.get("Member") or headers.get("Interface") or headers.get("DestinationChannel") or headers.get("MemberName")
        if uniqueid:
            print(f"[EVENT] Queue call {uniqueid} dumped by agent")
            rcm_queue_db.db_call_hangup(uniqueid, "AgentDump", occurred_at)
        if member and q_num:
            agent_ext = clean_agent_ext(member)
            rcm_queue_db.db_agent_call_event(agent_ext, q_num, "HANGUP", uniqueid, occurred_at)
            
    elif evt == "BridgeLeave":
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        if uniqueid:
            print(f"[EVENT] Queue call {uniqueid} left bridge (BridgeLeave)")
            rcm_queue_db.db_call_hangup(uniqueid, "BridgeLeave", occurred_at)
            
    elif evt in ("Hold", "MusicOnHoldStart"):
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        if uniqueid:
            print(f"[EVENT] Call {uniqueid} put on HOLD")
            rcm_queue_db.db_call_hold_event(uniqueid, True, occurred_at)
            
    elif evt in ("Unhold", "MusicOnHoldStop"):
        uniqueid = headers.get("Uniqueid") or headers.get("CallerUniqueid")
        if uniqueid:
            print(f"[EVENT] Call {uniqueid} taken off HOLD (UNHOLD)")
            rcm_queue_db.db_call_hold_event(uniqueid, False, occurred_at)
        
    elif evt == "QueueMemberAdded":
        q_num = headers.get("Queue") or headers.get("queue")
        interface = headers.get("Interface") or headers.get("Member")
        name = headers.get("MemberName", "Agent")
        membership = headers.get("Membership", "DYNAMIC").upper()
        if interface and q_num:
            agent_ext = clean_agent_ext(interface)
            print(f"[EVENT] Agent {agent_ext} logged into queue {q_num}")
            rcm_queue_db.db_agent_login(agent_ext, q_num, name, membership)
            
    elif evt == "QueueMemberRemoved":
        q_num = headers.get("Queue") or headers.get("queue")
        interface = headers.get("Interface") or headers.get("Member")
        if interface and q_num:
            agent_ext = clean_agent_ext(interface)
            print(f"[EVENT] Agent {agent_ext} logged out of queue {q_num}")
            rcm_queue_db.db_agent_logout(agent_ext, q_num)
            
    elif evt == "QueueMemberPause":
        q_num = headers.get("Queue") or headers.get("queue")
        interface = headers.get("Interface") or headers.get("Member")
        paused = headers.get("Paused")
        if interface and q_num:
            agent_ext = clean_agent_ext(interface)
            is_paused = (paused == "1")
            print(f"[EVENT] Agent {agent_ext} pause state: {is_paused} in queue {q_num}")
            rcm_queue_db.db_agent_pause(agent_ext, q_num, is_paused)
            
    elif evt == "QueueMemberStatus":
        q_num = headers.get("Queue") or headers.get("queue")
        interface = headers.get("Interface") or headers.get("Location") or headers.get("Member")
        status = headers.get("Status") # status integer
        paused = headers.get("Paused") # "1" or "0"
        if interface and q_num:
            agent_ext = clean_agent_ext(interface)
            is_paused = (paused == "1")
            
            # Map status code to status string
            status_map = {
                "0": "UNKNOWN",
                "1": "NOT IN USE",
                "2": "IN USE",
                "3": "BUSY",
                "4": "UNAVAILABLE",
                "5": "UNAVAILABLE",
                "6": "RINGING",
                "7": "IN USE",
                "8": "BUSY"
            }
            status_str = status_map.get(status, "UNKNOWN")
            
            # Update status
            print(f"[EVENT] Agent {agent_ext} status in queue {q_num} is {status_str} (Paused: {is_paused})")
            rcm_queue_db.db_agent_status_update(agent_ext, q_num, status_str, is_paused)

def run_collector():
    print("Starting RCM Queue Collector daemon...")
    rcm_queue_db.init_queue_db()
    try:
        rcm_queue_db.reconcile_with_asterisk_state()
    except Exception as e:
        print(f"Error during initial state reconciliation: {e}")
    
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10.0)
            s.connect(("127.0.0.1", 5038))
            print("Connected to Asterisk AMI.")
            
            # Read greeting
            greeting = s.recv(1024).decode('utf-8', errors='ignore')
            
            # Login
            login_cmd = "Action: Login\r\nUsername: guiuser\r\nSecret: admin\r\n\r\n"
            s.sendall(login_cmd.encode('utf-8'))
            
            # Read login response
            res = ""
            while "\r\n\r\n" not in res:
                chunk = s.recv(1024).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                res += chunk
            
            if "Response: Success" not in res:
                print("AMI Login failed!")
                s.close()
                time.sleep(5)
                continue
                
            print("AMI Logged in successfully.")
            
            # Sync current queue status
            buffer = sync_queue_status(s) or ""
            
            # Recon/Startup sync
            try:
                buffer = sync_active_channels_with_asterisk(s, buffer) or ""
            except Exception as e:
                print(f"Error during startup sync: {e}")
                
            # Set timeout to check periodic sync every 5 seconds
            s.settimeout(5.0)
            
            # Read loop
            last_sync_time = time.time()
            while True:
                try:
                    chunk = s.recv(4096).decode('utf-8', errors='ignore')
                    if not chunk:
                        print("AMI Connection lost. Triggering immediate native fallback state sync...")
                        try:
                            rcm_queue_db.reconcile_with_asterisk_state()
                        except Exception as sync_err:
                            print(f"Fallback state sync error: {sync_err}")
                        break
                    buffer += chunk
                    while "\r\n\r\n" in buffer:
                        block, buffer = buffer.split("\r\n\r\n", 1)
                        block = block.replace("\r\n", "\n")
                        headers = parse_block(block)
                        handle_event(headers)
                except socket.timeout:
                    pass
                
                # Check for periodic sync
                if time.time() - last_sync_time >= 30.0:
                    try:
                        sync_active_channels_with_asterisk(s)
                    except Exception as e:
                        print(f"Error in periodic sync: {e}")
                    last_sync_time = time.time()
                    
            s.close()

        except Exception as e:
            print(f"Error in collector loop: {e}. Executing immediate fallback state sync...")
            try:
                rcm_queue_db.reconcile_with_asterisk_state()
            except Exception as sync_err:
                print(f"Fallback state sync error: {sync_err}")
            time.sleep(5)

if __name__ == '__main__':
    run_collector()
