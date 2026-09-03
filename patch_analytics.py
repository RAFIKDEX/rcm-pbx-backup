import re

with open("/root/RCM_7021/rcm_queue_db.py", "r") as f:
    content = f.read()

# 1. Remove the forced "all" agent filter
content = content.replace('report_filters["agent"] = "all"', '# report_filters["agent"] = "all"')

# 2. Add bulk fetch helpers
bulk_helpers = """
    # --- BULK PREFETCH TO FIX N+1 ---
    def fetch_all_attempts(event_type):
        q = "SELECT agent, queue, event_type, uniqueid, timestamp FROM queue_agent_events WHERE event_type = ?"
        p = [event_type]
        if filters.get("date_from"):
            q += " AND timestamp >= ?"
            p.append(filters["date_from"] + " 00:00:00")
        if filters.get("date_to"):
            q += " AND timestamp <= ?"
            p.append(filters["date_to"] + " 23:59:59")
        if filters.get("time_from"):
            q += " AND time(timestamp) >= ?"
            p.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
        if filters.get("time_to"):
            q += " AND time(timestamp) <= ?"
            p.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
        if filters.get("queue") and filters["queue"] != "all":
            q += " AND queue = ?"
            p.append(filters["queue"])
        scope_sql, scope_params = _queue_scope_sql(filters, "queue")
        q += scope_sql
        p.extend(scope_params)
        q += " ORDER BY timestamp ASC, id ASC"
        
        c = get_db_connection().cursor()
        c.execute(q, p)
        rows = c.fetchall()
        c.connection.close()
        
        grouped = {}
        for r in rows:
            grouped.setdefault(r["agent"], []).append(r)
        
        res = {}
        for a, evts in grouped.items():
            res[a] = len(_dedupe_attempt_events(evts))
        return res

    all_missed = fetch_all_attempts("RINGNOANSWER")
    all_cancelled = fetch_all_attempts("RINGCANCELED")
    
    # Bulk fetch agent lifecycle events
    q_all_evts = "SELECT agent, event_type, timestamp, reason FROM queue_agent_events WHERE event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE')"
    p_all_evts = []
    if filters.get("date_from"):
        q_all_evts += " AND timestamp >= ?"
        p_all_evts.append(filters["date_from"] + " 00:00:00")
    if filters.get("date_to"):
        q_all_evts += " AND timestamp <= ?"
        p_all_evts.append(filters["date_to"] + " 23:59:59")
    if filters.get("time_from"):
        q_all_evts += " AND time(timestamp) >= ?"
        p_all_evts.append(filters["time_from"] + ":00" if len(filters["time_from"]) == 5 else filters["time_from"])
    if filters.get("time_to"):
        q_all_evts += " AND time(timestamp) <= ?"
        p_all_evts.append(filters["time_to"] + ":59" if len(filters["time_to"]) == 5 else filters["time_to"])
    if filters.get("queue") and filters["queue"] != "all":
        q_all_evts += " AND queue = ?"
        p_all_evts.append(filters["queue"])
    scope_sql, scope_params = _queue_scope_sql(filters, "queue")
    q_all_evts += scope_sql
    p_all_evts.extend(scope_params)
    q_all_evts += " ORDER BY timestamp ASC"
    
    conn_tmp = get_db_connection()
    c_tmp = conn_tmp.cursor()
    c_tmp.execute(q_all_evts, p_all_evts)
    all_lifecycle = c_tmp.fetchall()
    conn_tmp.close()
    
    grouped_lifecycle = {}
    for r in all_lifecycle:
        grouped_lifecycle.setdefault(r["agent"], []).append(r)
    # --------------------------------
"""

content = content.replace("    results = []\n    for a in agent_rows:", bulk_helpers + "\n    results = []\n    for a in agent_rows:")

# 3. Replace N+1 queries with bulk maplookups
replace_from = """        # Count real attempts, collapsing only same-second collector/QueueLog
        # duplicates. A later ring after a no-answer remains a separate retry.
        missed_count = _count_agent_attempt_events(conn, ext, "RINGNOANSWER", filters)
        cancelled_count = _count_agent_attempt_events(conn, ext, "RINGCANCELED", filters)
        
        # LOGIN/LOGOUT/PAUSE/UNPAUSE events for duration calculation
        q_evts = "SELECT event_type, timestamp, reason FROM queue_agent_events WHERE agent = ? AND event_type IN ('LOGIN', 'LOGOUT', 'PAUSE', 'UNPAUSE')"
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
        evts = c.fetchall()"""

replace_to = """        # Count real attempts (using bulk map)
        missed_count = all_missed.get(ext, 0)
        cancelled_count = all_cancelled.get(ext, 0)
        
        # LOGIN/LOGOUT/PAUSE/UNPAUSE events (using bulk map)
        evts = grouped_lifecycle.get(ext, [])"""

content = content.replace(replace_from, replace_to)

with open("/root/RCM_7021/rcm_queue_db.py", "w") as f:
    f.write(content)

