import sqlite3
import os
import re
import threading
import json
import hashlib
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
    PBX_TIMEZONE = ZoneInfo("Africa/Cairo")
except Exception:
    PBX_TIMEZONE = datetime.now().astimezone().tzinfo

DB_PATH = "/root/RCM_7021/rcm_queue.db"
_QUEUE_LOG_SYNC_LOCK = threading.RLock()


def _coerce_event_datetime(value):
    """Normalize an AMI/QueueLog event time to the local naive DB format."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        epoch = float(raw)
        if epoch > 10_000_000_000:
            epoch /= 1_000_000.0
        return datetime.fromtimestamp(epoch, PBX_TIMEZONE).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    raw = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _event_time_string(value=None):
    return (_coerce_event_datetime(value) or datetime.now(PBX_TIMEZONE).replace(tzinfo=None)).strftime("%Y-%m-%d %H:%M:%S")


def _local_epoch(value):
    return int(value.replace(tzinfo=PBX_TIMEZONE).timestamp())


def _local_datetime_from_epoch(value):
    return datetime.fromtimestamp(float(value), PBX_TIMEZONE).replace(tzinfo=None)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        os.chmod(DB_PATH, 0o666)
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_queue_recording(row):
    """Resolve a queue recording when the collector did not persist its path."""
    stored = str(row["recording_path"] or "").strip() if "recording_path" in row.keys() else ""
    if stored:
        return stored
    try:
        import db
        # The CDR can already contain the authoritative recording even when
        # QueueLog did not carry a filename.  Prefer an exact linked-id match
        # before the looser legacy filename matcher; this is especially
        # important for names such as 555-2121-*.wav where the queue/agent is
        # not present in the filename.
        cdr_rows = _queue_cdr_rows(row)
        monitor_dir = getattr(db, "MONITOR_RECORDING_DIR", "/var/spool/asterisk/monitor")
        for cdr_row in cdr_rows:
            recording = str(cdr_row["recording"] or "").strip()
            if not recording:
                continue
            candidate = os.path.join(monitor_dir, os.path.basename(recording))
            try:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 44:
                    return os.path.basename(recording)
            except OSError:
                continue
        return db.find_recording_for_cdr(
            src=row["caller_number"],
            dst=row["queue_id"],
            uniqueid=row["uniqueid"],
            duration=int(row["wait_time"] or 0) + int(row["talk_time"] or 0),
            billsec=int(row["talk_time"] or 0),
            start_time=row["entry_time"] or "",
            end_time=row["hangup_time"] or "",
            extra_parties=(row["agent"],) if row["agent"] else (),
        )
    except Exception:
        return ""


def _queue_cdr_rows(row):
    """Return CDR legs linked to a queue call, if the CDR store is present."""
    try:
        import db
        uniqueid = str(row["uniqueid"] or "").strip()
        linkedid = str(row["linkedid"] or uniqueid).strip()
        if not uniqueid and not linkedid:
            return []
        conn = db.get_db()
        rows = conn.execute(
            """
            SELECT uniqueid, linkedid, dst, dstchannel, dcontext, lastapp,
                   status, billsec, recording, answer_time, end_time
            FROM cdr_records
            WHERE uniqueid IN (?, ?) OR linkedid IN (?, ?)
            ORDER BY start_time ASC, uniqueid ASC
            """,
            (uniqueid, linkedid, uniqueid, linkedid),
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _queue_cdr_leg_is_meaningful_answered(cdr_row):
    """Identify an answered destination leg without trusting context alone."""
    if str(cdr_row["status"] or "").strip().upper().replace("_", " ") != "ANSWERED":
        return False
    app_name = str(cdr_row["lastapp"] or "").strip().lower()
    if app_name in {"answer", "background", "back-ground", "wait", "playback", "hangup"}:
        return False
    return bool(
        app_name in {"dial", "appdial", "local", "bridge", "queue"}
        or str(cdr_row["dstchannel"] or "").strip()
    )


def _resolve_queue_talk_time(row):
    """Use CDR billsec as a safe fallback when QueueLog stored zero talk time."""
    current = max(0, int(row["talk_time"] or 0)) if "talk_time" in row.keys() else 0
    if current or str(row["status"] or "").strip().upper() != "ANSWERED":
        return current
    cdr_rows = _queue_cdr_rows(row)
    meaningful = [
        max(0, int(cdr_row["billsec"] or 0))
        for cdr_row in cdr_rows
        if _queue_cdr_leg_is_meaningful_answered(cdr_row)
    ]
    return max([current] + meaningful)

def init_queue_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. queues
    c.execute("""
    CREATE TABLE IF NOT EXISTS queues (
        queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        queue_number TEXT UNIQUE,
        queue_name TEXT,
        strategy TEXT,
        max_members INTEGER,
        timeout INTEGER,
        retry INTEGER,
        servicelevel INTEGER DEFAULT 30,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 2. queue_calls
    c.execute("""
    CREATE TABLE IF NOT EXISTS queue_calls (
        call_id INTEGER PRIMARY KEY AUTOINCREMENT,
        uniqueid TEXT UNIQUE,
        linkedid TEXT,
        caller_number TEXT,
        queue_id TEXT,
        queue_name TEXT,
        agent TEXT,
        entry_time TIMESTAMP,
        answer_time TIMESTAMP,
        hangup_time TIMESTAMP,
        status TEXT,
        wait_time INTEGER DEFAULT 0,
        talk_time INTEGER DEFAULT 0,
        hold_time INTEGER DEFAULT 0,
        hangup_reason TEXT,
        recording_path TEXT,
        source_trunk TEXT,
        position INTEGER DEFAULT 0,
        hangup_by TEXT,
        initial_position INTEGER DEFAULT 0,
        last_position INTEGER DEFAULT 0
    )
    """)
    
    # Run Migrations for existing database
    try:
        c.execute("ALTER TABLE queue_calls ADD COLUMN source_trunk TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE queue_calls ADD COLUMN position INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE queue_calls ADD COLUMN hangup_by TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE queue_calls ADD COLUMN initial_position INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE queue_calls ADD COLUMN last_position INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE queues ADD COLUMN servicelevel INTEGER DEFAULT 30")
    except sqlite3.OperationalError:
        pass

    # New Table: queue_call_positions
    c.execute("""
    CREATE TABLE IF NOT EXISTS queue_call_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uniqueid TEXT,
        queue TEXT,
        position INTEGER,
        event TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. queue_agents
    c.execute("""
    CREATE TABLE IF NOT EXISTS queue_agents (
        agent_id INTEGER PRIMARY KEY AUTOINCREMENT,
        extension TEXT,
        agent_name TEXT,
        queue_id TEXT,
        type TEXT,
        status TEXT,
        login_time TIMESTAMP,
        logout_time TIMESTAMP,
        UNIQUE(extension, queue_id)
    )
    """)
    
    # 4. queue_agent_events
    c.execute("""
    CREATE TABLE IF NOT EXISTS queue_agent_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT,
        queue TEXT,
        event_type TEXT,
        uniqueid TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        transfer_type TEXT
    )
    """)

    try:
        c.execute("ALTER TABLE queue_agent_events ADD COLUMN transfer_type TEXT")
    except sqlite3.OperationalError:
        pass
    
    # 5. queue_live
    c.execute("""
    CREATE TABLE IF NOT EXISTS queue_live (
        call_id TEXT PRIMARY KEY,
        queue TEXT,
        caller TEXT,
        position INTEGER,
        state TEXT,
        agent TEXT,
        start_time TIMESTAMP,
        last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Create Indexes for Optimization
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcalls_entry ON queue_calls(entry_time)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcalls_qid ON queue_calls(queue_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcalls_agent ON queue_calls(agent)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcalls_status ON queue_calls(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcalls_uniq ON queue_calls(uniqueid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcp_uniq ON queue_call_positions(uniqueid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcp_queue ON queue_call_positions(queue)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qcp_event ON queue_call_positions(event)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qevents_agent ON queue_agent_events(agent)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qevents_queue ON queue_agent_events(queue)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qevents_type ON queue_agent_events(event_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qevents_ts ON queue_agent_events(timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_qevents_uniq ON queue_agent_events(uniqueid)")
    # Clear stale dynamic agents
    c.execute("UPDATE queue_agents SET status = 'OFFLINE' WHERE type = 'DYNAMIC'")
    
    conn.commit()
    conn.close()

def db_reindex_queue_positions(queue_num):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
    SELECT call_id FROM queue_live 
    WHERE queue = ? AND state IN ('WAITING', 'RINGING')
    ORDER BY start_time ASC
    """, (queue_num,))
    rows = c.fetchall()
    for idx, row in enumerate(rows):
        new_pos = idx + 1
        c.execute("UPDATE queue_live SET position = ? WHERE call_id = ?", (new_pos, row["call_id"]))
    conn.commit()
    conn.close()

def db_record_event_position(uniqueid, event, queue=None, position=None, timestamp=None):
    if not timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    c = conn.cursor()
    
    # Try to find queue and current position from queue_live if not provided
    if not queue or position is None:
        c.execute("SELECT queue, position FROM queue_live WHERE call_id = ?", (uniqueid,))
        row = c.fetchone()
        if row:
            if not queue:
                queue = row["queue"]
            if position is None:
                position = row["position"]
                
    if not queue:
        # Fallback to queue_calls
        c.execute("SELECT queue_id, position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
        row = c.fetchone()
        if row:
            queue = row["queue_id"]
            if position is None:
                position = row["position"]
                
    if position is None:
        position = 1 # Fallback default
        
    # Update last_position in queue_calls
    c.execute("UPDATE queue_calls SET last_position = ? WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)", (position, uniqueid))
    
    # Also update initial_position if it's 0/null and event is ENTERQUEUE
    if event == 'ENTERQUEUE':
        c.execute("UPDATE queue_calls SET initial_position = ? WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1) AND (initial_position IS NULL OR initial_position = 0)", (position, uniqueid))
        
    # Insert into queue_call_positions
    c.execute("""
    INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
    VALUES (?, ?, ?, ?, ?)
    """, (uniqueid, queue, position, event, timestamp))
    
    conn.commit()
    conn.close()

# Database Writers for Asterisk Integration
def db_sync_queue(queue_num, name, strategy, max_members, timeout, retry, servicelevel=30):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO queues (queue_number, queue_name, strategy, max_members, timeout, retry, servicelevel, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(queue_number) DO UPDATE SET
        queue_name=excluded.queue_name,
        strategy=excluded.strategy,
        max_members=excluded.max_members,
        timeout=excluded.timeout,
        retry=excluded.retry,
        servicelevel=excluded.servicelevel,
        updated_at=CURRENT_TIMESTAMP
    """, (queue_num, name, strategy, max_members, timeout, retry, servicelevel))
    conn.commit()
    conn.close()

def db_call_enter(uniqueid, linkedid, caller, queue_num, channel=None, position=None, event_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = _event_time_string(event_time)
    
    # Extract source trunk from channel name if present
    source_trunk = "Trunk-SIP-Main"
    if channel:
        try:
            parts = channel.split('/')
            if len(parts) > 1:
                trunk_part = parts[1]
                if '-' in trunk_part:
                    source_trunk = trunk_part.rsplit('-', 1)[0]
                else:
                    source_trunk = trunk_part
        except Exception:
            pass

    # Query queue name
    c.execute("SELECT queue_name FROM queues WHERE queue_number = ?", (queue_num,))
    row = c.fetchone()
    q_name = row["queue_name"] if row else queue_num
    
    # Find position
    if position is None:
        c.execute("SELECT COUNT(*) FROM queue_live WHERE queue = ?", (queue_num,))
        active_count = c.fetchone()[0]
        pos = active_count + 1
    else:
        pos = int(position)

    c.execute("""
    INSERT INTO queue_calls (uniqueid, linkedid, caller_number, queue_id, queue_name, entry_time, status, source_trunk, position, initial_position, last_position)
    VALUES (?, ?, ?, ?, ?, ?, 'ENTERED', ?, ?, ?, ?)
    ON CONFLICT(uniqueid, queue_id) DO UPDATE SET
        caller_number=excluded.caller_number,
        entry_time=excluded.entry_time,
        status=CASE WHEN queue_calls.status IN ('ANSWERED', 'ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT') THEN queue_calls.status ELSE 'ENTERED' END,
        source_trunk=excluded.source_trunk,
        position=excluded.position,
        initial_position=excluded.initial_position,
        last_position=excluded.last_position
    """, (uniqueid, linkedid, caller, queue_num, q_name, now_str, source_trunk, pos, pos, pos))
    
    c.execute("""
    INSERT INTO queue_live (call_id, queue, caller, position, state, start_time)
    VALUES (?, ?, ?, ?, 'WAITING', ?)
    ON CONFLICT(call_id) DO UPDATE SET
        state='WAITING',
        caller=excluded.caller,
        position=excluded.position,
        start_time=excluded.start_time,
        last_update=CURRENT_TIMESTAMP
    """, (uniqueid, queue_num, caller, pos, now_str))
    
    # Write event for timeline
    c.execute("""
    INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
    VALUES (?, ?, 'ENTERQUEUE', ?, ?)
    """, (caller, queue_num, uniqueid, now_str))
    
    conn.commit()
    conn.close()
    
    # Record event position
    db_record_event_position(uniqueid, 'ENTERQUEUE', queue=queue_num, position=pos, timestamp=now_str)

def db_call_ring(uniqueid, agent_ext, event_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = _event_time_string(event_time)
    c.execute("SELECT queue_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
    row = c.fetchone()
    qnum = row["queue_id"] if row else ""
    c.execute("""
        UPDATE queue_calls
        SET status = CASE WHEN status IN ('ANSWERED', 'ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT') THEN status ELSE 'RINGING' END,
            agent = CASE WHEN status = 'ANSWERED' THEN agent ELSE ? END
        WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
    """, (agent_ext, uniqueid))
    c.execute("""
    UPDATE queue_live SET 
        state = 'RINGING', 
        agent = ?, 
        last_update = CURRENT_TIMESTAMP 
    WHERE call_id = ?
    """, (agent_ext, uniqueid))
    c.execute("""
    INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
    VALUES (?, ?, 'RING', ?, ?)
    """, (agent_ext, qnum, uniqueid, now_str))
    conn.commit()
    conn.close()

def db_call_answer(uniqueid, agent_ext, event_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    now_dt = _coerce_event_datetime(event_time) or datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("SELECT entry_time, queue_id, position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
    row = c.fetchone()
    wait_time = 0
    qnum = ""
    orig_pos = 0
    if row:
        qnum = row["queue_id"]
        orig_pos = row["position"]
        if row["entry_time"]:
            try:
                entry_dt = datetime.strptime(row["entry_time"], "%Y-%m-%d %H:%M:%S")
                # Fix: prevent negative wait_time due to clock sync/drifts
                wait_time = max(0, int((now_dt - entry_dt).total_seconds()))
            except Exception:
                pass
                
    # Query current position in queue_live
    c.execute("SELECT position FROM queue_live WHERE call_id = ?", (uniqueid,))
    lrow = c.fetchone()
    position = lrow["position"] if lrow else (orig_pos or 1)
    
    c.execute("""
    UPDATE queue_calls SET 
        answer_time = ?, 
        status = 'ANSWERED',
        agent = ?,
        wait_time = ?,
        last_position = ?
    WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
    """, (now_str, agent_ext, wait_time, position, uniqueid))
    
    # Keep answered calls visible on the live wallboard until the real hangup event.
    c.execute("""
    UPDATE queue_live SET
        state = 'TALKING',
        agent = ?,
        position = 0,
        last_update = CURRENT_TIMESTAMP
    WHERE call_id = ?
    """, (agent_ext, uniqueid))
    
    conn.commit()
    conn.close()
    
    # Reindex remaining calls in this queue
    if qnum:
        db_reindex_queue_positions(qnum)
        
    # Record event CONNECT/ANSWER
    db_record_event_position(uniqueid, 'CONNECT', queue=qnum, position=position, timestamp=now_str)

def db_call_abandon(uniqueid, position=None, event_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    now_dt = _coerce_event_datetime(event_time) or datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("SELECT entry_time, caller_number, queue_id, position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
    row = c.fetchone()
    wait_time = 0
    caller = ""
    qnum = ""
    orig_pos = 0
    if row:
        caller = row["caller_number"]
        qnum = row["queue_id"]
        orig_pos = row["position"]
        if row["entry_time"]:
            try:
                entry_dt = datetime.strptime(row["entry_time"], "%Y-%m-%d %H:%M:%S")
                # Fix: prevent negative wait_time due to clock sync/drifts
                wait_time = max(0, int((now_dt - entry_dt).total_seconds()))
            except Exception:
                pass
                
    # If position is not passed, query it from queue_live before deleting
    if position is None:
        c.execute("SELECT position FROM queue_live WHERE call_id = ?", (uniqueid,))
        lrow = c.fetchone()
        if lrow:
            position = lrow["position"]
        else:
            position = orig_pos or 1
            
    c.execute("""
    UPDATE queue_calls SET 
        hangup_time = ?, 
        status = 'ABANDONED',
        wait_time = ?,
        hangup_by = 'CALLER',
        last_position = ?
    WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
    """, (now_str, wait_time, position, uniqueid))
    
    # Store event
    c.execute("DELETE FROM queue_live WHERE call_id = ?", (uniqueid,))
    
    # Write abandon event for timeline
    c.execute("""
    INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
    VALUES (?, ?, 'ABANDON', ?, ?)
    """, (caller, qnum, uniqueid, now_str))
    
    conn.commit()
    conn.close()
    
    # Reindex remaining calls in this queue
    if qnum:
        db_reindex_queue_positions(qnum)
        
    # Record the position event in queue_call_positions
    db_record_event_position(uniqueid, 'ABANDON', queue=qnum, position=position, timestamp=now_str)

def db_call_hangup(uniqueid, reason="Hangup", event_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    event_dt = _coerce_event_datetime(event_time) or datetime.now()
    now_str = event_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("SELECT entry_time, answer_time, status, caller_number, queue_id, agent, hangup_by, position, last_position, talk_time, hangup_time FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
    row = c.fetchone()
    
    qnum = None
    if row:
        status = row["status"]
        entry_time = row["entry_time"]
        answer_time = row["answer_time"]
        caller = row["caller_number"]
        qnum = row["queue_id"]
        agent = row["agent"]
        existing_hangup_by = row["hangup_by"]
        orig_pos = row["position"]
        last_pos = row["last_position"]
        existing_talk_time = row["talk_time"]
        existing_hangup_time = row["hangup_time"]
        
        # If already in a final state and has a hangup time, avoid recalculation but clean up live states
        if status in ('ANSWERED', 'ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT') and existing_hangup_time:
            if agent:
                c.execute("UPDATE queue_agents SET status = 'AVAILABLE' WHERE extension = ? AND queue_id = ? AND status IN ('BUSY', 'IN USE')", (agent, qnum))
            c.execute("DELETE FROM queue_live WHERE call_id = ?", (uniqueid,))
            conn.commit()
            conn.close()
            if qnum:
                db_reindex_queue_positions(qnum)
            return
            
        # Calculate times
        wait_time = 0
        talk_time = 0
        
        # Retrieve existing wait_time and talk_time to preserve if needed during reconciliation
        c.execute("SELECT wait_time, talk_time FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
        existing_row = c.fetchone()
        existing_wait = existing_row["wait_time"] if existing_row else None
        existing_talk = existing_row["talk_time"] if existing_row else None
        
        if entry_time:
            try:
                entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                # Fix: Check for general reconciliation reason to prevent fake huge values
                if reason == "Ghost Call Auto-Reconciliation" or (reason and "reconciliation" in reason.lower()):
                    # Preserve existing wait_time if valid
                    wait_time = existing_wait if (existing_wait is not None and existing_wait > 0) else 0
                    talk_time = 0
                else:
                    if answer_time:
                        ans_dt = datetime.strptime(answer_time, "%Y-%m-%d %H:%M:%S")
                        wait_time = max(0, int((ans_dt - entry_dt).total_seconds()))
                        talk_time = max(0, int((event_dt - ans_dt).total_seconds()))
                        # Prevent fake huge talk_time values
                        if talk_time > 43200: # 12 hours
                            talk_time = 0
                    else:
                        wait_time = max(0, int((event_dt - entry_dt).total_seconds()))
                        # Prevent fake huge wait_time values
                        if wait_time > 43200:
                            wait_time = 0
            except Exception:
                pass
                
        # Fix: Calculate hold time if call was left on hold at the time of hangup
        c.execute("""
            SELECT event_type, timestamp FROM queue_agent_events
            WHERE uniqueid = ? AND event_type IN ('HOLD', 'UNHOLD')
            ORDER BY timestamp DESC LIMIT 1
        """, (uniqueid,))
        last_hold_evt = c.fetchone()
        if last_hold_evt and last_hold_evt["event_type"] == "HOLD":
            try:
                hold_dt = datetime.strptime(last_hold_evt["timestamp"], "%Y-%m-%d %H:%M:%S")
                hang_dt = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S")
                hold_dur = max(0, int((hang_dt - hold_dt).total_seconds()))
                if hold_dur > 0:
                    c.execute("""
                        UPDATE queue_calls 
                        SET hold_time = COALESCE(hold_time, 0) + ? 
                        WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
                    """, (hold_dur, uniqueid))
            except Exception:
                pass
                
        # Resolve status
        if status in ('ANSWERED', 'ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT'):
            new_status = status
        else:
            if answer_time or status == 'ANSWERED':
                new_status = 'ANSWERED'
            else:
                r_upper = (reason or "").upper()
                if "CANCEL" in r_upper:
                    new_status = 'CANCELLED'
                elif "NO ANSWER" in r_upper or "RINGNOANSWER" in r_upper:
                    new_status = 'NO ANSWER'
                elif "TIMEOUT" in r_upper:
                    new_status = 'TIMEOUT'
                else:
                    new_status = 'ABANDONED'
                
        # Resolve hangup_by
        if existing_hangup_by and existing_hangup_by.upper() in ("CALLER", "AGENT"):
            new_hangup_by = existing_hangup_by.upper()
        else:
            r = (reason or "").upper()
            if "CALLER" in r or r == "CALLER":
                new_hangup_by = "CALLER"
            elif "AGENT" in r or r == "AGENT" or "COMPLETEAGENT" in r or "DUMP" in r:
                new_hangup_by = "AGENT"
            else:
                if new_status == 'ANSWERED':
                    new_hangup_by = "AGENT"
                else:
                    new_hangup_by = "CALLER"
                    
        # Find position
        c.execute("SELECT position FROM queue_live WHERE call_id = ?", (uniqueid,))
        lrow = c.fetchone()
        position = lrow["position"] if lrow else (last_pos or orig_pos or 1)
        
        c.execute("""
        UPDATE queue_calls SET 
            hangup_time = ?, 
            status = ?,
            wait_time = ?,
            talk_time = ?,
            hangup_reason = ?,
            hangup_by = ?,
            last_position = ?
        WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
        """, (now_str, new_status, wait_time, talk_time, reason, new_hangup_by, position, uniqueid))
        
        # Write agent events
        if agent:
            # Check if event already exists
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE uniqueid = ? AND event_type = 'COMPLETE'", (uniqueid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'COMPLETE', ?, ?)
                """, (agent, qnum, uniqueid, now_str))
            # Revert agent status to AVAILABLE
            c.execute("UPDATE queue_agents SET status = 'AVAILABLE' WHERE extension = ? AND queue_id = ? AND status IN ('BUSY', 'IN USE')", (agent, qnum))

        else:
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE uniqueid = ? AND event_type = 'ABANDON'", (uniqueid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'ABANDON', ?, ?)
                """, (caller, qnum, uniqueid, now_str))
                
    # Delete from queue_live on hangup
    c.execute("DELETE FROM queue_live WHERE call_id = ?", (uniqueid,))
    conn.commit()
    conn.close()
    
    # Reindex remaining calls in this queue
    if qnum:
        db_reindex_queue_positions(qnum)

def _clean_agent_ext(agent):
    agent = str(agent or "").strip()
    if "/" in agent:
        agent = agent.split("/")[-1]
    agent = agent.split("@")[0]
    if "-" in agent:
        agent = agent.split("-")[0]
    return agent

def _resolve_agent_display_name(agent_ext, agent_name=None):
    ext = _clean_agent_ext(agent_ext)
    raw_name = str(agent_name or "").strip()
    generic_names = {"", "agent", ext.lower(), f"pjsip/{ext}".lower(), f"sip/{ext}".lower()}

    if raw_name and raw_name.lower() not in generic_names and "/" not in raw_name:
        return raw_name

    try:
        import db
        for extension in db.get_all_extensions():
            if str(extension.get("ext")) == ext:
                return extension.get("name") or ext
    except Exception:
        pass

    return ext

def db_agent_login(agent_ext, queue_num, agent_name="Agent", member_type="DYNAMIC"):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    agent_ext = _clean_agent_ext(agent_ext)
    agent_name = _resolve_agent_display_name(agent_ext, agent_name)
    
    # Fix: Prevent duplicate login events
    c.execute("SELECT status FROM queue_agents WHERE extension = ? AND queue_id = ?", (agent_ext, queue_num))
    row = c.fetchone()
    current_status = row["status"] if row else None
    
    c.execute("""
    INSERT INTO queue_agents (extension, agent_name, queue_id, type, status, login_time)
    VALUES (?, ?, ?, ?, 'AVAILABLE', ?)
    ON CONFLICT(extension, queue_id) DO UPDATE SET
        agent_name = excluded.agent_name,
        type = excluded.type,
        status = 'AVAILABLE',
        login_time = CASE WHEN status = 'OFFLINE' THEN ? ELSE login_time END,
        logout_time = NULL
    """, (agent_ext, agent_name, queue_num, member_type, now_str, now_str))
    
    if current_status is None or current_status == 'OFFLINE':
        c.execute("""
        INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
        VALUES (?, ?, 'LOGIN', ?)
        """, (agent_ext, queue_num, now_str))
        
    conn.commit()
    conn.close()

def db_agent_logout(agent_ext, queue_num):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Fix: Prevent duplicate logout events
    c.execute("SELECT status FROM queue_agents WHERE extension = ? AND queue_id = ?", (agent_ext, queue_num))
    row = c.fetchone()
    current_status = row["status"] if row else None
    
    if current_status is not None and current_status != 'OFFLINE':
        c.execute("""
        UPDATE queue_agents SET 
            status = 'OFFLINE',
            login_time = NULL,
            logout_time = ? 
        WHERE extension = ? AND queue_id = ?
        """, (now_str, agent_ext, queue_num))
        
        c.execute("""
        INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
        VALUES (?, ?, 'LOGOUT', ?)
        """, (agent_ext, queue_num, now_str))
        
    conn.commit()
    conn.close()

def db_agent_pause(agent_ext, queue_num, is_paused):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "PAUSED" if is_paused else "AVAILABLE"
    evt_type = "PAUSE" if is_paused else "UNPAUSE"
    
    # Fix: Prevent duplicate pause/unpause events
    c.execute("SELECT status FROM queue_agents WHERE extension = ? AND queue_id = ?", (agent_ext, queue_num))
    row = c.fetchone()
    current_status = row["status"] if row else None
    
    if current_status != status:
        c.execute("""
        UPDATE queue_agents SET 
            status = ? 
        WHERE extension = ? AND queue_id = ?
        """, (status, agent_ext, queue_num))
        
        c.execute("""
        INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
        VALUES (?, ?, ?, ?)
        """, (agent_ext, queue_num, evt_type, now_str))
        
    conn.commit()
    conn.close()

def db_agent_status_update(agent_ext, queue_num, status_str, is_paused=False):
    # Map raw AMI QueueMemberStatus/QueueStatus events to agent database statuses
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT status, login_time FROM queue_agents WHERE extension = ? AND queue_id = ?", (agent_ext, queue_num))
    row = c.fetchone()
    
    status_to_write = "PAUSED" if is_paused else status_str
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if row:
        current_status = row["status"]
        current_login_time = row["login_time"]
        
        # If we are transitions from offline to active, set/preserve login_time
        if current_status == 'OFFLINE' and status_to_write != 'OFFLINE':
            login_time_val = now_str
        else:
            login_time_val = current_login_time
            
        if status_to_write == 'OFFLINE':
            login_time_val = None
            
        if current_status != status_to_write or login_time_val != current_login_time:
            c.execute("""
                UPDATE queue_agents 
                SET status = ?, login_time = ?, logout_time = CASE WHEN ? = 'OFFLINE' THEN ? ELSE logout_time END
                WHERE extension = ? AND queue_id = ?
            """, (status_to_write, login_time_val, status_to_write, now_str, agent_ext, queue_num))
            
            evt_type = "PAUSE" if status_to_write == "PAUSED" else \
                       "UNPAUSE" if current_status == "PAUSED" else \
                       "LOGIN" if current_status == "OFFLINE" and status_to_write != "OFFLINE" else \
                       "LOGOUT" if status_to_write == "OFFLINE" else \
                       "STATUS_CHANGE"
                       
            c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES (?, ?, ?, ?)
            """, (agent_ext, queue_num, evt_type, now_str))
    else:
        # Agent not in database (dynamic sync discovery)
        login_time_val = None if status_to_write == 'OFFLINE' else now_str
        logout_time_val = now_str if status_to_write == 'OFFLINE' else None
        
        c.execute("""
            INSERT INTO queue_agents (extension, agent_name, queue_id, type, status, login_time, logout_time)
            VALUES (?, ?, ?, 'DYNAMIC', ?, ?, ?)
        """, (agent_ext, agent_ext, queue_num, status_to_write, login_time_val, logout_time_val))
        
        evt_type = "LOGOUT" if status_to_write == 'OFFLINE' else "LOGIN"
        c.execute("""
            INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
            VALUES (?, ?, ?, ?)
        """, (agent_ext, queue_num, evt_type, now_str))
        
    conn.commit()
    conn.close()

def db_agent_call_event(agent_ext, queue_num, event, uniqueid=None, event_time=None):
    # Events like: RING, ANSWER, HANGUP, RINGNOANSWER
    conn = get_db_connection()
    c = conn.cursor()
    now_str = _event_time_string(event_time)
    c.execute("""
    INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
    VALUES (?, ?, ?, ?, ?)
    """, (agent_ext, queue_num, event, uniqueid, now_str))
    
    if event in ("RING", "ANSWER"):
        if queue_num:
            c.execute("UPDATE queue_agents SET status = 'BUSY' WHERE extension = ? AND queue_id = ?", (agent_ext, queue_num))
        else:
            c.execute("UPDATE queue_agents SET status = 'BUSY' WHERE extension = ?", (agent_ext,))
    elif event in ("HANGUP", "RINGNOANSWER", "COMPLETE"):
        if queue_num:
            c.execute("UPDATE queue_agents SET status = 'AVAILABLE' WHERE extension = ? AND queue_id = ? AND status IN ('BUSY', 'IN USE', 'RINGING')", (agent_ext, queue_num))
        else:
            c.execute("UPDATE queue_agents SET status = 'AVAILABLE' WHERE extension = ? AND status IN ('BUSY', 'IN USE', 'RINGING')", (agent_ext,))
        
    conn.commit()
    conn.close()

# Database Readers for UI and Statistics Integration
def _queue_scope_sql(filters, column):
    """Return a SQL predicate for the centralized Reporting Data Scope."""
    scope_ids = filters.get("_scope_queue_ids") if isinstance(filters, dict) else None
    if scope_ids is None:
        return "", []
    scope_ids = sorted({str(item) for item in scope_ids})
    if not scope_ids:
        return " AND 1 = 0", []
    placeholders = ",".join("?" for _ in scope_ids)
    direct_scope = f"{column} IN ({placeholders})"

    # A transferred queue call can still have only one queue_calls row: the
    # original queue leg.  QueueLog stores the target queue on the TRANSFER
    # event (in queue_agent_events.agent), so make that target visible to a
    # user scoped to the destination queue as well.  This affects only the
    # queue_calls query shape; normal queue/agent analytics continue to use
    # their own physical queue column.
    if column == "qc.queue_id":
        transfer_scope = f"""
            EXISTS (
                SELECT 1
                FROM queue_agent_events qae
                WHERE qae.event_type = 'TRANSFER'
                  AND qae.agent IN ({placeholders})
                  AND (qae.uniqueid = qc.uniqueid OR qae.uniqueid = qc.linkedid)
            )
        """
        return f" AND ({direct_scope} OR {transfer_scope})", scope_ids + scope_ids

    return f" AND {direct_scope}", scope_ids


def _dedupe_attempt_events(rows):
    """Collapse collector/QueueLog duplicates while preserving real retries.

    A repeated event for the same agent/call/queue within one second is the
    same attempt arriving from two sources.  A later ring after RINGNOANSWER
    remains a real retry and is intentionally retained.
    """
    kept = []
    last_seen = {}
    for row in rows or []:
        event_type = str(row["event_type"] or "").upper()
        if event_type not in {"ENTERQUEUE", "RING", "ANSWER", "RINGNOANSWER", "RINGCANCELED"}:
            kept.append(row)
            continue
        key = (
            str(row["uniqueid"] or "").strip(),
            str(row["agent"] or "").strip(),
            str(row["queue"] or "").strip(),
            event_type,
        )
        current_time = _coerce_event_datetime(row["timestamp"])
        previous_time = last_seen.get(key)
        if previous_time is not None and current_time is not None:
            if abs((current_time - previous_time).total_seconds()) <= 1:
                continue
        last_seen[key] = current_time
        kept.append(row)
    return kept


def _count_agent_attempt_events(conn, agent, event_type, filters):
    query = """
        SELECT agent, queue, event_type, uniqueid, timestamp
        FROM queue_agent_events
        WHERE agent = ? AND event_type = ?
    """
    params = [agent, event_type]
    if filters.get("date_from"):
        query += " AND timestamp >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += " AND timestamp <= ?"
        params.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        query += " AND time(timestamp) >= ?"
        params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        query += " AND time(timestamp) <= ?"
        params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
    if filters.get("queue") and filters["queue"] != "all":
        query += " AND queue = ?"
        params.append(filters["queue"])
    scope_sql, scope_params = _queue_scope_sql(filters, "queue")
    query += scope_sql
    params.extend(scope_params)
    query += " ORDER BY timestamp ASC, id ASC"
    return len(_dedupe_attempt_events(conn.execute(query, params).fetchall()))


def _queue_stats_event_map(conn, rows):
    ids = {str(row["uniqueid"] or "").strip() for row in rows if row["uniqueid"]}
    ids.update(str(row["linkedid"] or "").strip() for row in rows if row["linkedid"])
    ids = sorted(value for value in ids if value)
    events = {}
    for offset in range(0, len(ids), 400):
        chunk = ids[offset:offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        query = f"""
            SELECT id, agent, queue, event_type, uniqueid, timestamp, transfer_type
            FROM queue_agent_events
            WHERE uniqueid IN ({placeholders})
            ORDER BY timestamp ASC, id ASC
        """
        for event in conn.execute(query, chunk).fetchall():
            events.setdefault(str(event["uniqueid"] or "").strip(), []).append(event)
    return events


def _queue_stats_session_rows(row, events):
    """Expand a transferred call into one report row per queue visit."""
    ordered = sorted(
        _dedupe_attempt_events(events),
        key=lambda item: (_coerce_event_datetime(item["timestamp"]) or datetime.max, int(item["id"] or 0)),
    )
    enters = [
        event for event in ordered
        if str(event["event_type"] or "").upper() == "ENTERQUEUE"
        and _coerce_event_datetime(event["timestamp"])
    ]
    if len(enters) <= 1:
        return [row]

    sessions = []
    terminal_types = {
        "HANGUP", "COMPLETE", "COMPLETEAGENT", "COMPLETECALLER",
        "ABANDON", "EXITWITHTIMEOUT", "EXITWITHKEY", "EXITEMPTY",
    }
    for index, enter in enumerate(enters):
        start_dt = _coerce_event_datetime(enter["timestamp"])
        next_dt = _coerce_event_datetime(enters[index + 1]["timestamp"]) if index + 1 < len(enters) else None
        queue_number = str(enter["queue"] or row["queue_id"] or "").strip()
        scoped = [
            event for event in ordered
            if (_coerce_event_datetime(event["timestamp"]) or datetime.min) >= start_dt
            and (next_dt is None or (_coerce_event_datetime(event["timestamp"]) or datetime.max) < next_dt)
            and (not event["queue"] or str(event["queue"]).strip() == queue_number)
        ]
        answer_events = [
            event for event in scoped
            if str(event["event_type"] or "").upper() in {"ANSWER", "CONNECT"}
            and str(event["agent"] or "").strip()
        ]
        terminal_events = [
            event for event in scoped
            if str(event["event_type"] or "").upper() in terminal_types
        ]
        answer_event = answer_events[0] if answer_events else None
        terminal_event = terminal_events[0] if terminal_events else None
        end_dt = _coerce_event_datetime(terminal_event["timestamp"]) if terminal_event else next_dt
        status = "ANSWERED" if answer_event else ""
        if not status and terminal_event:
            terminal_type = str(terminal_event["event_type"] or "").upper()
            status = {
                "ABANDON": "ABANDONED",
                "EXITWITHTIMEOUT": "TIMEOUT",
                "EXITWITHKEY": "CANCELLED",
                "EXITEMPTY": "NO ANSWER",
            }.get(terminal_type, "NO ANSWER")
        if not status and index == len(enters) - 1:
            status = str(row["status"] or "NO ANSWER")
        answer_dt = _coerce_event_datetime(answer_event["timestamp"]) if answer_event else None
        wait_end = answer_dt or end_dt
        wait_time = max(0, int((wait_end - start_dt).total_seconds())) if wait_end else int(row["wait_time"] or 0)
        talk_time = 0
        if answer_dt and end_dt:
            talk_time = max(0, int((end_dt - answer_dt).total_seconds()))
        if not answer_event and index == len(enters) - 1:
            talk_time = int(row["talk_time"] or 0)
        item = dict(row)
        item.update({
            "queue_id": queue_number,
            "queue_name": row["queue_name"] if queue_number == str(row["queue_id"] or "") else queue_number,
            "entry_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "answer_time": answer_dt.strftime("%Y-%m-%d %H:%M:%S") if answer_dt else None,
            "hangup_time": end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else row["hangup_time"],
            "status": status,
            "agent": str(answer_event["agent"] or "").strip() if answer_event else (str(row["agent"] or "") if index == len(enters) - 1 else ""),
            "wait_time": wait_time,
            "talk_time": talk_time,
            "hold_time": int(row["hold_time"] or 0) if len(enters) == 1 else 0,
            "queue_session_index": index,
        })
        sessions.append(item)
    return sessions


def _expand_queue_stats_sessions(conn, rows, filters):
    event_map = _queue_stats_event_map(conn, rows)
    queue_names = {
        str(item["queue_number"]): item["queue_name"]
        for item in conn.execute("SELECT queue_number, queue_name FROM queues").fetchall()
        if item["queue_number"]
    }
    expanded = []
    allowed = filters.get("_scope_queue_ids")
    requested = str(filters.get("queue") or "all")
    for row in rows:
        uid = str(row["uniqueid"] or "").strip()
        related_events = event_map.get(uid, [])
        session_rows = _queue_stats_session_rows(row, related_events)
        for session in session_rows:
            session = dict(session)
            queue_number = str(session["queue_id"] or "").strip()
            if requested != "all" and queue_number != requested:
                transfer_target = any(
                    str(event["event_type"] or "").upper() == "TRANSFER"
                    and str(event["agent"] or "").strip() == requested
                    for event in related_events
                )
                if transfer_target and len(session_rows) == 1:
                    expanded.append(session)
                continue
            if allowed is not None and queue_number not in {str(value) for value in allowed}:
                transfer_target = any(
                    str(event["event_type"] or "").upper() == "TRANSFER"
                    and str(event["agent"] or "").strip() in {str(value) for value in allowed}
                    for event in related_events
                )
                if transfer_target and len(session_rows) == 1:
                    expanded.append(session)
                continue
            if queue_number in queue_names:
                session["mapped_queue_name"] = queue_names[queue_number]
            expanded.append(session)
    return expanded


def get_filtered_queue_stats(filters):
    sync_queue_log_to_db()
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Optional AI analysis is not present in every installation/test fixture;
    # reporting must remain usable when that extension table is absent.
    analysis_table = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rcm_call_analysis'"
    ).fetchone()
    analysis_select = (
        ", a.sentiment AS ai_sentiment, a.transcript AS ai_transcript, a.summary AS ai_summary"
        if analysis_table else ", NULL AS ai_sentiment, NULL AS ai_transcript, NULL AS ai_summary"
    )
    analysis_join = " LEFT JOIN rcm_call_analysis a ON qc.call_id = a.call_id" if analysis_table else ""
    query = f"""
        SELECT qc.*, q.queue_name AS mapped_queue_name{analysis_select}
        FROM queue_calls qc
        LEFT JOIN queues q ON qc.queue_id = q.queue_number{analysis_join}
        WHERE 1=1
    """
    params = []
    
    if filters.get("date_from"):
        query += " AND qc.entry_time >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += " AND qc.entry_time <= ?"
        params.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        query += " AND time(qc.entry_time) >= ?"
        params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        query += " AND time(qc.entry_time) <= ?"
        params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
        
    if filters.get("queue") and filters["queue"] != "all":
        # Include an original queue leg when the selected queue is the target
        # of a recorded transfer.  The call details endpoint then opens the
        # complete linked journey, as required for queue-scoped users.
        query += """
            AND (
                qc.queue_id = ?
                OR EXISTS (
                    SELECT 1
                    FROM queue_agent_events qae
                    WHERE qae.event_type = 'TRANSFER'
                      AND qae.agent = ?
                      AND (qae.uniqueid = qc.uniqueid OR qae.uniqueid = qc.linkedid)
                )
            )
        """
        params.extend([filters["queue"], filters["queue"]])

    scope_sql, scope_params = _queue_scope_sql(filters, "qc.queue_id")
    query += scope_sql
    params.extend(scope_params)
        
    if filters.get("agent") and filters["agent"] != "all":
        query += " AND qc.agent = ?"
        params.append(filters["agent"])
        
    if filters.get("caller"):
        query += " AND qc.caller_number LIKE ?"
        params.append(f"%{filters['caller']}%")
        
    query += " ORDER BY qc.entry_time DESC"
    c.execute(query, params)
    rows = c.fetchall()
    rows = _expand_queue_stats_sessions(conn, rows, filters)
    
    calls = []
    for r in rows:
        import datetime as dt_module
        talk_time = _resolve_queue_talk_time(r)
        recording = _resolve_queue_recording(r)
        ts = 0
        if r["entry_time"]:
            try:
                dt = dt_module.datetime.strptime(r["entry_time"], "%Y-%m-%d %H:%M:%S")
                ts = _local_epoch(dt)
            except Exception:
                pass
                
        calls.append({
            "id": r["call_id"],
            "call_id": r["call_id"],
            "callid": r["uniqueid"],
            "uniqueid": r["uniqueid"],
            "linkedid": r["linkedid"],
            "queuename": r["queue_id"],
            "queue": r["queue_id"],
            "queue_id": r["queue_id"],
            # Fix: use mapped_queue_name from queues mapping first
            "queue_name": r["mapped_queue_name"] or r["queue_name"] or r["queue_id"],
            "caller": r["caller_number"],
            "caller_number": r["caller_number"],
            "timestamp": ts,
            "entry_time": r["entry_time"],
            "answer_time": r["answer_time"],
            "hangup_time": r["hangup_time"],
            "status": r["status"],
            "agent": r["agent"] or "",
            "wait_time": r["wait_time"] or 0,
            "talk_time": talk_time,
            "hold_time": r["hold_time"] or 0,
            "hangup_by": "AGENT" if (r["hangup_by"] == "AGENT" or (r["status"] == "ANSWERED" and r["hangup_by"] != "CALLER")) else "CALLER",
            "initial_position": r["initial_position"] if ("initial_position" in r.keys() and r["initial_position"] is not None) else (r["position"] or 0),
            "last_position": r["last_position"] if ("last_position" in r.keys() and r["last_position"] is not None) else (r["position"] or 0),
            "recording_file": recording,
            "recording_path": recording,
            "source_trunk": r["source_trunk"] if ("source_trunk" in r.keys() and r["source_trunk"]) else "Trunk-SIP-Main",
            "position": r["position"] if ("position" in r.keys() and r["position"]) else 0,
            "disposition_code": "",
            "vip_priority": 0,
            "ai_sentiment": r["ai_sentiment"] if "ai_sentiment" in r.keys() else None,
            "ai_transcript": r["ai_transcript"] if "ai_transcript" in r.keys() else None,
            "ai_summary": r["ai_summary"] if "ai_summary" in r.keys() else None
        })
        
    conn.close()
    return calls

def get_agent_analytics(filters):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Fix: Apply agent/queue filters to agent selection
    q_agents = "SELECT DISTINCT extension, agent_name, type FROM queue_agents"
    params_agents = []
    where_clauses = []
    if filters.get("agent") and filters["agent"] != "all":
        where_clauses.append("extension = ?")
        params_agents.append(filters["agent"])
    if filters.get("queue") and filters["queue"] != "all":
        where_clauses.append("queue_id = ?")
        params_agents.append(filters["queue"])
    scope_sql, scope_params = _queue_scope_sql(filters, "queue_id")
    if scope_sql:
        where_clauses.append(scope_sql.replace(" AND ", "", 1))
        params_agents.extend(scope_params)
    if where_clauses:
        q_agents += " WHERE " + " AND ".join(where_clauses)
        
    c.execute(q_agents, params_agents)
    agents = c.fetchall()
    
    import db
    ext_names = {e["ext"]: e.get("name") or e["ext"] for e in db.get_all_extensions()}
    report_filters = dict(filters)
    report_filters["agent"] = "all"
    try:
        report_calls = get_filtered_queue_stats(report_filters)
    except Exception:
        report_calls = None
    if report_calls is not None:
        status_filter = str(filters.get("call_status") or "all")
        if status_filter != "all":
            status_map = {
                "ANSWERED": "answered", "ABANDONED": "abandoned",
                "CANCELLED": "cancelled", "CANCELED": "cancelled",
                "NO ANSWER": "no_answer", "TIMEOUT": "timeout",
            }
            report_calls = [
                call for call in report_calls
                if status_map.get(str(call.get("status") or "").upper(), "other") == status_filter
            ]
        wait_filter = str(filters.get("wait_time") or "all")
        talk_filter = str(filters.get("talk_time") or "all")
        if wait_filter != "all":
            report_calls = [
                call for call in report_calls
                if (
                    (wait_filter == "short" and int(call.get("wait_time") or 0) < 20)
                    or (wait_filter == "medium" and 20 <= int(call.get("wait_time") or 0) <= 60)
                    or (wait_filter == "long" and int(call.get("wait_time") or 0) > 60)
                )
            ]
        if talk_filter != "all":
            report_calls = [
                call for call in report_calls
                if (
                    (talk_filter == "short" and int(call.get("talk_time") or 0) < 60)
                    or (talk_filter == "medium" and 60 <= int(call.get("talk_time") or 0) <= 300)
                    or (talk_filter == "long" and int(call.get("talk_time") or 0) > 300)
                )
            ]
    agent_rows = [dict(item) for item in agents]
    known_agents = {str(item.get("extension") or "") for item in agent_rows}
    if report_calls is not None:
        for call in report_calls:
            ext = str(call.get("agent") or "").strip()
            if not ext or ext in known_agents:
                continue
            if filters.get("agent") and filters["agent"] != "all" and str(filters["agent"]) != ext:
                continue
            agent_rows.append({"extension": ext, "agent_name": ext, "type": "DYNAMIC"})
            known_agents.add(ext)
    deduped_agent_rows = {}
    for item in agent_rows:
        ext = str(item.get("extension") or "").strip()
        if not ext:
            continue
        current = deduped_agent_rows.get(ext)
        if current is None or (not current.get("agent_name") and item.get("agent_name")):
            deduped_agent_rows[ext] = item
    agent_rows = list(deduped_agent_rows.values())
    agent_name_filter = str(filters.get("agent_name") or "").strip().lower()
    if agent_name_filter:
        agent_rows = [
            item for item in agent_rows
            if agent_name_filter in str(
                ext_names.get(str(item.get("extension") or ""))
                or item.get("agent_name")
                or item.get("extension")
                or ""
            ).lower()
        ]

    results = []
    for a in agent_rows:
        ext = a["extension"]
        name = ext_names.get(ext) or a["agent_name"] or ext
        
        # Filter calls for this agent
        q = "SELECT COUNT(*) as calls_count, SUM(talk_time) as talk_sum, MAX(talk_time) as talk_max FROM queue_calls WHERE agent = ? AND status = 'ANSWERED'"
        params = [ext]
        
        if filters.get("date_from"):
            q += " AND entry_time >= ?"
            params.append(filters["date_from"] + " 00:00:00")
        if filters.get("date_to"):
            q += " AND entry_time <= ?"
            params.append(filters["date_to"] + " 23:59:59")
        if filters.get("time_from"):
            q += " AND time(entry_time) >= ?"
            params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
        if filters.get("time_to"):
            q += " AND time(entry_time) <= ?"
            params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
        if filters.get("caller"):
            q += " AND caller_number LIKE ?"
            params.append(f"%{filters['caller']}%")
        if filters.get("queue") and filters["queue"] != "all":
            q += " AND queue_id = ?"
            params.append(filters["queue"])
        scope_sql, scope_params = _queue_scope_sql(filters, "queue_id")
        q += scope_sql
        params.extend(scope_params)
            
        if report_calls is not None:
            agent_call_rows = [
                call for call in report_calls
                if str(call.get("agent") or "").strip() == str(ext)
                and str(call.get("status") or "").upper() == "ANSWERED"
            ]
            calls_count = len(agent_call_rows)
            talk_sum = sum(int(call.get("talk_time") or 0) for call in agent_call_rows)
            talk_max = max((int(call.get("talk_time") or 0) for call in agent_call_rows), default=0)
        else:
            c.execute(q, params)
            call_stats = c.fetchone()
            calls_count = call_stats["calls_count"] or 0
            talk_sum = call_stats["talk_sum"] or 0
            talk_max = call_stats["talk_max"] or 0
        avg_talk = int(talk_sum / calls_count) if calls_count > 0 else 0
        
        # Count real attempts, collapsing only same-second collector/QueueLog
        # duplicates. A later ring after a no-answer remains a separate retry.
        missed_count = _count_agent_attempt_events(conn, ext, "RINGNOANSWER", filters)
        cancelled_count = _count_agent_attempt_events(conn, ext, "RINGCANCELED", filters)
        
        # LOGIN/LOGOUT/PAUSE/UNPAUSE events for duration calculation
        q_evts = "SELECT event_type, timestamp FROM queue_agent_events WHERE agent = ? AND event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE')"
        params_evts = [ext]
        
        if filters.get("date_from"):
            q_evts += " AND timestamp >= ?"
            params_evts.append(filters["date_from"] + " 00:00:00")
        if filters.get("date_to"):
            q_evts += " AND timestamp <= ?"
            params_evts.append(filters["date_to"] + " 23:59:59")
        if filters.get("time_from"):
            q_evts += " AND time(timestamp) >= ?"
            params_evts.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
        if filters.get("time_to"):
            q_evts += " AND time(timestamp) <= ?"
            params_evts.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
        if filters.get("queue") and filters["queue"] != "all":
            q_evts += " AND queue = ?"
            params_evts.append(filters["queue"])
        scope_sql, scope_params = _queue_scope_sql(filters, "queue")
        q_evts += scope_sql
        params_evts.extend(scope_params)
            
        q_evts += " ORDER BY timestamp ASC"
        c.execute(q_evts, params_evts)
        evts = c.fetchall()
        
        online_time = 0
        pause_time = 0
        
        login_ts = None
        pause_ts = None
        
        sessions = []
        pauses = []
        
        import datetime as dt_module
        
        # Check boundary state at the start of the date range
        if filters.get("date_from"):
            q_boundary = """
                SELECT event_type, timestamp FROM queue_agent_events 
                WHERE agent = ? AND event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE') 
                  AND timestamp < ?
            """
            params_boundary = [ext, filters["date_from"] + " 00:00:00"]
            if filters.get("queue") and filters["queue"] != "all":
                q_boundary += " AND queue = ?"
                params_boundary.append(filters["queue"])
            scope_sql, scope_params = _queue_scope_sql(filters, "queue")
            q_boundary += scope_sql
            params_boundary.extend(scope_params)
            q_boundary += " ORDER BY timestamp DESC LIMIT 1"
            c.execute(q_boundary, params_boundary)
            last_evt = c.fetchone()
            if last_evt:
                boundary_start_dt = dt_module.datetime.strptime(filters["date_from"] + " 00:00:00", "%Y-%m-%d %H:%M:%S")
                if last_evt["event_type"] in ('LOGIN', 'UNPAUSE'):
                    login_ts = boundary_start_dt
                    sessions.append({
                        "queuename": "Queue",
                        "login_time": int(boundary_start_dt.timestamp()),
                        "logout_time": 0,
                        "total_online_time": 0
                    })
                elif last_evt["event_type"] == 'PAUSE':
                    login_ts = boundary_start_dt
                    sessions.append({
                        "queuename": "Queue",
                        "login_time": int(boundary_start_dt.timestamp()),
                        "logout_time": 0,
                        "total_online_time": 0
                    })
                    pause_ts = boundary_start_dt
                    pauses.append({
                        "queuename": "Queue",
                        "pause_time": int(boundary_start_dt.timestamp()),
                        "unpause_time": 0,
                        "reason": "Break"
                    })
        for evt in evts:
            evt_type = evt["event_type"]
            try:
                evt_dt = dt_module.datetime.strptime(evt["timestamp"], "%Y-%m-%d %H:%M:%S")
                evt_ts = int(evt_dt.timestamp())
            except Exception:
                continue
                
            if evt_type == 'LOGIN':
                # Fix: Close previous session/pause if unclosed before starting a new one
                if login_ts:
                    online_time += int((evt_dt - login_ts).total_seconds())
                    if sessions and sessions[-1]["logout_time"] == 0:
                        sessions[-1]["logout_time"] = evt_ts
                        sessions[-1]["total_online_time"] = max(0, evt_ts - sessions[-1]["login_time"])
                    if pause_ts:
                        pause_time += int((evt_dt - pause_ts).total_seconds())
                        if pauses and pauses[-1]["unpause_time"] == 0:
                            pauses[-1]["unpause_time"] = evt_ts
                        pause_ts = None
                login_ts = evt_dt
                sessions.append({
                    "queuename": "Queue",
                    "login_time": evt_ts,
                    "logout_time": 0,
                    "total_online_time": 0
                })
            elif evt_type == 'LOGOUT':
                if login_ts:
                    online_time += int((evt_dt - login_ts).total_seconds())
                    login_ts = None
                if sessions and sessions[-1]["logout_time"] == 0:
                    sessions[-1]["logout_time"] = evt_ts
                    sessions[-1]["total_online_time"] = max(0, evt_ts - sessions[-1]["login_time"])
                if pauses and pauses[-1]["unpause_time"] == 0:
                    pauses[-1]["unpause_time"] = evt_ts
                if pause_ts:
                    pause_time += int((evt_dt - pause_ts).total_seconds())
                    pause_ts = None
            elif evt_type == 'PAUSE':
                # Fix: Close previous active pause if unclosed
                if pause_ts:
                    pause_time += int((evt_dt - pause_ts).total_seconds())
                    if pauses and pauses[-1]["unpause_time"] == 0:
                        pauses[-1]["unpause_time"] = evt_ts
                if login_ts:
                    pause_ts = evt_dt
                pauses.append({
                    "queuename": "Queue",
                    "pause_time": evt_ts,
                    "unpause_time": 0,
                    "reason": "Break"
                })
            elif evt_type == 'UNPAUSE':
                if pause_ts:
                    pause_time += int((evt_dt - pause_ts).total_seconds())
                    pause_ts = None
                if pauses and pauses[-1]["unpause_time"] == 0:
                    pauses[-1]["unpause_time"] = evt_ts
                
        end_boundary = dt_module.datetime.now()
        if filters.get("date_to"):
            boundary_dt = dt_module.datetime.strptime(filters["date_to"] + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            if boundary_dt < end_boundary:
                end_boundary = boundary_dt

        if login_ts:
            online_time += int((end_boundary - login_ts).total_seconds())
            if sessions and sessions[-1]["logout_time"] == 0:
                sessions[-1]["total_online_time"] = max(0, int(end_boundary.timestamp()) - sessions[-1]["login_time"])
        if pause_ts:
            pause_time += int((end_boundary - pause_ts).total_seconds())
            # Fix: Update unpause_time for the active pause at boundary end
            if pauses and pauses[-1]["unpause_time"] == 0:
                pauses[-1]["unpause_time"] = int(end_boundary.timestamp())
            
        a_type = (a["type"] or "DYNAMIC").upper()
        if a_type == "STATIC":
            online_time = None
            pause_time = None
            available_time = None
            productivity_score = None
            sessions = []
            pauses = []
            acw_duration = 0
        else:
            available_time = max(0, online_time - pause_time)
            acw_duration = int(talk_sum * 0.08)
            productivity_score = min(100, int(((talk_sum + acw_duration) / online_time) * 100)) if online_time > 0 else 0
        
        results.append({
            "id": ext,
            "extension": ext,
            "agent": ext,
            "agent_name": name,
            "type": a_type,
            "online_time": online_time,
            "pause_time": pause_time,
            "available_time": available_time,
            "calls": calls_count,
            "talk_time": talk_sum,
            "longest_talk": talk_max,
            "avg_talk": avg_talk,
            "missed_calls": missed_count,
            "no_answer_calls": missed_count,
            "cancelled_calls": cancelled_count,
            "acw_duration": acw_duration,
            "productivity_score": productivity_score,
            "sessions": sessions,
            "pauses": pauses
        })
        
    conn.close()
    return results


def _occupancy_scope_sql(filters, column):
    """Apply the physical queue scope to occupancy metrics.

    Occupancy is queue-leg based.  Unlike the call list, a transfer target
    should not make the original queue's time or agent metrics count toward
    the destination queue.
    """
    scope_ids = filters.get("_scope_queue_ids") if isinstance(filters, dict) else None
    if scope_ids is None:
        return "", []
    scope_ids = sorted({str(item) for item in scope_ids})
    if not scope_ids:
        return " AND 1 = 0", []
    placeholders = ",".join("?" for _ in scope_ids)
    return f" AND {column} IN ({placeholders})", scope_ids


def _occupancy_time_filters(filters, field, query, params):
    """Append the shared date/time/caller filters to an occupancy query."""
    if filters.get("date_from"):
        query += f" AND {field} >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += f" AND {field} <= ?"
        params.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        query += f" AND time({field}) >= ?"
        params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        query += f" AND time({field}) <= ?"
        params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
    return query, params


def get_agent_occupancy(filters, base_agents=None):
    """Return queue-agent occupancy, work mix, and drill-down details.

    ``available_time`` is logged-in time minus pauses.  Occupancy is the
    productive busy time (talk + hold) divided by that available window.
    Static agents do not have login sessions, so their occupancy is returned
    as ``None`` rather than inventing a denominator.
    """
    agents = [dict(item) for item in (base_agents if base_agents is not None else get_agent_analytics(filters))]
    if not agents:
        return []

    conn = get_db_connection()
    c = conn.cursor()
    import db
    extension_names = {str(e["ext"]): e.get("name") or e["ext"] for e in db.get_all_extensions() if e.get("ext")}
    agent_ids = {str(item.get("extension") or item.get("agent") or "") for item in agents}
    report_filters = dict(filters)
    report_filters["agent"] = "all"
    try:
        expanded_calls = get_filtered_queue_stats(report_filters)
    except Exception:
        expanded_calls = None

    # The queue list lets us distinguish a transfer target queue (6501) from
    # a transfer target agent (5002) in QueueLog's shared agent column.
    queue_rows = c.execute("SELECT queue_number FROM queues").fetchall()
    queue_ids = {str(row["queue_number"]) for row in queue_rows if row["queue_number"]}
    call_owner_rows = c.execute(
        """
        SELECT uniqueid, linkedid, agent, queue_id
        FROM queue_calls
        WHERE agent IS NOT NULL AND TRIM(agent) <> ''
        """
    ).fetchall()
    call_owner_by_id = {}
    for owner_row in call_owner_rows:
        owner = str(owner_row["agent"] or "").strip()
        if not owner:
            continue
        for owner_key in (owner_row["uniqueid"], owner_row["linkedid"]):
            if owner_key:
                call_owner_by_id[(str(owner_key), str(owner_row["queue_id"] or ""))] = owner

    transfer_query = """
        SELECT id, agent, queue, event_type, uniqueid, timestamp, transfer_type
        FROM queue_agent_events
        WHERE event_type IN ('ANSWER', 'TRANSFER')
    """
    transfer_params = []
    transfer_query, transfer_params = _occupancy_time_filters(filters, "timestamp", transfer_query, transfer_params)
    if filters.get("queue") and filters["queue"] != "all":
        transfer_query += " AND queue = ?"
        transfer_params.append(filters["queue"])
    scope_sql, scope_params = _occupancy_scope_sql(filters, "queue")
    transfer_query += scope_sql
    transfer_params.extend(scope_params)
    transfer_query += " ORDER BY timestamp ASC, id ASC"
    transfer_rows = c.execute(transfer_query, transfer_params).fetchall()

    transfer_counts = {
        ext: {"in": 0, "out": 0, "events": []}
        for ext in agent_ids
    }
    active_answered_agent = {}
    for row in transfer_rows:
        event_type = str(row["event_type"] or "").upper()
        event_agent = str(row["agent"] or "").strip()
        event_queue = str(row["queue"] or "").strip()
        event_uid = str(row["uniqueid"] or "").strip()
        event_key = (event_uid, event_queue)
        if event_type == "ANSWER":
            if event_agent:
                active_answered_agent[event_key] = event_agent
            continue
        source = active_answered_agent.get(event_key, "")
        if not source:
            source = call_owner_by_id.get((event_uid, event_queue), "")
        target = event_agent
        transfer_type = str(row["transfer_type"] or "").strip() or "Blind Transfer"
        target_label = f"Queue {target}" if target in queue_ids else (extension_names.get(target) or target or "Unknown")
        event_details = {
            "direction": "out" if source in agent_ids else "in" if target in agent_ids else "queue",
            "source": source,
            "target": target,
            "target_label": target_label,
            "queue": event_queue,
            "timestamp": row["timestamp"] or "",
            "transfer_type": transfer_type,
            "uniqueid": event_uid,
        }
        if source in transfer_counts:
            transfer_counts[source]["out"] += 1
            transfer_counts[source]["events"].append(dict(event_details, direction="out"))
        if target in transfer_counts and target not in queue_ids:
            transfer_counts[target]["in"] += 1
            transfer_counts[target]["events"].append(dict(event_details, direction="in"))

    occupancy = []
    for item in agents:
        ext = str(item.get("extension") or item.get("agent") or "")
        talk_time = int(item.get("talk_time") or 0)
        online_time = item.get("online_time")
        pause_time = int(item.get("pause_time") or 0)
        available_time = item.get("available_time")
        if available_time is not None:
            available_time = max(0, int(available_time or 0))

        calls_query = """
            SELECT uniqueid, linkedid, queue_id, queue_name, caller_number,
                   entry_time, answer_time, hangup_time, status, wait_time,
                   talk_time, hold_time, hangup_by
            FROM queue_calls
            WHERE agent = ?
        """
        calls_params = [ext]
        calls_query, calls_params = _occupancy_time_filters(filters, "entry_time", calls_query, calls_params)
        if filters.get("queue") and filters["queue"] != "all":
            calls_query += " AND queue_id = ?"
            calls_params.append(filters["queue"])
        scope_sql, scope_params = _occupancy_scope_sql(filters, "queue_id")
        calls_query += scope_sql
        calls_params.extend(scope_params)
        calls_query += " ORDER BY entry_time DESC LIMIT 200"
        if expanded_calls is not None:
            call_rows = [
                call for call in expanded_calls
                if str(call.get("agent") or "").strip() == ext
            ][:200]
        else:
            call_rows = c.execute(calls_query, calls_params).fetchall()
        calls_detail = [
            {
                "uniqueid": row["uniqueid"],
                "linkedid": row["linkedid"],
                "queue_id": row["queue_id"],
                "queue_name": row.get("queue_name") or row["queue_id"] if hasattr(row, "get") else row["queue_id"],
                "caller": (row.get("caller_number") if hasattr(row, "get") else row["caller_number"]) or "Unknown",
                "entry_time": (row.get("entry_time") if hasattr(row, "get") else row["entry_time"]) or "",
                "answer_time": (row.get("answer_time") if hasattr(row, "get") else row["answer_time"]) or "",
                "hangup_time": (row.get("hangup_time") if hasattr(row, "get") else row["hangup_time"]) or "",
                "status": (row.get("status") if hasattr(row, "get") else row["status"]) or "",
                "wait_time": int((row.get("wait_time") if hasattr(row, "get") else row["wait_time"]) or 0),
                "talk_time": int((row.get("talk_time") if hasattr(row, "get") else row["talk_time"]) or 0),
                "hold_time": int((row.get("hold_time") if hasattr(row, "get") else row["hold_time"]) or 0),
                "hangup_by": (row.get("hangup_by") if hasattr(row, "get") else row["hangup_by"]) or "",
            }
            for row in call_rows
        ]
        hold_time = sum(item["hold_time"] for item in calls_detail)
        answered_calls = sum(1 for item in calls_detail if str(item["status"]).upper() == "ANSWERED")
        busy_time = talk_time + hold_time
        idle_time = max(0, available_time - busy_time) if available_time is not None else None
        occupancy_percent = (
            round((busy_time / available_time) * 100, 1)
            if available_time is not None and available_time > 0
            else None
        )
        transfers = transfer_counts.get(ext, {"in": 0, "out": 0, "events": []})

        occupancy.append({
            **item,
            "extension": ext,
            "agent": ext,
            "agent_name": extension_names.get(ext) or item.get("agent_name") or ext,
            "answered_calls": answered_calls,
            "talk_time": talk_time,
            "hold_time": hold_time,
            "pause_time": pause_time,
            "online_time": online_time,
            "available_time": available_time,
            "busy_time": busy_time,
            "idle_time": idle_time,
            "occupancy_percent": occupancy_percent,
            "transfers_in": transfers["in"],
            "transfers_out": transfers["out"],
            "transfer_events": sorted(transfers["events"], key=lambda event: event.get("timestamp") or "", reverse=True),
            "calls_detail": calls_detail,
        })

    conn.close()
    return occupancy

def get_call_details_timeline(uniqueid):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Fix: Stop overwriting queue_name with queue number. Use queues table mapping.
    c.execute("""
        SELECT qc.*, q.queue_name AS mapped_queue_name, q.timeout AS mapped_ring_time
        FROM queue_calls qc
        LEFT JOIN queues q ON qc.queue_id = q.queue_number
        WHERE qc.uniqueid = ? OR qc.linkedid = ?
    """, (uniqueid, uniqueid))
    call = c.fetchone()
    
    if not call:
        conn.close()
        return None
        
    q_name = call["mapped_queue_name"] or call["queue_name"] or call["queue_id"]
    queue_ring_time = int(call["mapped_ring_time"] or 0)

    timeline = []
    seen = set()

    def fmt_duration(seconds):
        seconds = int(seconds or 0)
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def get_extension_names():
        try:
            import db
            return {e["ext"]: e.get("name") or e["ext"] for e in db.get_all_extensions()}
        except Exception:
            return {}

    extension_names = get_extension_names()

    def format_agent(agent):
        agent = str(agent or "").strip()
        if not agent:
            return "unknown"
        name = extension_names.get(agent)
        return f"{name} ({agent})" if name and name != agent else agent

    def format_agent_html(agent):
        import html
        return f"<strong>{html.escape(format_agent(agent))}</strong>"

    def add_event(event, time_value, details="", rank=50, details_html=None):
        if not time_value:
            return
        key = (event, time_value, details)
        if key in seen:
            return
        seen.add(key)
        timeline.append({
            "event": event,
            "time": time_value,
            "details": details,
            "details_html": details_html,
            "_rank": rank
        })

    c.execute("""
        SELECT event, position, timestamp
        FROM queue_call_positions
        WHERE uniqueid IN (?, ?)
        ORDER BY timestamp ASC, id ASC
    """, (call["uniqueid"], call["linkedid"]))
    position_events = c.fetchall()

    c.execute("""
        SELECT agent, queue, event_type, timestamp
        FROM queue_agent_events
        WHERE uniqueid IN (?, ?)
        ORDER BY timestamp ASC, id ASC
    """, (call["uniqueid"], call["linkedid"]))
    agent_events = c.fetchall()

    if call["entry_time"]:
        pos_text = f" Initial position: #{call['initial_position']}." if ("initial_position" in call.keys() and call["initial_position"]) else ""
        add_event(
            "Entered Queue",
            call["entry_time"],
            f"Caller {call['caller_number']} entered queue {call['queue_id']} - {q_name}.{pos_text}",
            10
        )

    for ev in position_events:
        event_type = (ev["event"] or "").upper()
        if event_type == "ENTERQUEUE":
            pos = ev["position"] or call["initial_position"] or 1
            add_event("Queue Position", ev["timestamp"], f"Caller joined the waiting line at position #{pos}.", 15)
        elif event_type == "ABANDON":
            if call["hangup_time"] and ev["timestamp"] >= call["hangup_time"]:
                continue
            pos = ev["position"] or call["last_position"] or 0
            add_event("Abandoned", ev["timestamp"], f"Caller left the queue before answer. Last position: #{pos}. Wait time: {fmt_duration(call['wait_time'])}.", 80)
        elif event_type in ("EXITWITHKEY", "RINGCANCELED"):
            if (
                event_type == "RINGCANCELED"
                and call["hangup_time"]
                and (call["hangup_by"] or "").upper() == "CALLER"
                and ev["timestamp"] >= call["hangup_time"]
            ):
                continue
            add_event("Cancelled", ev["timestamp"], f"Caller cancelled or exited the queue. Wait time: {fmt_duration(call['wait_time'])}.", 80)
        elif event_type in ("EXITWITHTIMEOUT", "EXITEMPTY"):
            # The final call row already renders Timeout/No Answer. Keep position events from duplicating it.
            continue

    has_position_abandon = any((ev["event"] or "").upper() == "ABANDON" for ev in position_events)
    answer_agent = call["agent"] or "unknown"
    active_agent = str(call["agent"] or "").strip()
    answer_display_time = call["answer_time"] if call["answer_time"] and call["status"] == 'ANSWERED' else None

    def seconds_between(start, end):
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            return max(0, int((end_dt - start_dt).total_seconds()))
        except Exception:
            return 0

    def caller_ended_during_ring(event_timestamp):
        return (
            call["hangup_time"]
            and (call["hangup_by"] or "").upper() == "CALLER"
            and (call["status"] or "").upper() != "ANSWERED"
            and event_timestamp >= call["hangup_time"]
        )

    pending_rings = []
    for ev in agent_events:
        event_type = (ev["event_type"] or "").upper()
        agent = ev["agent"] or ""
        if not agent:
            continue

        if event_type == "RING":
            if answer_display_time and ev["timestamp"] > answer_display_time:
                continue
            add_event(
                "Agent Ringing",
                ev["timestamp"],
                f"Queue is ringing agent {format_agent(agent)}.",
                30,
                f"Queue is ringing agent {format_agent_html(agent)}."
            )
            pending_rings.append({"agent": agent, "time": ev["timestamp"], "resolved": False})
            continue

        if event_type in ("RINGNOANSWER", "RINGCANCELED", "ANSWER"):
            match = None
            for ring in pending_rings:
                if ring["agent"] == agent and not ring["resolved"]:
                    match = ring
                    break
            event_time = match["time"] if match else ev["timestamp"]
            if answer_display_time and event_time > answer_display_time:
                continue
            if match:
                match["resolved"] = True

            if event_type == "ANSWER":
                add_event("Answered", ev["timestamp"], f"Agent {format_agent(agent)} answered the call.", 40, f"Agent {format_agent_html(agent)} answered the call.")
            elif event_type == "RINGCANCELED":
                if caller_ended_during_ring(ev["timestamp"]):
                    add_event("Caller Ended", ev["timestamp"], f"Caller ended the call while agent {format_agent(agent)} was ringing.", 32, f"Caller ended the call while agent {format_agent_html(agent)} was ringing.")
                else:
                    add_event("Cancelled", event_time, f"Ringing to agent {format_agent(agent)} was cancelled before answer.", 32, f"Ringing to agent {format_agent_html(agent)} was cancelled before answer.")
            else:
                ring_duration = seconds_between(event_time, ev["timestamp"])
                caller_interrupted = (
                    caller_ended_during_ring(ev["timestamp"])
                    and queue_ring_time > 0
                    and ring_duration < queue_ring_time
                )
                if caller_interrupted:
                    add_event("Caller Ended", ev["timestamp"], f"Caller ended the call while agent {format_agent(agent)} was ringing.", 32, f"Caller ended the call while agent {format_agent_html(agent)} was ringing.")
                else:
                    add_event("No Answer", event_time, f"Agent {format_agent(agent)} did not answer, so the queue moved to the next agent.", 32, f"Agent {format_agent_html(agent)} did not answer, so the queue moved to the next agent.")

    valid_hold_time = 0
    active_hold_at = None

    for ev in agent_events:
        event_type = (ev["event_type"] or "").upper()
        agent = ev["agent"] or call["agent"] or "unknown"
        if event_type in ("RING", "RINGNOANSWER", "RINGCANCELED", "ANSWER"):
            continue
        if event_type == "HOLD":
            if not ev["agent"] or not call["answer_time"] or ev["timestamp"] <= call["answer_time"]:
                continue
            display_time = ev["timestamp"]
            active_hold_at = ev["timestamp"]
            add_event("Hold", display_time, f"Agent {format_agent(agent)} placed the caller on hold.", 45, f"Agent {format_agent_html(agent)} placed the caller on hold.")
        elif event_type == "UNHOLD":
            if not ev["agent"] or not call["answer_time"] or ev["timestamp"] <= call["answer_time"]:
                continue
            display_time = ev["timestamp"]
            if active_hold_at:
                try:
                    hold_dt = datetime.strptime(active_hold_at, "%Y-%m-%d %H:%M:%S")
                    unhold_dt = datetime.strptime(ev["timestamp"], "%Y-%m-%d %H:%M:%S")
                    valid_hold_time += max(0, int((unhold_dt - hold_dt).total_seconds()))
                except Exception:
                    pass
                active_hold_at = None
            add_event("Unhold", display_time, f"Agent {format_agent(agent)} resumed the call.", 46, f"Agent {format_agent_html(agent)} resumed the call.")
        elif event_type == "TRANSFER":
            display_time = call["answer_time"] if call["answer_time"] and ev["timestamp"] < call["answer_time"] else ev["timestamp"]
            transfer_from = active_agent or "unknown"
            transfer_to = str(agent or "").strip() or "unknown"
            add_event(
                "Transfer",
                display_time,
                f"{format_agent(transfer_from)} transferred the call to {format_agent(transfer_to)}.",
                55,
                f"{format_agent_html(transfer_from)} transferred the call to {format_agent_html(transfer_to)}."
            )
            if transfer_to != "unknown":
                active_agent = transfer_to
        elif event_type == "ABANDON":
            if has_position_abandon:
                continue
            add_event("Abandoned", ev["timestamp"], f"Caller left the queue before answer. Wait time: {fmt_duration(call['wait_time'])}.", 80)

    if call["answer_time"] and call["status"] == 'ANSWERED' and not any(item["event"] == "Answered" for item in timeline):
        add_event("Answered", answer_display_time, f"Agent {format_agent(answer_agent)} answered the call.", 40, f"Agent {format_agent_html(answer_agent)} answered the call.")

    if call["hangup_time"]:
        status_upper = (call["status"] or "").upper()
        if status_upper == "ABANDONED":
            final_event = "Abandoned"
        elif status_upper == "CANCELLED":
            final_event = "Cancelled"
        elif status_upper == "TIMEOUT":
            final_event = "Timeout"
        elif status_upper == "BUSY":
            final_event = "Busy"
        elif status_upper in ("FAILED", "CONGESTION", "CHANUNAVAIL"):
            final_event = "Failed"
        elif status_upper in ("NO ANSWER", "NO_ANSWER"):
            final_event = "No Answer"
        else:
            final_event = "Hangup"

        hangup_by = (call["hangup_by"] or "").title() if "hangup_by" in call.keys() and call["hangup_by"] else "Unknown"
        if status_upper == "ABANDONED":
            pos = call["last_position"] or call["position"] or 0
            hangup_details = f"Caller left the queue before answer. Last position: #{pos}. Wait time: {fmt_duration(call['wait_time'])}. Final status: {call['status']}."
        else:
            hangup_details = f"Call ended. Final status: {call['status']}."
        if call["talk_time"]:
            hangup_details += f" Talk time: {fmt_duration(call['talk_time'])}."
        if valid_hold_time:
            hangup_details += f" Hold time: {fmt_duration(valid_hold_time)}."
        if hangup_by != "Unknown":
            hangup_details += f" Hangup by: {hangup_by}."
        if call["hangup_reason"]:
            hangup_details += f" Reason: {call['hangup_reason']}."

        add_event(final_event, call["hangup_time"], hangup_details, 90)

    timeline.sort(key=lambda x: (x["time"], x.get("_rank", 50)))
    for item in timeline:
        item.pop("_rank", None)

    agent_attempts = _build_agent_attempts(agent_events, call, extension_names, queue_ring_time)
    
    call_info = {
        "id": call["call_id"],
        "call_id": call["call_id"],
        "uniqueid": call["uniqueid"],
        "linkedid": call["linkedid"],
        "caller": call["caller_number"],
        "caller_number": call["caller_number"],
        "queue_id": call["queue_id"],
        "queue_name": q_name,
        "status": call["status"],
        "agent": call["agent"],
        "wait_time": call["wait_time"],
        "talk_time": call["talk_time"],
        "hangup_reason": call["hangup_reason"],
        "recording_path": call["recording_path"],
        "entry_time": call["entry_time"],
        "answer_time": call["answer_time"],
        "hangup_time": call["hangup_time"],
        "ended_by": call["hangup_by"] or "",
        "final_result": call["status"],
        "initial_position": call["initial_position"] or call["position"] or 0,
        "last_position": call["last_position"] or call["position"] or 0,
        "agent_attempts": agent_attempts,
        "timeline": timeline
    }
    
    conn.close()
    return call_info


def _format_journey_duration(seconds):
    try:
        total = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"


def _parse_cdr_call_path(userfield):
    """Parse the delimiter-safe path written by the generated IVR dialplan."""
    path = []
    for token in str(userfield or "").replace("|", "~").split("~"):
        token = token.strip()
        if not token:
            continue
        if token.startswith("IVR:"):
            parts = token.split(":", 2)
            if len(parts) == 3:
                path.append({"kind": "ivr", "number": parts[1], "name": parts[2] or parts[1]})
        elif token.startswith("DIGIT:"):
            parts = token.split(":", 1)
            if len(parts) == 2:
                path.append({"kind": "digit", "digit": parts[1]})
        elif token.startswith("DEST:"):
            parts = token.split(":", 2)
            if len(parts) == 3:
                path.append({"kind": "destination", "type": parts[1], "number": parts[2]})
        elif token.startswith("FORWARD:"):
            parts = token.split(":", 3)
            if len(parts) == 4:
                path.append({"kind": "forward", "source": parts[1], "reason": parts[2], "target": parts[3]})
    return path


def get_cdr_path_summary(userfield):
    """Return display-safe route metadata for the CDR list row."""
    path = _parse_cdr_call_path(userfield)
    ivrs = [item for item in path if item["kind"] == "ivr"]
    digits = [item for item in path if item["kind"] == "digit"]
    destinations = [item for item in path if item["kind"] == "destination"]
    first_ivr = ivrs[0] if ivrs else {}
    return {
        "recorded": bool(path),
        "ivr_display": " \u2192 ".join(item["name"] for item in ivrs),
        "ivr_number": ivrs[-1]["number"] if ivrs else "",
        "first_ivr_display": first_ivr.get("name", ""),
        "first_ivr_number": first_ivr.get("number", ""),
        "pressed": digits[-1]["digit"] if digits else "",
        "destination_type": destinations[-1]["type"] if destinations else "",
        "destination_number": destinations[-1]["number"] if destinations else ""
    }


def _build_agent_attempts(agent_events, call, extension_names, queue_ring_time):
    attempts = []
    open_attempts = []

    def seconds_between(start, end):
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            return max(0, int((end_dt - start_dt).total_seconds()))
        except Exception:
            return 0

    def find_open(agent):
        for attempt in reversed(open_attempts):
            if attempt["extension"] == agent and not attempt["resolved"]:
                return attempt
        return None

    def ensure_attempt(agent, timestamp):
        agent = str(agent or "").strip()
        if not agent:
            return None
        attempt = find_open(agent)
        if attempt:
            return attempt
        attempt = {
            "extension": agent,
            "agent_name": extension_names.get(agent) or agent,
            "status": "Ringing",
            "status_key": "ringing",
            "ring_started": timestamp,
            "answered_at": "",
            "ring_time": 0,
            "resolved": False
        }
        attempts.append(attempt)
        open_attempts.append(attempt)
        return attempt

    for event in sorted(agent_events, key=lambda item: item["timestamp"] or ""):
        event_type = (event["event_type"] or "").upper()
        agent = str(event["agent"] or "").strip()
        if not agent:
            continue
        timestamp = event["timestamp"] or ""

        if event_type == "RING":
            ensure_attempt(agent, timestamp)
            continue

        if event_type not in ("RINGNOANSWER", "RINGCANCELED", "ANSWER"):
            continue

        attempt = ensure_attempt(agent, timestamp)
        if not attempt:
            continue
        attempt["resolved"] = True
        attempt["ring_time"] = seconds_between(attempt["ring_started"], timestamp)
        if event_type == "ANSWER":
            attempt["status"] = "Answered"
            attempt["status_key"] = "answered"
            attempt["answered_at"] = timestamp
        elif event_type == "RINGNOANSWER":
            # queue_log already distinguishes a timeout/no-answer event from
            # an explicit ring cancellation. Per-agent ring timeouts can be
            # shorter than the queue setting, so do not infer cancellation
            # from the elapsed seconds here.
            attempt["status"] = "No Answer"
            attempt["status_key"] = "no_answer"
        else:
            attempt["status"] = "Cancelled"
            attempt["status_key"] = "cancelled"

    # Queue integrations can persist the final answered state even when the
    # ANSWER queue event is missing from the local event log. Repair the final
    # agent card from the authoritative queue_calls row in that case.
    if str(call["status"] or "").upper().replace("_", " ") == "ANSWERED" and call["agent"]:
        final_agent = str(call["agent"]).strip()
        final_attempt = next(
            (item for item in reversed(attempts) if item["extension"] == final_agent),
            None
        )
        if final_attempt is None:
            final_attempt = ensure_attempt(final_agent, call["answer_time"] or "")
        if final_attempt is not None:
            final_attempt["status"] = "Answered"
            final_attempt["status_key"] = "answered"
            final_attempt["answered_at"] = call["answer_time"] or ""
            final_attempt["ring_time"] = seconds_between(final_attempt["ring_started"], call["answer_time"])

    for attempt in attempts:
        attempt.pop("resolved", None)
        attempt["ring_time_display"] = _format_journey_duration(attempt["ring_time"])
    return attempts


def build_friendly_call_journey(call_info, cdr_record=None):
    """Build the user-facing call journey without exposing raw queue events."""
    if not call_info:
        return call_info

    cdr = cdr_record
    # Legacy fallback records usually have only one CDR row and QueueLog
    # HOLD/UNHOLD markers.  Reuse the same three-duration contract, while
    # explicitly allowing a conservative billsec/talk_time fallback because
    # these records do not contain caller bridge evidence.
    try:
        import cdr_journey
        duration_events = []
        for event in call_info.get("timeline") or []:
            event_name = str(event.get("event") or "").upper()
            if event_name in {"HOLD", "UNHOLD"}:
                duration_events.append({
                    "event_type": event_name,
                    "timestamp": event.get("time") or "",
                })
        duration_call = dict(call_info)
        duration_call["_related_queue_calls"] = [duration_call]
        duration_summary = cdr_journey.calculate_call_durations(
            [dict(cdr)] if cdr is not None else [],
            duration_call,
            duration_events,
            legacy_fallback=True,
        )
        call_info.update({
            "call_time": duration_summary["call_time"],
            "talk_time": duration_summary["talk_time"],
            "hold_time": duration_summary["hold_time"],
            "call_time_display": duration_summary["call_time_display"],
            "talk_time_display": duration_summary["talk_time_display"],
            "hold_time_display": duration_summary["hold_time_display"],
        })
    except Exception as duration_exc:
        # The friendly journey remains available if an old installation has
        # malformed duration data; do not fabricate a Hold value.
        print(f"[call-details] Legacy duration fallback unavailable: {duration_exc}")

    userfield = cdr["userfield"] if cdr is not None and "userfield" in cdr.keys() else ""
    path = _parse_cdr_call_path(userfield)
    start_time = (cdr["start_time"] if cdr is not None and "start_time" in cdr.keys() else "") or call_info.get("entry_time") or ""
    end_time = call_info.get("hangup_time") or (cdr["end_time"] if cdr is not None and "end_time" in cdr.keys() else "") or ""
    ivr_items = [item for item in path if item["kind"] == "ivr"]
    digit_items = [item for item in path if item["kind"] == "digit"]
    destination_items = [item for item in path if item["kind"] == "destination"]
    forward_items = [item for item in path if item["kind"] == "forward"]
    has_transfer = any(
        str(event.get("event") or "").upper() == "TRANSFER"
        for event in (call_info.get("timeline") or [])
    )
    call_info["ivr_display"] = " \u2192 ".join(item["name"] for item in ivr_items)
    call_info["ivr_digit"] = digit_items[-1]["digit"] if digit_items else ""
    call_info["final_destination"] = (
        cdr["dst"] if cdr is not None and "dst" in cdr.keys() else call_info.get("queue_id") or ""
    )
    final_destination = str(call_info["final_destination"] or "").strip()
    final_destination_display = final_destination
    extension_names = {}
    queue_names = {}
    try:
        import db
        queue_names = {
            str(queue.get("queue_number") or "").strip(): str(queue.get("name") or queue.get("queue_name") or "").strip()
            for queue in db.get_queues()
            if str(queue.get("queue_number") or "").strip()
        }
        extension_names = {
            str(extension.get("ext") or "").strip(): str(extension.get("name") or "").strip()
            for extension in db.get_all_extensions()
            if str(extension.get("ext") or "").strip()
        }
        if final_destination in queue_names and queue_names[final_destination]:
            final_destination_display = f"Queue: {queue_names[final_destination]} ({final_destination})"
        elif final_destination in extension_names and extension_names[final_destination]:
            final_destination_display = f"{extension_names[final_destination]} ({final_destination})"
    except Exception:
        pass
    call_info["final_destination_display"] = final_destination_display

    queue_id = str(call_info.get("queue_id") or "").strip()
    queue_name = str(call_info.get("queue_name") or "").strip()
    cdr_context = str(cdr["dcontext"] if cdr is not None and "dcontext" in cdr.keys() else "").strip().lower()
    cdr_app = str(cdr["lastapp"] if cdr is not None and "lastapp" in cdr.keys() else "").strip().lower()
    is_queue_call = bool(queue_id or cdr_context.startswith("queue-") or cdr_app == "queue")
    # Transfer is an event inside the call journey; it does not change the
    # underlying call type. A direct call remains direct and a queue call
    # remains a queue call after the transfer.
    call_info["call_type"] = "queue" if is_queue_call else ("forwarded" if forward_items else "direct")
    call_info["has_transfer"] = has_transfer
    if not is_queue_call:
        call_info["queue_id"] = ""
        call_info["queue_name"] = ""

    def format_extension(extension):
        extension = str(extension or "").strip()
        if not extension:
            return "Unknown"
        name = extension_names.get(extension) or extension
        return f"{name} ({extension})" if name != extension else extension

    call_info["agent_display"] = format_extension(call_info.get("agent")) if call_info.get("agent") else ""
    if has_transfer and call_info.get("transfer_source") and call_info.get("transfer_target"):
        call_info["initial_destination"] = str(call_info["transfer_source"]).strip()
        call_info["initial_destination_display"] = format_extension(call_info["transfer_source"])
        call_info["transfer_target_display"] = format_extension(call_info["transfer_target"])

    journey = []

    for index, item in enumerate(path):
        if item["kind"] == "ivr":
            journey.append({
                "kind": "ivr",
                "title": f"IVR: {item['name']}",
                "subtitle": f"IVR number: {item['number']}",
                "time": start_time if not any(step["kind"] == "ivr" for step in journey) else "",
                "details": []
            })
        elif item["kind"] == "digit":
            # DTMF choices are kept in the raw call data, but are not shown as
            # a separate journey card; the user-facing destination is enough.
            continue
        elif item["kind"] == "forward":
            source = item.get("source") or "unknown"
            target = item.get("target") or "unknown"
            reason = str(item.get("reason") or "").replace("_", " ").title()
            journey.append({
                "kind": "forward",
                "title": "Call forwarded",
                "subtitle": f"{format_extension(source)} forwarded the call to {format_extension(target)}.",
                "time": start_time,
                "details": ([{"label": "Forward type", "value": reason}] if reason else [])
            })

    # Direct, forwarded, and transferred calls are extension journeys, not
    # queue agent attempts. Agent cards are rendered only for queue calls.
    if not is_queue_call:
        direct_step = {
            "kind": "direct",
            "title": "Forwarded call" if forward_items else "Direct call",
            "subtitle": f"{format_extension(call_info.get('caller_number') or call_info.get('caller'))} → {call_info.get('transfer_target_display') if has_transfer and call_info.get('transfer_target_display') else (final_destination_display or 'Unknown destination')}",
            "time": start_time,
            "details": (
                [
                    {"label": "Call type", "value": "Forwarded call" if forward_items else "Direct extension call"},
                    {"label": "Initial destination", "value": call_info.get("initial_destination_display")},
                    {"label": "Transferred to", "value": call_info.get("transfer_target_display")}
                ]
                if has_transfer and call_info.get("transfer_target_display")
                else [
                    {"label": "Call type", "value": "Forwarded call" if forward_items else "Direct extension call"},
                    {"label": "Destination", "value": final_destination_display or "Unknown"}
                ]
            )
        }
        # Direct, forwarded, and transferred calls are extension journeys—not
        # queue agent attempts. Queue calls add the Agent cards below instead.
        journey.append(direct_step)

    attempts = (call_info.get("agent_attempts") or []) if is_queue_call else []
    for attempt in attempts:
        if attempt.get("status_key") == "answered":
            attempt["talk_time_display"] = _format_journey_duration(call_info.get("talk_time"))
    if is_queue_call:
        queue_details = [
            {"label": "Initial position", "value": f"#{call_info.get('initial_position') or 0}"},
            {"label": "Final position", "value": f"#{call_info.get('last_position') or 0}"},
            {"label": "Waiting time", "value": _format_journey_duration(call_info.get("wait_time"))}
        ]
        journey.append({
            "kind": "queue",
            "title": f"Queue: {call_info.get('queue_name') or call_info.get('queue_id') or 'Unknown'}",
            "subtitle": "Queue handling",
            "time": call_info.get("entry_time") or "",
            "details": queue_details,
            "agent_attempts": attempts
        })

    for event in call_info.get("timeline") or []:
        event_name = str(event.get("event") or "").upper()
        if event_name not in {"TRANSFER", "HOLD", "UNHOLD"}:
            continue
        kind = "transfer" if event_name == "TRANSFER" else "hold"
        title = "Call transferred" if event_name == "TRANSFER" else ("Call on hold" if event_name == "HOLD" else "Call resumed")
        journey.append({
            "kind": kind,
            "title": title,
            "subtitle": event.get("details") or "",
            "time": event.get("time") or "",
            "details": []
        })

    status = str(call_info.get("status") or "Unknown")
    ended_by = str(call_info.get("ended_by") or "").title()
    end_details = [{"label": "Final result", "value": status}]
    if ended_by:
        end_details.append({"label": "Ended by", "value": ended_by})
    end_details.append({"label": "Total duration", "value": _format_journey_duration((cdr["duration"] if cdr is not None and "duration" in cdr.keys() else 0))})
    journey.append({
        "kind": "end",
        "title": "Call Ended",
        "subtitle": status,
        "time": end_time,
        "details": end_details
    })

    call_info["journey"] = journey
    call_info["journey_recorded"] = bool(path)
    return call_info

def db_call_transfer_event(uniqueid, target, queue_num=None):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not queue_num:
        c.execute("SELECT queue_id FROM queue_calls WHERE uniqueid = ? OR linkedid = ?", (uniqueid, uniqueid))
        row = c.fetchone()
        queue_num = row["queue_id"] if row else ""

    c.execute("""
        INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
        VALUES (?, ?, 'TRANSFER', ?, ?)
    """, (str(target or ""), queue_num, uniqueid, now_str))
    conn.commit()
    conn.close()


def _store_queue_transfer_event(conn, uniqueid, queue_num, target, timestamp, transfer_type=""):
    """Persist a queue_log transfer once, using target as the event agent."""
    target = str(target or "").strip()
    if not uniqueid or not target:
        return
    exists = conn.execute(
        """
        SELECT COUNT(*) FROM queue_agent_events
        WHERE uniqueid = ? AND queue = ? AND event_type = 'TRANSFER'
          AND agent = ? AND timestamp = ?
        """,
        (uniqueid, queue_num, target, timestamp)
    ).fetchone()[0]
    if not exists:
        conn.execute(
            """
            INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp, transfer_type)
            VALUES (?, ?, 'TRANSFER', ?, ?, ?)
            """,
            (target, queue_num, uniqueid, timestamp, transfer_type or "")
        )
    elif transfer_type:
        conn.execute(
            """
            UPDATE queue_agent_events
            SET transfer_type = ?
            WHERE uniqueid = ? AND queue = ? AND event_type = 'TRANSFER'
              AND agent = ? AND timestamp = ?
              AND COALESCE(transfer_type, '') = ''
            """,
            (transfer_type, uniqueid, queue_num, target, timestamp)
        )


def sync_recent_transfer_events(uniqueid=None, max_bytes=2 * 1024 * 1024):
    """Backfill recent BLIND/ATTENDED transfer events already past the offset."""
    log_file = "/var/log/asterisk/queue_log"
    if not os.path.exists(log_file):
        return
    try:
        file_size = os.path.getsize(log_file)
        with open(log_file, "r", errors="replace") as handle:
            handle.seek(max(0, file_size - max_bytes))
            if handle.tell() > 0:
                handle.readline()
            lines = handle.readlines()
        conn = get_db_connection()
        import datetime as dt_module
        for line in lines:
            parts = line.strip().split("|")
            if len(parts) < 6 or parts[4] not in ("BLINDTRANSFER", "ATTENDEDTRANSFER"):
                continue
            callid = parts[1]
            if uniqueid and callid != uniqueid:
                continue
            try:
                timestamp = dt_module.datetime.fromtimestamp(int(parts[0]), PBX_TIMEZONE).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            transfer_type = "Attended Transfer" if parts[4] == "ATTENDEDTRANSFER" else "Blind Transfer"
            _store_queue_transfer_event(conn, callid, parts[2], parts[5], timestamp, transfer_type)
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[queue-log] Could not backfill transfer events: {exc}")

def _sync_queue_log_to_db_locked():
    log_file = "/var/log/asterisk/queue_log"
    offset_file = "/root/RCM_7021/queue_log_new.offset"
    state_file = offset_file + ".state"
    
    if not os.path.exists(log_file):
        return
        
    offset = 0
    if os.path.exists(offset_file):
        try:
            with open(offset_file, 'r') as f:
                offset = int(f.read().strip())
        except Exception:
            offset = 0
            
    try:
        log_size = os.path.getsize(log_file)
        source_head = ""
        try:
            with open(log_file, "rb") as source_handle:
                source_head = hashlib.sha1(source_handle.read(512)).hexdigest()
        except (OSError, TypeError):
            pass
        saved_state = {}
        try:
            with open(state_file, "r") as state_handle:
                saved_state = json.load(state_handle)
        except (OSError, ValueError, TypeError):
            saved_state = {}
        source_changed = bool(saved_state.get("head_hash") and source_head and saved_state.get("head_hash") != source_head)
        # Reset on truncation, inode rotation, or a changed file prefix. The
        # prefix check catches a rotated file that is already larger than the
        # old offset.
        if offset > log_size or source_changed or not source_head:
            offset = 0
            try:
                with open(offset_file, 'w') as f:
                    f.write("0")
                try:
                    os.chmod(offset_file, 0o666)
                except Exception:
                    pass
            except Exception as e:
                print(f"Error resetting offset file: {e}")
    except Exception:
        pass
            
    try:
        with open(log_file, 'r') as f:
            f.seek(offset)
            pending = f.read()
            last_newline = pending.rfind("\n")
            if last_newline < 0:
                # Asterisk normally terminates lines, but test/legacy writers
                # may leave the final valid record without a newline. Keep a
                # genuinely incomplete fragment for the next pass.
                if pending.count("|") < 4:
                    return
                complete = pending
            else:
                trailing = pending[last_newline + 1:]
                complete = pending if trailing.count("|") >= 4 else pending[:last_newline + 1]
            f.seek(offset)
            complete = f.read(len(complete))
            new_offset = f.tell()
            lines = complete.splitlines()
    except Exception as e:
        print(f"Error reading queue_log: {e}")
        return
        
    if not lines:
        return
        
    conn = get_db_connection()
    c = conn.cursor()
    
    import datetime as dt_module
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
            
        ts_str = parts[0]
        callid = parts[1]
        queuename = parts[2]
        agent = parts[3]
        event = parts[4]
        args = parts[5:] + [""] * 5
        
        agent_ext = agent
        if "/" in agent:
            agent_ext = agent.split("/")[-1].split("@")[0]
            
        try:
            epoch = int(ts_str)
            dt_str = dt_module.datetime.fromtimestamp(epoch, PBX_TIMEZONE).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            dt_str = dt_module.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        if event == "ENTERQUEUE":
            # Fix: Parse Asterisk queue_log ENTERQUEUE arguments.
            # Format: ENTERQUEUE|url|callerid|position|calleridname
            # Fallback/alternative checks to retrieve the real queue position and caller ID
            caller = ""
            pos = 1
            if len(args) >= 3 and args[2].isdigit():
                caller = args[1]
                pos = int(args[2])
            elif len(args) >= 2:
                if args[0].isdigit() and args[1].isdigit():
                    val0 = int(args[0])
                    val1 = int(args[1])
                    if val0 < val1:
                        pos = val0
                        caller = args[1]
                    else:
                        pos = val1
                        caller = args[0]
                elif args[0].isdigit():
                    pos = int(args[0])
                    caller = args[1]
                elif args[1].isdigit():
                    pos = int(args[1])
                    caller = args[0]
                else:
                    caller = args[0]
                    pos = 1
            elif len(args) == 1:
                caller = args[0]
                pos = 1
            else:
                caller = "Unknown"
                pos = 1
            
            c.execute("SELECT queue_name FROM queues WHERE queue_number = ?", (queuename,))
            qrow = c.fetchone()
            q_name = qrow["queue_name"] if qrow else queuename
            
            c.execute("""
            INSERT INTO queue_calls (uniqueid, linkedid, caller_number, queue_id, queue_name, entry_time, status, initial_position, last_position)
            VALUES (?, ?, ?, ?, ?, ?, 'ENTERED', ?, ?)
            ON CONFLICT(uniqueid, queue_id) DO UPDATE SET
                caller_number=excluded.caller_number,
                entry_time=excluded.entry_time,
                status='ENTERED',
                initial_position=excluded.initial_position,
                last_position=excluded.last_position
            """, (callid, callid, caller, queuename, q_name, dt_str, pos, pos))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE event_type = 'ENTERQUEUE' AND uniqueid = ?", (callid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'ENTERQUEUE', ?, ?)
                """, (caller, queuename, callid, dt_str))
                
            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = 'ENTERQUEUE'", (callid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, 'ENTERQUEUE', ?)
                """, (callid, queuename, pos, dt_str))
            
        elif event == "CONNECT":
            wait_time = int(args[0]) if args[0].isdigit() else 0
            # Get initial position
            c.execute("SELECT initial_position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            pos = crow["initial_position"] if crow else 1
            
            c.execute("""
            UPDATE queue_calls SET
                answer_time = ?,
                status = 'ANSWERED',
                agent = ?,
                wait_time = ?,
                last_position = ?
            WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
            """, (dt_str, agent_ext, wait_time, pos, callid))

            c.execute("""
            UPDATE queue_live SET
                state = 'TALKING',
                agent = ?,
                position = 0,
                last_update = CURRENT_TIMESTAMP
            WHERE call_id = ?
            """, (agent_ext, callid))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'ANSWER' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'ANSWER', ?, ?)
                """, (agent_ext, queuename, callid, dt_str))
                
            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = 'CONNECT'", (callid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, 'CONNECT', ?)
                """, (callid, queuename, pos, dt_str))
                
        elif event in ("COMPLETEAGENT", "COMPLETECALLER"):
            wait_time = int(args[0]) if args[0].isdigit() else 0
            talk_time = int(args[1]) if args[1].isdigit() else 0
            hangup_by = "AGENT" if event == "COMPLETEAGENT" else "CALLER"
            
            c.execute("SELECT last_position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            pos = crow["last_position"] if (crow and crow["last_position"]) else 1
            
            c.execute("""
            UPDATE queue_calls SET
                answer_time = COALESCE(datetime(entry_time, '+' || ? || ' seconds'), answer_time),
                hangup_time = ?,
                status = 'ANSWERED',
                agent = ?,
                wait_time = ?,
                talk_time = ?,
                hangup_reason = ?,
                hangup_by = ?,
                last_position = ?
            WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
            """, (wait_time, dt_str, agent_ext, wait_time, talk_time, event, hangup_by, pos, callid))

            c.execute("DELETE FROM queue_live WHERE call_id = ?", (callid,))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'HANGUP' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'HANGUP', ?, ?)
                """, (agent_ext, queuename, callid, dt_str))
                
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'COMPLETE' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'COMPLETE', ?, ?)
                """, (agent_ext, queuename, callid, dt_str))
                
        elif event == "ABANDON":
            pos = int(args[0]) if args[0].isdigit() else 1
            orig_pos = int(args[1]) if args[1].isdigit() else 1
            wait_time = int(args[2]) if args[2].isdigit() else 0
            c.execute("""
            UPDATE queue_calls SET
                hangup_time = ?,
                status = 'ABANDONED',
                wait_time = ?,
                hangup_reason = 'ABANDON',
                hangup_by = 'CALLER',
                initial_position = ?,
                last_position = ?
            WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
            """, (dt_str, wait_time, orig_pos, pos, callid))

            c.execute("DELETE FROM queue_live WHERE call_id = ?", (callid,))
            
            c.execute("SELECT caller_number FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            caller = crow["caller_number"] if crow else ""
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE event_type = 'ABANDON' AND uniqueid = ?", (callid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'ABANDON', ?, ?)
                """, (caller, queuename, callid, dt_str))
                
            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = 'ABANDON'", (callid,))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, 'ABANDON', ?)
                """, (callid, queuename, pos, dt_str))
            
        elif event in ("EXITWITHTIMEOUT", "EXITEMPTY"):
            wait_time = int(args[2]) if args[2].isdigit() else 0
            status = 'TIMEOUT' if event == 'EXITWITHTIMEOUT' else 'NO ANSWER'
            
            c.execute("SELECT last_position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            pos = crow["last_position"] if (crow and crow["last_position"]) else 1
            
            c.execute("""
            UPDATE queue_calls SET
                hangup_time = ?,
                status = ?,
                wait_time = ?,
                hangup_reason = ?,
                hangup_by = 'CALLER',
                last_position = ?
            WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
            """, (dt_str, status, wait_time, event, pos, callid))

            c.execute("DELETE FROM queue_live WHERE call_id = ?", (callid,))

            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = ?", (callid, event))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """, (callid, queuename, pos, event, dt_str))
            
        elif event == "EXITWITHKEY":
            wait_time = int(args[3]) if args[3].isdigit() else 0
            
            c.execute("SELECT last_position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            pos = crow["last_position"] if (crow and crow["last_position"]) else 1
            
            c.execute("""
            UPDATE queue_calls SET
                hangup_time = ?,
                status = 'CANCELLED',
                wait_time = ?,
                hangup_reason = ?,
                hangup_by = 'CALLER',
                last_position = ?
            WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
            """, (dt_str, wait_time, event, pos, callid))

            c.execute("DELETE FROM queue_live WHERE call_id = ?", (callid,))

            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = ?", (callid, event))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """, (callid, queuename, pos, event, dt_str))
            
        elif event == "RINGNOANSWER":
            c.execute("SELECT last_position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            pos = crow["last_position"] if (crow and crow["last_position"]) else 1
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'RINGNOANSWER' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'RINGNOANSWER', ?, ?)
                """, (agent_ext, queuename, callid, dt_str))
                
            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = 'RINGNOANSWER' AND timestamp = ?", (callid, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, 'RINGNOANSWER', ?)
                """, (callid, queuename, pos, dt_str))

        elif event == "RINGCANCELED":
            c.execute("SELECT last_position FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
            crow = c.fetchone()
            pos = crow["last_position"] if (crow and crow["last_position"]) else 1
            
            # Store in queue_call_positions
            c.execute("SELECT COUNT(*) FROM queue_call_positions WHERE uniqueid = ? AND event = 'RINGCANCELED' AND timestamp = ?", (callid, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_call_positions (uniqueid, queue, position, event, timestamp)
                VALUES (?, ?, ?, 'RINGCANCELED', ?)
                """, (callid, queuename, pos, dt_str))
                
            # Store in queue_agent_events
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'RINGCANCELED' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
                VALUES (?, ?, 'RINGCANCELED', ?, ?)
                """, (agent_ext, queuename, callid, dt_str))

        elif event in ("BLINDTRANSFER", "ATTENDEDTRANSFER"):
            # queue_log stores the transfer target in the first argument.
            # Keep the target in the event row; get_call_details_timeline uses
            # the active queue agent as the transfer source.
            target = args[0] if args else ""
            transfer_type = "Attended Transfer" if event == "ATTENDEDTRANSFER" else "Blind Transfer"
            _store_queue_transfer_event(c, callid, queuename, target, dt_str, transfer_type)
            
        elif event == "ADDMEMBER":
            c.execute("""
            INSERT INTO queue_agents (extension, agent_name, queue_id, type, status, login_time)
            VALUES (?, ?, ?, 'DYNAMIC', 'AVAILABLE', ?)
            ON CONFLICT(extension, queue_id) DO UPDATE SET
                status='AVAILABLE',
                login_time=?
            """, (agent_ext, agent_ext, queuename, dt_str, dt_str))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'LOGIN' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES (?, ?, 'LOGIN', ?)
                """, (agent_ext, queuename, dt_str))
                
        elif event == "REMOVEMEMBER":
            c.execute("""
            UPDATE queue_agents SET
                status='OFFLINE',
                logout_time=?
            WHERE extension = ? AND queue_id = ?
            """, (dt_str, agent_ext, queuename))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'LOGOUT' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES (?, ?, 'LOGOUT', ?)
                """, (agent_ext, queuename, dt_str))
                
        elif event == "PAUSE":
            c.execute("""
            UPDATE queue_agents SET status='PAUSED' WHERE extension = ? AND queue_id = ?
            """, (agent_ext, queuename))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'PAUSE' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES (?, ?, 'PAUSE', ?)
                """, (agent_ext, queuename, dt_str))
                
        elif event == "UNPAUSE":
            c.execute("""
            UPDATE queue_agents SET status='AVAILABLE' WHERE extension = ? AND queue_id = ?
            """, (agent_ext, queuename))
            
            c.execute("SELECT COUNT(*) FROM queue_agent_events WHERE agent = ? AND queue = ? AND event_type = 'UNPAUSE' AND timestamp = ?", (agent_ext, queuename, dt_str))
            if c.fetchone()[0] == 0:
                c.execute("""
                INSERT INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES (?, ?, 'UNPAUSE', ?)
                """, (agent_ext, queuename, dt_str))
                
    conn.commit()
    conn.close()
    
    try:
        with open(offset_file, 'w') as f:
            f.write(str(new_offset))
        try:
            with open(state_file, "w") as state_handle:
                json.dump({"head_hash": source_head, "size": new_offset}, state_handle)
        except OSError:
            pass
        try:
            os.chmod(offset_file, 0o666)
        except Exception:
            pass
    except Exception as e:
        print(f"Error saving offset file: {e}")


def sync_queue_log_to_db():
    """Serialize QueueLog imports across web requests and collector workers."""
    with _QUEUE_LOG_SYNC_LOCK:
        try:
            import fcntl
            lock_path = "/root/RCM_7021/queue_log_new.offset.lock"
            with open(lock_path, "a+") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    return _sync_queue_log_to_db_locked()
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            return _sync_queue_log_to_db_locked()

def get_active_queue_channels_from_asterisk():
    import subprocess
    import sys
    
    if "unittest" in sys.modules or "pytest" in sys.modules or "/tmp" in DB_PATH or "TemporaryDirectory" in DB_PATH:
        return {}
        
    try:
        res = subprocess.run("asterisk -rx \"core show channels concise\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
    except Exception as e:
        print(f"Error reading active queue channels: {e}")
        return {}
        
    if res.returncode != 0 or not res.stdout:
        return {}
        
    channels = []
    linked_agents = {}
    
    for line in res.stdout.strip().splitlines():
        parts = line.split("!")
        if len(parts) < 14:
            continue
            
        channel = parts[0]
        application = parts[5]
        app_data = parts[6]
        caller = parts[7]
        duration = 0
        try:
            duration = int(parts[11] or 0)
        except Exception:
            pass
        linkedid = parts[12]
        uniqueid = parts[13]
        
        ext = ""
        if "/" in channel:
            ext = channel.split("/", 1)[1].split("-", 1)[0].split("@", 1)[0]
            
        channels.append({
            "channel": channel,
            "application": application,
            "app_data": app_data,
            "caller": caller,
            "duration": duration,
            "linkedid": linkedid,
            "uniqueid": uniqueid,
            "ext": ext
        })
        
    for ch in channels:
        if ch["application"] == "AppQueue" and ch["ext"]:
            linked_agents[ch["linkedid"]] = ch["ext"]
            
    queue_calls = {}
    for ch in channels:
        if ch["application"] != "Queue":
            continue
        qnum = (ch["app_data"] or "").split(",", 1)[0] or ""
        if not qnum:
            qnum = ch["channel"].split("-", 1)[1] if ch["channel"].startswith("queue-") else ""
        if not qnum:
            continue
            
        queue_calls[ch["uniqueid"]] = {
            "call_id": ch["uniqueid"],
            "queue": qnum,
            "caller": ch["caller"] or "Unknown",
            "agent": linked_agents.get(ch["linkedid"], ""),
            "duration": ch["duration"],
            "linkedid": ch["linkedid"]
        }
        
    return queue_calls

def get_live_dashboard_status():
    try:
        sync_queue_log_to_db()
    except Exception as e:
        print(f"Error syncing queue log in get_live_dashboard_status: {e}")
        
    # 1. Seed static agents from config to SQLite first
    conn = get_db_connection()
    c = conn.cursor()
    try:
        import db
        config_queues = db.get_queues()
        extension_names = {e["ext"]: e.get("name") or e["ext"] for e in db.get_all_extensions()}
        for cq in config_queues:
            qnum = cq.get("queue_number")
            static_agents = cq.get("static_agents", [])
            for agent in static_agents:
                c.execute("SELECT COUNT(*) FROM queue_agents WHERE extension = ? AND queue_id = ?", (agent, qnum))
                exists = c.fetchone()[0] > 0
                if not exists:
                    agent_name = extension_names.get(agent) or "Agent"
                    c.execute("""
                        INSERT INTO queue_agents (extension, agent_name, queue_id, type, status)
                        VALUES (?, ?, ?, 'STATIC', 'OFFLINE')
                    """, (agent, agent_name, qnum))
        conn.commit()
    except Exception as e:
        print(f"Error syncing static agents from config to SQLite: {e}")
    finally:
        conn.close()
        
    # 2. Unconditionally reconcile database agent status with Asterisk's real state after seeding static agents
    try:
        reconcile_with_asterisk_state()
    except Exception as e:
        print(f"Error in state reconciliation: {e}")
        
    # 3. Re-open connection to read live state
    conn = get_db_connection()
    c = conn.cursor()

        
    c.execute("SELECT * FROM queues")
    db_queues = c.fetchall()
    
    queues = {}
    active_calls = []
    
    now = datetime.now()
    today_start = now.strftime("%Y-%m-%d") + " 00:00:00"
    asterisk_queue_calls = get_active_queue_channels_from_asterisk()
    
    for q in db_queues:
        qnum = q["queue_number"]
        qname = q["queue_name"]
        servicelevel = q["servicelevel"] if "servicelevel" in q.keys() else 30
        
        c.execute("""
            SELECT 
                SUM(CASE WHEN status = 'ANSWERED' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status IN ('ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT') THEN 1 ELSE 0 END) as abandoned,
                AVG(wait_time) as avg_hold,
                AVG(CASE WHEN status = 'ANSWERED' THEN talk_time ELSE NULL END) as avg_talk,
                SUM(CASE WHEN status = 'ANSWERED' AND wait_time <= ? THEN 1 ELSE 0 END) as sla_met
            FROM queue_calls
            WHERE queue_id = ? AND entry_time >= ?
        """, (servicelevel, qnum, today_start))
        
        stats = c.fetchone()
        completed = stats["completed"] or 0
        abandoned = stats["abandoned"] or 0
        total = completed + abandoned
        avg_hold = int(stats["avg_hold"] or 0)
        avg_talk = int(stats["avg_talk"] or 0)
        
        sla_pct = 100.0
        if total > 0:
            sla_pct = round(((stats["sla_met"] or 0) / total) * 100, 1)

            
        c.execute("SELECT * FROM queue_live WHERE queue = ? ORDER BY position ASC", (qnum,))
        live_rows = c.fetchall()
        
        entries = []
        q_calls_waiting = 0
        
        for lr in live_rows:
            wait_dur = 0
            if lr["start_time"]:
                try:
                    start_dt = datetime.strptime(lr["start_time"], "%Y-%m-%d %H:%M:%S")
                    wait_dur = int((now - start_dt).total_seconds())
                except Exception:
                    pass
            
            if lr["state"] in ('WAITING', 'RINGING'):
                q_calls_waiting += 1
                entries.append({
                    "position": lr["position"],
                    "callerid": lr["caller"],
                    "wait": wait_dur
                })
                
            state_upper = lr["state"].upper()
            active_calls.append({
                "id": lr["call_id"],
                "call_id": lr["call_id"],
                "caller": lr["caller"],
                "caller_number": lr["caller"],
                "queue": qnum,
                "queue_id": qnum,
                "queue_name": qname or qnum,
                "wait": wait_dur if state_upper in ('WAITING', 'RINGING') else 0,
                "position": lr["position"] if state_upper in ('WAITING', 'RINGING') else 0,
                "agent": lr["agent"] or "",
                "duration": wait_dur,
                "status": state_upper,
                "state": state_upper,
                "entry_time": lr["start_time"],
                "start_time": lr["start_time"],
                "last_update": lr["last_update"]
            })
            
        live_call_ids = {lr["call_id"] for lr in live_rows}
        live_talking_count = sum(1 for lr in live_rows if (lr["state"] or "").upper() == "TALKING")

        # Get active talking calls for this queue from queue_calls
        c.execute("""
            SELECT uniqueid, caller_number, agent, answer_time 
            FROM queue_calls 
            WHERE queue_id = ? 
              AND status = 'ANSWERED' 
              AND hangup_time IS NULL
        """, (qnum,))
        talking_rows = c.fetchall()
        
        q_calls_talking = live_talking_count
        for tr in talking_rows:
            talk_dur = 0
            if tr["answer_time"]:
                try:
                    ans_dt = datetime.strptime(tr["answer_time"], "%Y-%m-%d %H:%M:%S")
                    talk_dur = int((now - ans_dt).total_seconds())
                except Exception:
                    pass
            if tr["uniqueid"] in live_call_ids:
                continue
            q_calls_talking += 1
            active_calls.append({
                "id": tr["uniqueid"],
                "call_id": tr["uniqueid"],
                "caller": tr["caller_number"],
                "caller_number": tr["caller_number"],
                "queue": qnum,
                "queue_id": qnum,
                "queue_name": qname or qnum,
                "wait": 0,
                "position": 0,
                "agent": tr["agent"] or "",
                "duration": talk_dur,
                "status": "TALKING",
                "state": "TALKING",
                "entry_time": tr["answer_time"],
                "start_time": tr["answer_time"],
                "last_update": tr["answer_time"]
            })

        existing_active_ids = {c["call_id"] for c in active_calls}
        fallback_talking = 0
        for uid, ch in asterisk_queue_calls.items():
            if ch["queue"] != qnum or uid in existing_active_ids:
                continue
            fallback_talking += 1
            
            caller = ch["caller"]
            agent = ch["agent"]
            answer_time = None
            c.execute("SELECT caller_number, agent, answer_time FROM queue_calls WHERE uniqueid = ?", (uid,))
            db_call = c.fetchone()
            if db_call:
                caller = db_call["caller_number"] or caller
                agent = db_call["agent"] or agent
                answer_time = db_call["answer_time"]
                
            active_calls.append({
                "id": uid,
                "call_id": uid,
                "caller": caller,
                "caller_number": caller,
                "queue": qnum,
                "queue_id": qnum,
                "queue_name": qname or qnum,
                "wait": 0,
                "position": 0,
                "agent": agent or "",
                "duration": ch["duration"],
                "status": "TALKING",
                "state": "TALKING",
                "entry_time": answer_time,
                "start_time": answer_time,
                "last_update": None
            })
        q_calls_talking += fallback_talking
        c.execute("SELECT * FROM queue_agents WHERE queue_id = ? AND status != 'OFFLINE'", (qnum,))
        agents = c.fetchall()
        
        c.execute("SELECT * FROM queue_agents WHERE queue_id = ?", (qnum,))
        all_agents = c.fetchall()
        
        def clean_agent_ext(agent):
            agent = str(agent or "").strip()
            if "/" in agent:
                agent = agent.split("/")[-1]
            agent = agent.split("@")[0]
            if "-" in agent:
                agent = agent.split("-")[0]
            return agent

        def map_agent_details(agent_list):
            mapped = []
            for a in agent_list:
                ext = a["extension"]
                name = a["agent_name"]
                
                state_val = 0
                paused_val = 0
                status_val = 0
                status_text = 'Unknown'
                
                status_upper = a["status"].upper() if a["status"] else "UNKNOWN"
                if status_upper == 'PAUSED':
                    state_val = 1
                    paused_val = 1
                    status_val = 2
                    status_text = 'Pause'
                elif status_upper in ('NOT IN USE', 'AVAILABLE'):
                    state_val = 1
                    paused_val = 0
                    status_val = 1
                    status_text = 'Idle'
                elif status_upper == 'IN USE':
                    state_val = 2
                    paused_val = 0
                    status_val = 2
                    status_text = 'Busy'
                elif status_upper == 'BUSY':
                    state_val = 3
                    paused_val = 0
                    status_val = 3
                    status_text = 'Busy'
                elif status_upper == 'RINGING':
                    state_val = 6
                    paused_val = 0
                    status_val = 6
                    status_text = 'Ringing'
                elif status_upper in ('UNAVAILABLE', 'OFFLINE'):
                    state_val = 5
                    paused_val = 0
                    status_val = 5
                    status_text = 'Unavailable'
                elif status_upper == 'UNKNOWN':
                    state_val = 0
                    paused_val = 0
                    status_val = 0
                    status_text = 'Unknown'
                else:
                    state_val = 4
                    paused_val = 0
                    status_val = 4
                    status_text = 'Unmonitored'
                    
                c.execute("""
                    SELECT timestamp FROM queue_agent_events 
                    WHERE agent = ? AND queue = ? 
                    ORDER BY timestamp DESC LIMIT 1
                """, (ext, qnum))
                evt_row = c.fetchone()
                status_duration = 0
                if evt_row and evt_row["timestamp"]:
                    try:
                        evt_dt = datetime.strptime(evt_row["timestamp"], "%Y-%m-%d %H:%M:%S")
                        status_duration = int((now - evt_dt).total_seconds())
                    except Exception:
                        pass
                        
                c.execute("""
                    SELECT COUNT(*) FROM queue_calls 
                    WHERE (agent = ? OR agent = ?)
                      AND queue_id = ?
                      AND status = 'ANSWERED'
                      AND entry_time >= ?
                """, (ext, f"PJSIP/{ext}", qnum, today_start))
                calls_taken = c.fetchone()[0] or 0
                
                caller_id = ""
                call_duration = 0
                for tr in talking_rows:
                    if clean_agent_ext(tr["agent"]) == ext:
                        caller_id = tr["caller_number"]
                        if tr["answer_time"]:
                            try:
                                ans_dt = datetime.strptime(tr["answer_time"], "%Y-%m-%d %H:%M:%S")
                                call_duration = int((now - ans_dt).total_seconds())
                            except Exception:
                                pass
                        break
                        
                if not caller_id:
                    for lr in live_rows:
                        state = (lr["state"] or "").upper()
                        if state in ('RINGING', 'TALKING') and clean_agent_ext(lr["agent"]) == ext:
                            caller_id = lr["caller"]
                            if lr["start_time"]:
                                try:
                                    start_dt = datetime.strptime(lr["start_time"], "%Y-%m-%d %H:%M:%S")
                                    call_duration = int((now - start_dt).total_seconds())
                                except Exception:
                                    pass
                            break

                if not caller_id:
                    for ac in active_calls:
                        if ac.get("queue_id") != qnum and ac.get("queue") != qnum:
                            continue
                        if clean_agent_ext(ac.get("agent")) != ext:
                            continue
                        caller_id = ac.get("caller_number") or ac.get("caller") or ""
                        call_duration = int(ac.get("duration") or 0)
                        break
                
                pause_duration = 0
                if status_upper == 'PAUSED' and status_duration > 0:
                    pause_duration = status_duration
                    
                login_duration = None if (a["type"] or "").upper() == "STATIC" else 0
                if (a["type"] or "").upper() != "STATIC" and status_upper != 'OFFLINE' and a["login_time"]:
                    try:
                        login_dt = datetime.strptime(a["login_time"], "%Y-%m-%d %H:%M:%S")
                        dur = int((now - login_dt).total_seconds())
                        if dur >= 0:
                            login_duration = dur
                    except Exception:
                        pass
                
                mapped.append({
                    "id": a["agent_id"],
                    "agent_id": a["agent_id"],
                    "name": name,
                    "agent_name": name,
                    "location": f"PJSIP/{ext}",
                    "extension": ext,
                    "queue_id": qnum,
                    "state": state_val,
                    "status": status_val,
                    "status_text": status_text,
                    "paused": paused_val,
                    "paused_reason": "Break" if paused_val else "",
                    "status_duration": status_duration,
                    "calls_taken": calls_taken,
                    "type": a["type"],
                    "login_time": a["login_time"],
                    "logout_time": a["logout_time"],
                    "caller_id": caller_id,
                    "call_duration": call_duration,
                    "login_duration": login_duration,
                    "pause_duration": pause_duration
                })
            return mapped
            
        members = map_agent_details(agents)
        roster = map_agent_details(all_agents)
            
        queues[qnum] = {
            "name": qname,
            "calls": q_calls_waiting,
            "talking": q_calls_talking,
            "completed": completed,
            "abandoned": abandoned,
            "holdtime": avg_hold,
            "talktime": avg_talk,
            "servicelevelperf": sla_pct,
            "servicelevel": servicelevel,
            "members": members,
            "roster": roster,
            "entries": entries
        }
        
    conn.close()
    active_calls.sort(key=lambda x: (x["status"] == 'Waiting', x["duration"]), reverse=True)
    
    return {
        "queues": queues,
        "active_calls": active_calls
    }

def _queue_detail_bounds(filters):
    if not filters:
        return None, None
    start_value = str(filters.get("date_from") or "").strip()
    end_value = str(filters.get("date_to") or "").strip()
    if not start_value and not end_value:
        return None, None
    start_value = (start_value or "1900-01-01") + " " + (str(filters.get("time_from") or "00:00") + (":00" if len(str(filters.get("time_from") or "00:00")) == 5 else ""))
    end_time = str(filters.get("time_to") or "23:59")
    end_value = (end_value or "2999-12-31") + " " + (end_time + (":59" if len(end_time) == 5 else ""))
    try:
        return datetime.strptime(start_value, "%Y-%m-%d %H:%M:%S"), datetime.strptime(end_value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None, None


def get_queue_sessions(queue_num, filters=None):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Query all events for the queue
    c.execute("""
        SELECT agent, event_type, timestamp 
        FROM queue_agent_events 
        WHERE queue = ? AND event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE')
        ORDER BY agent, timestamp ASC
    """, (queue_num,))
    rows = c.fetchall()
    conn.close()
    
    import datetime as dt_module
    
    # Group events by agent
    agent_events = {}
    for r in rows:
        ag = r["agent"]
        if ag not in agent_events:
            agent_events[ag] = []
        agent_events[ag].append(r)
        
    sessions = []
    
    for ag, evts in agent_events.items():
        current_session = None
        pause_start = None
        
        for e in evts:
            evt_type = e["event_type"]
            try:
                evt_dt = dt_module.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
                evt_ts = int(evt_dt.timestamp())
            except Exception:
                continue
                
            if evt_type == 'LOGIN':
                if current_session:
                    # Close previous session if unclosed
                    current_session["logout_time"] = evt_ts
                    current_session["total_online_time"] = max(0, evt_ts - current_session["login_time"])
                    current_session["available_time"] = max(0, current_session["total_online_time"] - current_session["pause_time"])
                    sessions.append(current_session)
                current_session = {
                    "agent": ag,
                    "queuename": queue_num,
                    "login_time": evt_ts,
                    "logout_time": 0,
                    "total_online_time": 0,
                    "pause_time": 0,
                    "available_time": 0
                }
                pause_start = None
            elif evt_type == 'LOGOUT':
                if current_session:
                    current_session["logout_time"] = evt_ts
                    if pause_start:
                        current_session["pause_time"] += max(0, evt_ts - pause_start)
                        pause_start = None
                    current_session["total_online_time"] = max(0, evt_ts - current_session["login_time"])
                    current_session["available_time"] = max(0, current_session["total_online_time"] - current_session["pause_time"])
                    sessions.append(current_session)
                    current_session = None
            elif evt_type == 'PAUSE':
                if current_session and not pause_start:
                    pause_start = evt_ts
            elif evt_type == 'UNPAUSE':
                if current_session and pause_start:
                    current_session["pause_time"] += max(0, evt_ts - pause_start)
                    pause_start = None
                    
        # If there is still an active session, mark as active (logout_time = 0)
        if current_session:
            now_ts = int(dt_module.datetime.now().timestamp())
            current_session["total_online_time"] = max(0, now_ts - current_session["login_time"])
            if pause_start:
                current_session["pause_time"] += max(0, now_ts - pause_start)
            current_session["available_time"] = max(0, current_session["total_online_time"] - current_session["pause_time"])
            sessions.append(current_session)
            
    bounds_start, bounds_end = _queue_detail_bounds(filters)
    if bounds_start and bounds_end:
        clipped = []
        for session in sessions:
            original_login = _local_datetime_from_epoch(session["login_time"])
            original_logout = _local_datetime_from_epoch(session["logout_time"]) if session["logout_time"] else datetime.now(PBX_TIMEZONE).replace(tzinfo=None)
            if original_logout < bounds_start or original_login > bounds_end:
                continue
            login_dt = max(original_login, bounds_start)
            logout_dt = min(original_logout, bounds_end)
            session["login_time"] = _local_epoch(login_dt)
            session["logout_time"] = _local_epoch(logout_dt) if session["logout_time"] else 0
            session["total_online_time"] = max(0, int((logout_dt - login_dt).total_seconds()))
            session["pause_time"] = min(session["pause_time"], session["total_online_time"])
            session["available_time"] = max(0, session["total_online_time"] - session["pause_time"])
            clipped.append(session)
        sessions = clipped

    # Sort by login_time descending
    sessions.sort(key=lambda x: x["login_time"], reverse=True)
    return sessions[:100]

def get_queue_pauses(queue_num, filters=None):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Query all events for the queue of types PAUSE and UNPAUSE
    c.execute("""
        SELECT agent, event_type, timestamp 
        FROM queue_agent_events 
        WHERE queue = ? AND event_type IN ('PAUSE', 'UNPAUSE')
        ORDER BY agent, timestamp ASC
    """, (queue_num,))
    rows = c.fetchall()
    conn.close()
    
    import datetime as dt_module
    
    agent_events = {}
    for r in rows:
        ag = r["agent"]
        if ag not in agent_events:
            agent_events[ag] = []
        agent_events[ag].append(r)
        
    pauses = []
    
    for ag, evts in agent_events.items():
        pause_start_ts = None
        
        for e in evts:
            evt_type = e["event_type"]
            try:
                evt_dt = dt_module.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
                evt_ts = int(evt_dt.timestamp())
            except Exception:
                continue
                
            if evt_type == 'PAUSE':
                if pause_start_ts:
                    # Record pause even if unpaused previously (e.g. consecutive pause without unpause)
                    pauses.append({
                        "agent": ag,
                        "queuename": queue_num,
                        "pause_time": pause_start_ts,
                        "unpause_time": evt_ts,
                        "reason": "Break"
                    })
                pause_start_ts = evt_ts
            elif evt_type == 'UNPAUSE':
                if pause_start_ts:
                    pauses.append({
                        "agent": ag,
                        "queuename": queue_num,
                        "pause_time": pause_start_ts,
                        "unpause_time": evt_ts,
                        "reason": "Break"
                    })
                    pause_start_ts = None
                    
        if pause_start_ts:
            # Active pause
            pauses.append({
                "agent": ag,
                "queuename": queue_num,
                "pause_time": pause_start_ts,
                "unpause_time": 0,
                "reason": "Break"
            })
            
    bounds_start, bounds_end = _queue_detail_bounds(filters)
    if bounds_start and bounds_end:
        clipped = []
        for pause in pauses:
            pause_start = _local_datetime_from_epoch(pause["pause_time"])
            pause_end = _local_datetime_from_epoch(pause["unpause_time"]) if pause["unpause_time"] else datetime.now(PBX_TIMEZONE).replace(tzinfo=None)
            if pause_end < bounds_start or pause_start > bounds_end:
                continue
            clipped_start = max(pause_start, bounds_start)
            clipped_end = min(pause_end, bounds_end)
            pause["pause_time"] = _local_epoch(clipped_start)
            pause["unpause_time"] = _local_epoch(clipped_end) if pause["unpause_time"] else 0
            clipped.append(pause)
        pauses = clipped

    pauses.sort(key=lambda x: x["pause_time"], reverse=True)
    return pauses[:100]

def get_realtime_counters():
    try:
        auto_reconcile_if_needed()
    except Exception as e:
        print(f"Error in auto_reconcile_if_needed: {e}")
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # 1. Waiting calls (state is WAITING or RINGING)
        c.execute("SELECT COUNT(*) FROM queue_live WHERE state IN ('WAITING', 'RINGING')")
        waiting_calls = c.fetchone()[0] or 0
        
        # 2. Talking calls
        c.execute("SELECT COUNT(*) FROM queue_calls WHERE status = 'ANSWERED' AND hangup_time IS NULL")
        talking_calls = c.fetchone()[0] or 0
        
        # 3. Available agents (extension status AVAILABLE or NOT IN USE)
        c.execute("SELECT COUNT(DISTINCT extension) FROM queue_agents WHERE status IN ('AVAILABLE', 'NOT IN USE')")
        available_agents = c.fetchone()[0] or 0
        
        # 4. Busy agents
        c.execute("SELECT COUNT(DISTINCT extension) FROM queue_agents WHERE status IN ('BUSY', 'IN USE')")
        busy_agents = c.fetchone()[0] or 0
        
        # 5. Paused agents
        c.execute("SELECT COUNT(DISTINCT extension) FROM queue_agents WHERE status = 'PAUSED'")
        paused_agents = c.fetchone()[0] or 0
        
        return {
            "waiting_calls": waiting_calls,
            "talking_calls": talking_calls,
            "available_agents": available_agents,
            "busy_agents": busy_agents,
            "paused_agents": paused_agents
        }
    except Exception as e:
        print(f"Error in get_realtime_counters: {e}")
        return {
            "waiting_calls": 0,
            "talking_calls": 0,
            "available_agents": 0,
            "busy_agents": 0,
            "paused_agents": 0
        }
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_all_agent_sessions(filters):
    conn = get_db_connection()
    c = conn.cursor()
    
    query = """
        SELECT agent, queue, event_type, timestamp 
        FROM queue_agent_events 
        WHERE event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE')
    """
    params = []
    
    if filters.get("queue") and filters["queue"] != "all":
        query += " AND queue = ?"
        params.append(filters["queue"])
    scope_sql, scope_params = _queue_scope_sql(filters, "queue")
    query += scope_sql
    params.extend(scope_params)
    if filters.get("agent") and filters["agent"] != "all":
        query += " AND agent = ?"
        params.append(filters["agent"])
    if filters.get("date_from"):
        query += " AND timestamp >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += " AND timestamp <= ?"
        params.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        query += " AND time(timestamp) >= ?"
        params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        query += " AND time(timestamp) <= ?"
        params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
        
    query += " ORDER BY queue, agent, timestamp ASC"
    c.execute(query, params)
    rows = c.fetchall()
    
    c.execute("SELECT extension, agent_name, type FROM queue_agents")
    agent_info_rows = c.fetchall()
    import db
    ext_names = {e["ext"]: e.get("name") or e["ext"] for e in db.get_all_extensions()}
    agent_meta = {}
    for r in agent_info_rows:
        ext = r["extension"]
        agent_meta[ext] = {
            "name": ext_names.get(ext) or r["agent_name"] or ext,
            "type": r["type"]
        }
        
    import datetime as dt_module
    
    grouped = {}
    for r in rows:
        key = (r["queue"], r["agent"])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r)
        
    # Fix: Keep track of initial paused state to properly compute pauses that span across boundaries
    initial_paused = set()
    if filters.get("date_from"):
        q_da = "SELECT DISTINCT queue_id, extension FROM queue_agents WHERE type = 'DYNAMIC'"
        p_da = []
        where_da = []
        if filters.get("queue") and filters["queue"] != "all":
            where_da.append("queue_id = ?")
            p_da.append(filters["queue"])
        if filters.get("agent") and filters["agent"] != "all":
            where_da.append("extension = ?")
            p_da.append(filters["agent"])
        if where_da:
            q_da += " AND " + " AND ".join(where_da)
            
        c.execute(q_da, p_da)
        dynamic_agents = c.fetchall()
        for da in dynamic_agents:
            qnum = da["queue_id"]
            ag = da["extension"]
            
            c.execute("""
                SELECT event_type, timestamp FROM queue_agent_events 
                WHERE queue = ? AND agent = ? AND event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE') 
                  AND timestamp < ? 
                ORDER BY timestamp DESC LIMIT 1
            """, (qnum, ag, filters["date_from"] + " 00:00:00"))
            last_evt = c.fetchone()
            if last_evt and last_evt["event_type"] in ('LOGIN', 'PAUSE', 'UNPAUSE'):
                key = (qnum, ag)
                if key not in grouped:
                    grouped[key] = []
                grouped[key].insert(0, {
                    "event_type": "LOGIN",
                    "timestamp": filters["date_from"] + " 00:00:00",
                    "queue": qnum,
                    "agent": ag
                })
                if last_evt["event_type"] == 'PAUSE':
                    initial_paused.add(key)
                
    conn.close()
        
    stats = []
    for (qnum, ag), evts in grouped.items():
        sessions = []
        current_session = None
        pause_start = None
        
        # Initialize pause_start if the agent was paused at the start boundary
        if (qnum, ag) in initial_paused and filters.get("date_from"):
            try:
                boundary_dt = dt_module.datetime.strptime(filters["date_from"] + " 00:00:00", "%Y-%m-%d %H:%M:%S")
                pause_start = int(boundary_dt.timestamp())
            except Exception:
                pass
                
        first_login = None
        last_logout = None
        total_session_time = 0
        
        for e in evts:
            evt_type = e["event_type"]
            try:
                evt_dt = dt_module.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
                evt_ts = int(evt_dt.timestamp())
            except Exception:
                continue
                
            if evt_type == 'LOGIN':
                if not first_login:
                    first_login = e["timestamp"]
                if current_session:
                    current_session["logout"] = e["timestamp"]
                    current_session["logout_time_ts"] = evt_ts
                    current_session["duration"] = max(0, evt_ts - current_session["login_time_ts"])
                    sessions.append(current_session)
                current_session = {
                    "login": e["timestamp"],
                    "login_time_ts": evt_ts,
                    "logout": "Active",
                    "logout_time_ts": None,
                    "duration": 0
                }
                pause_start = None
            elif evt_type == 'LOGOUT':
                last_logout = e["timestamp"]
                if current_session:
                    current_session["logout"] = e["timestamp"]
                    current_session["logout_time_ts"] = evt_ts
                    current_session["duration"] = max(0, evt_ts - current_session["login_time_ts"])
                    total_session_time += current_session["duration"]
                    sessions.append(current_session)
                    current_session = None
            elif evt_type == 'PAUSE':
                if current_session and not pause_start:
                    pause_start = evt_ts
            elif evt_type == 'UNPAUSE':
                if current_session and pause_start:
                    pause_start = None
                    
        end_boundary_dt = dt_module.datetime.now()
        if filters.get("date_to"):
            boundary_dt = dt_module.datetime.strptime(filters["date_to"] + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            if boundary_dt < end_boundary_dt:
                end_boundary_dt = boundary_dt
        end_boundary_ts = int(end_boundary_dt.timestamp())

        if current_session:
            current_session["duration"] = max(0, end_boundary_ts - current_session["login_time_ts"])
            total_session_time += current_session["duration"]
            sessions.append(current_session)
            
        meta = agent_meta.get(ag, {"name": ag, "type": "DYNAMIC"})
        
        # Format session times nicely
        formatted_sessions = []
        for s in sessions:
            formatted_sessions.append({
                "login": s["login"],
                "logout": s["logout"],
                "duration": s["duration"]
            })
            
        if meta["type"].upper() == "STATIC":
            stats.append({
                "queue": qnum,
                "extension": ag,
                "agent_name": meta["name"],
                "type": meta["type"].upper(),
                "first_login": "",
                "last_logout": "",
                "total_session_time": None,
                "sessions": []
            })
        else:
            stats.append({
                "queue": qnum,
                "extension": ag,
                "agent_name": meta["name"],
                "type": meta["type"].upper(),
                "first_login": first_login or "-",
                "last_logout": last_logout or "Active",
                "total_session_time": total_session_time,
                "sessions": formatted_sessions
            })
        
    return stats

def get_all_agent_pauses(filters):
    conn = get_db_connection()
    c = conn.cursor()
    
    query = """
        SELECT agent, queue, event_type, timestamp 
        FROM queue_agent_events 
        WHERE event_type IN ('PAUSE', 'UNPAUSE', 'LOGOUT')
    """
    params = []
    
    if filters.get("queue") and filters["queue"] != "all":
        query += " AND queue = ?"
        params.append(filters["queue"])
    scope_sql, scope_params = _queue_scope_sql(filters, "queue")
    query += scope_sql
    params.extend(scope_params)
    if filters.get("agent") and filters["agent"] != "all":
        query += " AND agent = ?"
        params.append(filters["agent"])
    if filters.get("date_from"):
        query += " AND timestamp >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += " AND timestamp <= ?"
        params.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        query += " AND time(timestamp) >= ?"
        params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        query += " AND time(timestamp) <= ?"
        params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
        
    query += " ORDER BY queue, agent, timestamp ASC"
    c.execute(query, params)
    rows = c.fetchall()
    
    c.execute("SELECT extension, agent_name, type FROM queue_agents")
    agent_info_rows = c.fetchall()
    import db
    ext_names = {e["ext"]: e.get("name") or e["ext"] for e in db.get_all_extensions()}
    agent_meta = {}
    for r in agent_info_rows:
        ext = r["extension"]
        agent_meta[ext] = {
            "name": ext_names.get(ext) or r["agent_name"] or ext,
            "type": r["type"]
        }
        
    import datetime as dt_module
    
    grouped = {}
    for r in rows:
        key = (r["queue"], r["agent"])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r)
        
    if filters.get("date_from"):
        # Fix: Filter dynamic agents by agent/queue if specified
        q_da = "SELECT DISTINCT queue_id, extension FROM queue_agents WHERE type = 'DYNAMIC'"
        p_da = []
        where_da = []
        if filters.get("queue") and filters["queue"] != "all":
            where_da.append("queue_id = ?")
            p_da.append(filters["queue"])
        if filters.get("agent") and filters["agent"] != "all":
            where_da.append("extension = ?")
            p_da.append(filters["agent"])
        if where_da:
            q_da += " AND " + " AND ".join(where_da)
            
        c.execute(q_da, p_da)
        dynamic_agents = c.fetchall()
        for da in dynamic_agents:
            qnum = da["queue_id"]
            ag = da["extension"]
            
            c.execute("""
                SELECT event_type, timestamp FROM queue_agent_events 
                WHERE queue = ? AND agent = ? AND event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE') 
                  AND timestamp < ? 
                ORDER BY timestamp DESC LIMIT 1
            """, (qnum, ag, filters["date_from"] + " 00:00:00"))
            last_evt = c.fetchone()
            if last_evt and last_evt["event_type"] == 'PAUSE':
                key = (qnum, ag)
                if key not in grouped:
                    grouped[key] = []
                grouped[key].insert(0, {
                    "event_type": "PAUSE",
                    "timestamp": filters["date_from"] + " 00:00:00",
                    "queue": qnum,
                    "agent": ag
                })
                
    conn.close()
        
    stats = []
    for (qnum, ag), evts in grouped.items():
        pauses = []
        pause_start_ts = None
        pause_start_str = None
        total_pause_time = 0
        
        for e in evts:
            evt_type = e["event_type"]
            try:
                evt_dt = dt_module.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
                evt_ts = int(evt_dt.timestamp())
            except Exception:
                continue
                
            if evt_type == 'PAUSE':
                if pause_start_ts:
                    dur = max(0, evt_ts - pause_start_ts)
                    total_pause_time += dur
                    pauses.append({
                        "start": pause_start_str,
                        "end": e["timestamp"],
                        "duration": dur,
                        "reason": "Break"
                    })
                pause_start_ts = evt_ts
                pause_start_str = e["timestamp"]
            elif evt_type in ('UNPAUSE', 'LOGOUT'):
                if pause_start_ts:
                    dur = max(0, evt_ts - pause_start_ts)
                    total_pause_time += dur
                    pauses.append({
                        "start": pause_start_str,
                        "end": e["timestamp"],
                        "duration": dur,
                        "reason": "Break"
                    })
                    pause_start_ts = None
                    pause_start_str = None
                    
        if pause_start_ts:
            end_boundary_dt = dt_module.datetime.now()
            if filters.get("date_to"):
                boundary_dt = dt_module.datetime.strptime(filters["date_to"] + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                if boundary_dt < end_boundary_dt:
                    end_boundary_dt = boundary_dt
            end_boundary_ts = int(end_boundary_dt.timestamp())

            dur = max(0, end_boundary_ts - pause_start_ts)
            total_pause_time += dur
            pauses.append({
                "start": pause_start_str,
                "end": "Active",
                "duration": dur,
                "reason": "Break"
            })
            
        meta = agent_meta.get(ag, {"name": ag, "type": "DYNAMIC"})
        
        stats.append({
            "queue": qnum,
            "extension": ag,
            "agent_name": meta["name"],
            "total_pause_time": total_pause_time,
            "pauses": pauses
        })
        
    return stats

def get_kpis_aggregate(filters):
    conn = get_db_connection()
    c = conn.cursor()
    
    query = """
        SELECT 
            COUNT(*) as total_calls,
            SUM(CASE WHEN status = 'ANSWERED' THEN 1 ELSE 0 END) as answered,
            SUM(CASE WHEN status = 'ABANDONED' THEN 1 ELSE 0 END) as abandoned,
            SUM(CASE WHEN status IN ('CANCELED', 'CANCELLED') THEN 1 ELSE 0 END) as cancelled,
            SUM(CASE WHEN status = 'NO ANSWER' THEN 1 ELSE 0 END) as no_answer,
            AVG(CASE WHEN status = 'ANSWERED' THEN talk_time ELSE NULL END) as avg_talk,
            AVG(wait_time) as avg_wait,
            AVG(CASE WHEN status = 'ANSWERED' THEN hold_time ELSE NULL END) as avg_hold,
            MAX(wait_time) as longest_wait,
            MAX(CASE WHEN status = 'ANSWERED' THEN talk_time ELSE 0 END) as longest_talk,
            MIN(CASE WHEN status = 'ANSWERED' THEN talk_time ELSE NULL END) as shortest_talk,
            SUM(CASE WHEN status = 'ANSWERED' AND wait_time <= 20 THEN 1 ELSE 0 END) as sla_met
        FROM queue_calls
        WHERE 1=1
    """
    params = []
    
    if filters.get("date_from"):
        query += " AND entry_time >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += " AND entry_time <= ?"
        params.append(filters["date_to"] + " 23:59:59")
        
    if filters.get("queue") and filters["queue"] != "all":
        query += " AND queue_id = ?"
        params.append(filters["queue"])
        
    if filters.get("agent") and filters["agent"] != "all":
        query += " AND agent = ?"
        params.append(filters["agent"])
        
    if filters.get("caller"):
        query += " AND caller_number LIKE ?"
        params.append(f"%{filters['caller']}%")
        
    c.execute(query, params)
    row = c.fetchone()
    conn.close()
    
    total_calls = row["total_calls"] or 0
    answered = row["answered"] or 0
    abandoned = row["abandoned"] or 0
    cancelled = row["cancelled"] or 0
    no_answer = row["no_answer"] or 0
    
    ans_rate = round((answered / total_calls) * 100, 1) if total_calls > 0 else 0
    abandon_rate = round((abandoned / total_calls) * 100, 1) if total_calls > 0 else 0
    sla_pct = round((row["sla_met"] or 0) / total_calls * 100, 1) if total_calls > 0 else 100
    
    return {
        "total_calls": total_calls,
        "answered": answered,
        "abandoned": abandoned,
        "cancelled": cancelled,
        "no_answer": no_answer,
        "ans_rate": ans_rate,
        "abandon_rate": abandon_rate,
        "avg_talk": int(row["avg_talk"] or 0),
        "avg_wait": int(row["avg_wait"] or 0),
        "avg_hold": int(row["avg_hold"] or 0),
        "longest_wait": row["longest_wait"] or 0,
        "longest_talk": row["longest_talk"] or 0,
        "shortest_talk": row["shortest_talk"] or 0,
        "sla_pct": sla_pct
    }

def db_call_hold_event(uniqueid, is_hold, event_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT agent, queue_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (uniqueid,))
    row = c.fetchone()
    if row:
        agent = row["agent"]
        qnum = row["queue_id"]
        event = "HOLD" if is_hold else "UNHOLD"
        now_str = _event_time_string(event_time)
        
        c.execute("""
            INSERT INTO queue_agent_events (agent, queue, event_type, uniqueid, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (agent, qnum, event, uniqueid, now_str))
        
        # Fix: Compute and update hold_time in queue_calls when UNHOLD occurs
        if not is_hold:
            c.execute("""
                SELECT timestamp FROM queue_agent_events 
                WHERE uniqueid = ? AND event_type = 'HOLD' 
                ORDER BY timestamp DESC LIMIT 1
            """, (uniqueid,))
            hold_row = c.fetchone()
            if hold_row:
                try:
                    hold_dt = datetime.strptime(hold_row["timestamp"], "%Y-%m-%d %H:%M:%S")
                    unhold_dt = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S")
                    hold_duration = max(0, int((unhold_dt - hold_dt).total_seconds()))
                    if hold_duration > 0:
                        c.execute("""
                            UPDATE queue_calls 
                            SET hold_time = COALESCE(hold_time, 0) + ? 
                            WHERE call_id = (SELECT call_id FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1)
                        """, (hold_duration, uniqueid))
                except Exception as e:
                    print(f"Error calculating hold duration: {e}")
                    
    conn.commit()
    conn.close()

def reconcile_active_calls(active_uids):
    # Call the unified auto-reconciliation engine
    reconcile_with_asterisk_state()

LAST_RECONCILE_TIME = 0

def auto_reconcile_if_needed():
    global LAST_RECONCILE_TIME
    import time
    import sys
    
    # Fail-safe check to prevent running reconciliation in test environments
    if "unittest" in sys.modules or "pytest" in sys.modules or "/tmp" in DB_PATH or "TemporaryDirectory" in DB_PATH:
        return
        
    now = time.time()
    if now - LAST_RECONCILE_TIME >= 2.0:
        LAST_RECONCILE_TIME = now
        try:
            reconcile_with_asterisk_state()
        except Exception as e:
            print(f"Error in auto_reconcile_if_needed: {e}")

def reconcile_with_asterisk_state():
    import subprocess
    import sys
    
    # Fail-safe check to prevent running reconciliation in test environments
    if "unittest" in sys.modules or "pytest" in sys.modules or "/tmp" in DB_PATH or "TemporaryDirectory" in DB_PATH:
        return
        
    # Sync queue log first to capture latest events
    try:
        sync_queue_log_to_db()
    except Exception as e:
        print(f"Error syncing queue log during reconcile: {e}")
        
    # Check if Asterisk is online
    asterisk_online = False
    try:
        res = subprocess.run("asterisk -rx \"core show version\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0:
            asterisk_online = True
    except Exception:
        pass
        
    if not asterisk_online:
        print("[RECONCILE] Asterisk is offline or unreachable. Skipping reconciliation.")
        return

    print("[SYNC] Triggering full auto-reconciliation with Asterisk's real state...")
    
    active_uids = set()
    chan_to_uid = {}
    uid_to_caller = {}
    
    # 1. Get active channels from core show channels concise
    try:
        res = subprocess.run("asterisk -rx \"core show channels concise\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('!')
                if len(parts) >= 13:
                    channel = parts[0]
                    caller = parts[7]
                    uid = parts[12]
                    active_uids.add(uid)
                    chan_to_uid[channel] = uid
                    uid_to_caller[uid] = caller
    except Exception as e:
        print(f"Error during reconcile core show channels: {e}")
        
    # 2. Get queue status from queue show
    queues_waiting_channels = {}
    agent_states = {}
    
    try:
        res = subprocess.run("asterisk -rx \"queue show\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            current_queue = None
            in_members = False
            in_callers = False
            for line in res.stdout.split('\n'):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                
                if "has" in line_stripped and "calls" in line_stripped and "strategy" in line_stripped.lower():
                    parts = line_stripped.split()
                    if len(parts) > 0:
                        current_queue = parts[0]
                        queues_waiting_channels[current_queue] = []
                        in_members = False
                        in_callers = False
                    continue
                
                if current_queue:
                    if "Members:" in line_stripped:
                        in_members = True
                        in_callers = False
                        continue
                    elif "Callers:" in line_stripped or "No Callers" in line_stripped:
                        in_members = False
                        in_callers = "Callers:" in line_stripped
                        continue
                    
                    if in_members:
                        parts = line_stripped.split()
                        if len(parts) > 0:
                            member_name = parts[0]
                            ext = member_name.split("/")[-1].split("@")[0].split(";")[0]
                            if "-" in ext and not ext.startswith("-"):
                                ext = ext.rsplit("-", 1)[0]
                            ext = ext.strip()
                            
                            is_paused = "paused" in line_stripped.lower()
                            is_dynamic = "(dynamic)" in line_stripped.lower()
                            member_type = "DYNAMIC" if is_dynamic else "STATIC"
                            
                            status = "UNKNOWN"
                            if is_paused:
                                status = "PAUSED"
                            elif "ringing" in line_stripped.lower():
                                status = "RINGING"
                            elif "not in use" in line_stripped.lower():
                                status = "NOT IN USE"
                            elif "in use" in line_stripped.lower():
                                status = "IN USE"
                            elif "busy" in line_stripped.lower():
                                status = "BUSY"
                            elif "unavailable" in line_stripped.lower() or "invalid" in line_stripped.lower():
                                status = "UNAVAILABLE"
                            elif "unknown" in line_stripped.lower():
                                status = "UNKNOWN"
                                
                            agent_states[(ext, current_queue)] = (status, member_type)
                            
                    elif in_callers:
                        parts = line_stripped.split()
                        if len(parts) >= 2:
                            chan = parts[1]
                            queues_waiting_channels[current_queue].append(chan)
    except Exception as e:
        print(f"Error during reconcile queue show: {e}")
        
    conn = get_db_connection()
    c = conn.cursor()
    
    # 3. Read configured static agents from queues JSON config
    # This ensures we know which agents are configured as static members
    configured_static = {}
    try:
        import db
        config_queues = db.get_queues()
        for cq in config_queues:
            qnum = cq.get("queue_number")
            configured_static[qnum] = set(cq.get("static_agents", []))
    except Exception as e:
        print(f"[RECONCILE] Error reading queues config: {e}")

    # Gather all valid agent keys (extension, queue_id)
    # Valid agents are either:
    #   1) Configured as static agents in the JSON config
    #   2) Currently active members returned by Asterisk (AMI/CLI state)
    valid_agent_keys = set()
    for qnum, extensions in configured_static.items():
        for ext in extensions:
            valid_agent_keys.add((ext, qnum))
    for key in agent_states.keys():
        valid_agent_keys.add(key)

    # Reconcile agent states in queue_agents table
    c.execute("SELECT extension, queue_id, status, type FROM queue_agents")
    db_agents = c.fetchall()
    db_agent_keys = set()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for da in db_agents:
        ext = da["extension"]
        qnum = da["queue_id"]
        db_status = da["status"]
        db_type = da["type"]
        key = (ext, qnum)
        
        # 3a. If the agent does not exist in Asterisk state AND is not in rcm_queues.json static config:
        # Prune them from the database since they are no longer members.
        if key not in valid_agent_keys:
            print(f"[RECONCILE] Pruning stale/removed agent {ext} from queue {qnum} database records.")
            c.execute("DELETE FROM queue_agents WHERE extension = ? AND queue_id = ?", (ext, qnum))
            c.execute("DELETE FROM queue_live WHERE agent = ? AND queue = ?", (ext, qnum))
            if db_status != 'OFFLINE':
                c.execute("""
                    INSERT OR REPLACE INTO queue_agent_events (agent, queue, event_type, timestamp)
                    VALUES (?, ?, 'LOGOUT', ?)
                """, (ext, qnum, now_str))
            continue
            
        db_agent_keys.add(key)
        
        real_info = agent_states.get(key)
        if real_info:
            # Reconcile status and type with actual Asterisk active member info
            real_status, real_type = real_info
            if real_status != db_status or real_type != db_type:
                print(f"[RECONCILE] Correcting agent {ext} status/type in queue {qnum} from {db_status}/{db_type} to {real_status}/{real_type}")
                # Correcting status/type and preserving/initializing login_time
                if db_status == 'OFFLINE':
                    c.execute("""
                        UPDATE queue_agents 
                        SET status = ?, type = ?, login_time = COALESCE(login_time, ?), logout_time = NULL
                        WHERE extension = ? AND queue_id = ?
                    """, (real_status, real_type, now_str, ext, qnum))
                else:
                    c.execute("""
                        UPDATE queue_agents 
                        SET status = ?, type = ? 
                        WHERE extension = ? AND queue_id = ?
                    """, (real_status, real_type, ext, qnum))
                
                evt_type = "UNPAUSE" if real_status in ("NOT IN USE", "AVAILABLE") and db_status == "PAUSED" else \
                           "PAUSE" if real_status == "PAUSED" else \
                           "COMPLETE" if real_status in ("NOT IN USE", "AVAILABLE") and db_status in ("BUSY", "IN USE") else \
                           "LOGIN" if db_status == "OFFLINE" else \
                           "STATUS_CHANGE"
                
                c.execute("""
                    INSERT OR REPLACE INTO queue_agent_events (agent, queue, event_type, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (ext, qnum, evt_type, now_str))
        else:
            # 3b. The agent is not active in Asterisk but is configured as a static agent
            # We must make sure they are marked as OFFLINE in the database
            if db_status != 'OFFLINE':
                print(f"[RECONCILE] Configured static agent {ext} is not active in Asterisk queue {qnum}, marking OFFLINE")
                c.execute("UPDATE queue_agents SET status = 'OFFLINE', login_time = NULL, logout_time = ? WHERE extension = ? AND queue_id = ?", (now_str, ext, qnum))
                c.execute("""
                    INSERT OR REPLACE INTO queue_agent_events (agent, queue, event_type, timestamp)
                    VALUES (?, ?, 'LOGOUT', ?)
                """, (ext, qnum, now_str))
                
    # 4. Insert missing members that are valid (either configured static or active in Asterisk) but missing from DB
    for (ext, qnum) in valid_agent_keys:
        if (ext, qnum) not in db_agent_keys:
            real_info = agent_states.get((ext, qnum))
            if real_info:
                real_status, real_type = real_info
            else:
                real_status = 'OFFLINE'
                real_type = 'STATIC'
                
            print(f"[RECONCILE] Adding missing valid agent {ext} in queue {qnum} with status {real_status} and type {real_type}")
            
            login_time_val = None if real_status == 'OFFLINE' else now_str
            logout_time_val = now_str if real_status == 'OFFLINE' else None
            
            agent_name = ext
            try:
                ext_obj = db.get_extension(ext)
                if ext_obj and ext_obj.get("name"):
                    agent_name = ext_obj["name"]
            except Exception:
                pass
                
            c.execute("""
                INSERT INTO queue_agents (extension, agent_name, queue_id, type, status, login_time, logout_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ext, agent_name, qnum, real_type, real_status, login_time_val, logout_time_val))
            
            evt_type = "LOGOUT" if real_status == 'OFFLINE' else "LOGIN"
            c.execute("""
                INSERT OR REPLACE INTO queue_agent_events (agent, queue, event_type, timestamp)
                VALUES (?, ?, ?, ?)
            """, (ext, qnum, evt_type, now_str))

    # 4. Reconcile active calls (live calls and uncompleted calls)
    c.execute("SELECT call_id, queue, caller FROM queue_live")
    db_live_calls = c.fetchall()
    
    c.execute("""
        SELECT uniqueid, queue_id, caller_number FROM queue_calls 
        WHERE status NOT IN ('ANSWERED', 'ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT')
           OR hangup_time IS NULL
    """)
    db_uncompleted_calls = c.fetchall()
    
    live_call_ids = {row["call_id"] for row in db_live_calls}
    
    asterisk_waiting_uids = set()
    queues_with_waiting_callers = {
        qnum for qnum, channels in queues_waiting_channels.items() if channels
    }
    for qnum, channels in queues_waiting_channels.items():
        for ch in channels:
            uid = chan_to_uid.get(ch)
            if uid:
                asterisk_waiting_uids.add(uid)
    active_uids.update(asterisk_waiting_uids)
                
    ghost_uids = set()
    for lc in db_live_calls:
        cid = lc["call_id"]
        qnum = lc["queue"]
        if cid not in active_uids and qnum not in queues_with_waiting_callers:
            ghost_uids.add((cid, qnum))

    for uc in db_uncompleted_calls:
        uid = uc["uniqueid"]
        qnum = uc["queue_id"]
        if uid not in active_uids and qnum not in queues_with_waiting_callers:
            ghost_uids.add((uid, qnum))
            
    conn.commit()
    conn.close()
    
    # Process hangup on each ghost call to resolve database state
    for cid, qnum in ghost_uids:
        print(f"[RECONCILE] Purging ghost call {cid} from queue {qnum}")
        db_call_hangup(cid, "Ghost Call Auto-Reconciliation")
        
    # 5. Insert any missing waiting calls that are active in Asterisk but missing from DB
    conn = get_db_connection()
    c = conn.cursor()
    for qnum, channels in queues_waiting_channels.items():
        for ch in channels:
            uid = chan_to_uid.get(ch)
            if uid and uid not in live_call_ids:
                caller = uid_to_caller.get(uid, "Unknown")
                print(f"[RECONCILE] Recovering missing waiting caller {caller} in queue {qnum} (UID: {uid})")
                
                c.execute("SELECT COUNT(*) FROM queue_calls WHERE uniqueid = ?", (uid,))
                exists = c.fetchone()[0] > 0
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if not exists:
                    # Fix: Stop overwriting queue_name with queue number. Use queues table mapping.
                    c.execute("SELECT queue_name FROM queues WHERE queue_number = ?", (qnum,))
                    qrow = c.fetchone()
                    q_name = qrow["queue_name"] if qrow else qnum
                    c.execute("""
                        INSERT OR REPLACE INTO queue_calls (uniqueid, linkedid, caller_number, queue_id, queue_name, entry_time, status, source_trunk, position, initial_position, last_position)
                        VALUES (?, ?, ?, ?, ?, ?, 'ENTERED', 'Trunk-SIP-Main', 1, 1, 1)
                    """, (uid, uid, caller, qnum, q_name, now_str))
                
                c.execute("""
                    INSERT OR REPLACE INTO queue_live (call_id, queue, caller, position, state, start_time)
                    VALUES (?, ?, ?, 1, 'WAITING', ?)
                """, (uid, qnum, caller, now_str))
                
    conn.commit()
    conn.close()
    
    # Reindex waiting call positions
    for qnum in queues_waiting_channels.keys():
        db_reindex_queue_positions(qnum)
        
    print("[SYNC] Full auto-reconciliation complete.")


def get_paginated_queue_calls(filters):
    sync_queue_log_to_db()
    conn = get_db_connection()
    c = conn.cursor()
    
    # Fix: Stop overwriting queue_name with queue number. Use queues table mapping.
    query = """
        SELECT qc.*, q.queue_name AS mapped_queue_name 
        FROM queue_calls qc
        LEFT JOIN queues q ON qc.queue_id = q.queue_number
        WHERE 1=1
    """
    params = []
    
    if filters.get("date_from"):
        query += " AND qc.entry_time >= ?"
        params.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        query += " AND qc.entry_time <= ?"
        params.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        query += " AND time(qc.entry_time) >= ?"
        params.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        query += " AND time(qc.entry_time) <= ?"
        params.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
    if filters.get("queue") and filters["queue"] != "all":
        query += """
            AND (
                qc.queue_id = ?
                OR EXISTS (
                    SELECT 1
                    FROM queue_agent_events qae
                    WHERE qae.event_type = 'TRANSFER'
                      AND qae.agent = ?
                      AND (qae.uniqueid = qc.uniqueid OR qae.uniqueid = qc.linkedid)
                )
            )
        """
        params.extend([filters["queue"], filters["queue"]])
    scope_sql, scope_params = _queue_scope_sql(filters, "qc.queue_id")
    query += scope_sql
    params.extend(scope_params)
    if filters.get("agent") and filters["agent"] != "all":
        query += " AND qc.agent = ?"
        params.append(filters["agent"])
    if filters.get("caller"):
        query += " AND qc.caller_number LIKE ?"
        params.append(f"%{filters['caller']}%")
        
    # Expand queue visits before pagination so transfer rows, counts and the
    # visible page all describe the same business sessions.
    query += " ORDER BY qc.entry_time DESC"
    c.execute(query, params)
    rows = c.fetchall()
    rows = _expand_queue_stats_sessions(conn, rows, filters)
    total_rows = len(rows)
    limit = int(filters.get("limit", 10))
    page = int(filters.get("page", 1))
    offset = (page - 1) * limit
    rows = rows[offset:offset + limit]
    
    calls = []
    for r in rows:
        import datetime as dt_module
        talk_time = _resolve_queue_talk_time(r)
        ts = 0
        if r["entry_time"]:
            try:
                dt = dt_module.datetime.strptime(r["entry_time"], "%Y-%m-%d %H:%M:%S")
                ts = _local_epoch(dt)
            except Exception:
                pass
        calls.append({
            "id": r["call_id"],
            "call_id": r["call_id"],
            "callid": r["uniqueid"],
            "uniqueid": r["uniqueid"],
            "linkedid": r["linkedid"],
            "queuename": r["queue_id"],
            "queue": r["queue_id"],
            "queue_id": r["queue_id"],
            "queue_name": r["mapped_queue_name"] or r["queue_name"] or r["queue_id"],
            "caller": r["caller_number"],
            "caller_number": r["caller_number"],
            "timestamp": ts,
            "entry_time": r["entry_time"],
            "answer_time": r["answer_time"],
            "hangup_time": r["hangup_time"],
            "status": r["status"],
            "agent": r["agent"] or "",
            "wait_time": r["wait_time"] or 0,
            "talk_time": talk_time,
            "hold_time": r["hold_time"] or 0,
            "hangup_by": "AGENT" if (r["hangup_by"] == "AGENT" or (r["status"] == "ANSWERED" and r["hangup_by"] != "CALLER")) else "CALLER",
            "recording_file": _resolve_queue_recording(r),
            "disposition_code": "",
            "initial_position": r["initial_position"] if ("initial_position" in r.keys() and r["initial_position"] is not None) else (r["position"] or 0),
            "last_position": r["last_position"] if ("last_position" in r.keys() and r["last_position"] is not None) else (r["position"] or 0),
        })
        
    conn.close()
    return {
        "data": calls,
        "total_rows": total_rows,
        "current_page": page,
        "limit": limit
    }

def get_paginated_agent_sessions(filters):
    stats = get_all_agent_sessions(filters)
    total_rows = len(stats)
    
    limit = int(filters.get("login_limit", 10))
    page = int(filters.get("login_page", 1))
    offset = (page - 1) * limit
    
    paginated_data = stats[offset:offset+limit]
    return {
        "data": paginated_data,
        "total_rows": total_rows,
        "current_page": page,
        "limit": limit
    }

def get_paginated_agent_pauses(filters):
    stats = get_all_agent_pauses(filters)
    total_rows = len(stats)
    
    limit = int(filters.get("pause_limit", 10))
    page = int(filters.get("pause_page", 1))
    offset = (page - 1) * limit
    
    paginated_data = stats[offset:offset+limit]
    return {
        "data": paginated_data,
        "total_rows": total_rows,
        "current_page": page,
        "limit": limit
    }

def get_call_events_by_id(callid):
    def timeline_time(value):
        try:
            return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return datetime.max

    conn = get_db_connection()
    c = conn.cursor()
    
    # Query queue_calls to get overall metrics
    c.execute("SELECT * FROM queue_calls WHERE uniqueid = ? ORDER BY entry_time DESC LIMIT 1", (callid,))
    call_row = c.fetchone()
    
    # Query positions
    c.execute("SELECT * FROM queue_call_positions WHERE uniqueid = ? ORDER BY timestamp ASC", (callid,))
    positions = c.fetchall()
    
    # Query agent events
    c.execute("SELECT * FROM queue_agent_events WHERE uniqueid = ? ORDER BY timestamp ASC", (callid,))
    agent_evts = c.fetchall()
    
    conn.close()
    
    # Merge and build chronological event sequence
    raw_events = []
    
    for row in positions:
        raw_events.append({
            "timestamp": row["timestamp"],
            "event": row["event"],
            "agent": None,
            "queue": row["queue"],
            "position": row["position"],
            "duration": None,
            "reason": None
        })
        
    for row in agent_evts:
        raw_events.append({
            "timestamp": row["timestamp"],
            "event": row["event_type"],
            "agent": row["agent"],
            "queue": row["queue"],
            "position": None,
            "duration": None,
            "reason": None
        })
        
    # Sort raw events chronologically
    raw_events.sort(key=lambda x: x["timestamp"])
    
    mapped = []
    processed_types = {}

    # QueueLog stores the transfer destination in the event's agent field;
    # resolve the source from the last answered agent before rendering it.
    transfer_sources = {}
    active_agent = ""
    for a_ev in sorted(agent_evts, key=lambda row: row["timestamp"]):
        a_type = (a_ev["event_type"] or "").upper()
        if a_type == "ANSWER" and a_ev["agent"]:
            active_agent = a_ev["agent"]
        elif a_type == "TRANSFER":
            transfer_sources[a_ev["timestamp"]] = active_agent

    transfer_times_by_source = {}
    for transfer_time, source in transfer_sources.items():
        if source:
            transfer_times_by_source.setdefault(source, []).append(timeline_time(transfer_time))

    for ev in raw_events:
        evt_type = ev["event"].upper()
        ts = ev["timestamp"]
        
        agent = ev["agent"] or ""
        target = ""
        transfer_type = ""
        pos_dur = ""
        reason = ""
        
        if evt_type == "ENTERQUEUE":
            display_event = "ENTERQUEUE"
            initial_pos = 1
            if call_row and ("initial_position" in call_row.keys() and call_row["initial_position"] is not None):
                initial_pos = call_row["initial_position"]
            elif ev["position"]:
                initial_pos = ev["position"]
            pos_dur = f"Position: {initial_pos}"
            
        elif evt_type in ("CONNECT", "ANSWER"):
            display_event = "CONNECT"
            if not agent:
                for a_ev in agent_evts:
                    if (
                        a_ev["event_type"] in ("ANSWER", "RING", "HANGUP", "COMPLETE")
                        and a_ev["agent"]
                        and a_ev["timestamp"] == ts
                    ):
                        agent = a_ev["agent"]
                        break
            if not agent:
                for a_ev in agent_evts:
                    if a_ev["event_type"] in ("ANSWER", "RING", "HANGUP", "COMPLETE") and a_ev["agent"]:
                        agent = a_ev["agent"]
                        break
            if not agent and call_row:
                agent = call_row["agent"] or ""
                
            wait_time = 0
            if call_row and call_row["wait_time"]:
                wait_time = call_row["wait_time"]
            pos_dur = f"Wait: {wait_time}s"
            
        elif evt_type in ("COMPLETE", "HANGUP", "COMPLETEAGENT", "COMPLETECALLER") and not (
            transfer_sources.get(ts) and transfer_sources.get(ts) == agent
        ) and not any(
            timeline_time(ts) <= transfer_time <= timeline_time(ts) + timedelta(seconds=30)
            for transfer_time in transfer_times_by_source.get(agent, [])
        ):
            hangup_by = "AGENT" if evt_type == "COMPLETEAGENT" else "CALLER"
            hangup_reason = "Hangup"
            talk_time = 0
            if call_row:
                hb = call_row["hangup_by"]
                hangup_by = "AGENT" if (hb == "AGENT" or (call_row["status"] == "ANSWERED" and hb != "CALLER")) else "CALLER"
                hangup_reason = call_row["hangup_reason"] or "Hangup"
                talk_time = call_row["talk_time"] or 0
                
            display_event = "COMPLETEAGENT" if hangup_by == "AGENT" else "COMPLETECALLER"
            if not agent and call_row:
                agent = call_row["agent"] or ""
            pos_dur = f"Talk: {talk_time}s"
            reason = f"{hangup_by} Hangup ({hangup_reason})"
            
        elif evt_type == "ABANDON":
            display_event = "ABANDON"
            wait_time = 0
            if call_row and call_row["wait_time"]:
                wait_time = call_row["wait_time"]
            pos_dur = f"Wait: {wait_time}s"
            reason = "Caller Abandon"

        elif evt_type == "TRANSFER":
            target = agent
            agent = transfer_sources.get(ts) or ""
            display_event = "TRANSFERRED"
            transfer_type = next(
                (
                    row["transfer_type"] for row in agent_evts
                    if row["event_type"] == "TRANSFER"
                    and row["timestamp"] == ts
                    and row["transfer_type"]
                ),
                "Blind Transfer",
            )
            reason = ""

        elif evt_type == "RINGNOANSWER":
            display_event = "RINGNOANSWER"
            if not agent:
                for a_ev in agent_evts:
                    if a_ev["event_type"] == "RINGNOANSWER" and a_ev["agent"] and a_ev["timestamp"] == ts:
                        agent = a_ev["agent"]
                        break
            if not agent:
                for a_ev in agent_evts:
                    if a_ev["event_type"] == "RINGNOANSWER" and a_ev["agent"]:
                        agent = a_ev["agent"]
                        break
            reason = "Missed Ring"
            
        elif evt_type == "RINGCANCELED":
            display_event = "RINGCANCELED"
            if not agent:
                for a_ev in agent_evts:
                    if a_ev["event_type"] == "RINGCANCELED" and a_ev["agent"] and a_ev["timestamp"] == ts:
                        agent = a_ev["agent"]
                        break
            if not agent:
                for a_ev in agent_evts:
                    if a_ev["event_type"] == "RINGCANCELED" and a_ev["agent"]:
                        agent = a_ev["agent"]
                        break
            reason = "Ring Cancelled"
            
        elif evt_type == "EXITEMPTY":
            display_event = "EXITEMPTY"
            reason = "Queue Empty"
            
        elif evt_type == "EXITWITHTIMEOUT":
            display_event = "EXITWITHTIMEOUT"
            reason = "Queue Timeout"
            
        else:
            continue
            
        # Include the agent so simultaneous attempts are not collapsed into a
        # single event. Position rows and agent rows for the same attempt still
        # deduplicate because they resolve to the same timestamp and agent.
        key = (ts, display_event, "" if display_event == "ENTERQUEUE" else agent)
        if key in processed_types:
            continue
        processed_types[key] = True
        
        mapped.append({
            "timestamp": ts,
            "event": display_event,
            "agent": agent,
            "queue": ev.get("queue") or (call_row["queue_id"] if call_row else ""),
            "target": target,
            "transfer_type": transfer_type,
            "position_duration": pos_dur,
            "reason": reason
        })
        
    mapped.sort(key=lambda x: x["timestamp"])

    # The collector can record an intermediate COMPLETE at the answer time
    # and the real COMPLETE/HANGUP a few seconds later.  They describe the
    # same answered leg, so keep the latest terminal event in the timeline.
    terminal_events = {"COMPLETEAGENT", "COMPLETECALLER"}
    compacted = []
    terminal_indexes = {}
    for event in mapped:
        if event["event"] == "CONNECT" and compacted:
            previous = compacted[-1]
            if (
                previous
                and previous["event"] == "CONNECT"
                and previous.get("agent") == event.get("agent")
                and abs((timeline_time(event["timestamp"]) - timeline_time(previous["timestamp"])).total_seconds()) <= 1
            ):
                continue
        event_key = (event["event"], event.get("agent") or "")
        if event["event"] in terminal_events and event.get("agent"):
            previous_index = terminal_indexes.get(event_key)
            if previous_index is not None:
                # Mark the earlier intermediate record for removal, then keep
                # the later record in its real chronological position.
                compacted[previous_index] = None
                terminal_indexes[event_key] = len(compacted)
                compacted.append(event)
                continue
            terminal_indexes[event_key] = len(compacted)
        compacted.append(event)
    return [event for event in compacted if event is not None]
