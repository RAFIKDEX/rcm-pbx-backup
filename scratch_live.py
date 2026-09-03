def get_live_dashboard_status():
    global _LIVE_DASHBOARD_CACHE
    now_ts = time.time()
    if now_ts - _LIVE_DASHBOARD_CACHE["timestamp"] < 1.0 and _LIVE_DASHBOARD_CACHE["data"] is not None:
        return _LIVE_DASHBOARD_CACHE["data"]
        
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        c.execute("SELECT * FROM queues")
        db_queues = c.fetchall()
        
        queues = {}
        active_calls = []
        now = datetime.now()
        today_start = now.strftime("%Y-%m-%d") + " 00:00:00"
        
        # 1. Bulk fetch stats
        c.execute("""
            SELECT 
                c.queue_id,
                SUM(CASE WHEN c.status = 'ANSWERED' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN c.status IN ('ABANDONED', 'CANCELLED', 'NO ANSWER', 'TIMEOUT') THEN 1 ELSE 0 END) as abandoned,
                AVG(c.wait_time) as avg_hold,
                AVG(CASE WHEN c.status = 'ANSWERED' THEN c.talk_time ELSE NULL END) as avg_talk,
                SUM(CASE WHEN c.status = 'ANSWERED' AND c.wait_time <= COALESCE(q.servicelevel, 30) THEN 1 ELSE 0 END) as sla_met
            FROM queue_calls c
            LEFT JOIN queues q ON c.queue_id = q.queue_number
            WHERE c.entry_time >= ?
            GROUP BY c.queue_id
        """, (today_start,))
        stats_by_queue = {row["queue_id"]: dict(row) for row in c.fetchall()}
        
        # 2. Bulk fetch live rows
        c.execute("SELECT * FROM queue_live ORDER BY position ASC")
        live_rows_by_queue = {}
        for row in c.fetchall():
            live_rows_by_queue.setdefault(row["queue"], []).append(dict(row))
            
        # 3. Bulk fetch active talking calls
        c.execute("""
            SELECT queue_id, uniqueid, caller_number, agent, answer_time 
            FROM queue_calls 
            WHERE status = 'ANSWERED' AND hangup_time IS NULL
        """)
        talking_rows_by_queue = {}
        for row in c.fetchall():
            talking_rows_by_queue.setdefault(row["queue_id"], []).append(dict(row))
            
        # 4. Bulk pre-calculate agent properties
        c.execute("""
            SELECT agent, queue, event_type, timestamp 
            FROM queue_agent_events 
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (today_start,))
        
        agent_pause_durations = {}
        agent_last_events = {}
        pause_starts = {}
        for row in c.fetchall():
            agent_queue_key = (row["agent"], row["queue"])
            evt_type = row["event_type"]
            evt_ts = row["timestamp"]
            
            agent_last_events[agent_queue_key] = evt_ts
            
            try:
                dt = datetime.strptime(evt_ts, "%Y-%m-%d %H:%M:%S")
                if evt_type == 'PAUSE':
                    if agent_queue_key not in pause_starts:
                        pause_starts[agent_queue_key] = dt
                elif evt_type == 'UNPAUSE':
                    if agent_queue_key in pause_starts:
                        dur = int((dt - pause_starts[agent_queue_key]).total_seconds())
                        agent_pause_durations[agent_queue_key] = agent_pause_durations.get(agent_queue_key, 0) + dur
                        del pause_starts[agent_queue_key]
            except Exception:
                pass
                
        for k, start_dt in pause_starts.items():
            dur = int((now - start_dt).total_seconds())
            agent_pause_durations[k] = agent_pause_durations.get(k, 0) + dur

        c.execute("""
            SELECT queue_id, agent, COUNT(*) as cnt
            FROM queue_calls 
            WHERE status = 'ANSWERED' AND entry_time >= ?
            GROUP BY queue_id, agent
        """, (today_start,))
        agent_calls_taken = {}
        for row in c.fetchall():
            agent_ext = str(row["agent"] or "").strip()
            if "/" in agent_ext: agent_ext = agent_ext.split("/")[-1]
            agent_ext = agent_ext.split("@")[0]
            if "-" in agent_ext: agent_ext = agent_ext.split("-")[0]
            key = (agent_ext, row["queue_id"])
            agent_calls_taken[key] = agent_calls_taken.get(key, 0) + row["cnt"]
            
        c.execute("SELECT * FROM queue_agents")
        all_agents_db = c.fetchall()
        agents_by_queue = {}
        for a in all_agents_db:
            agents_by_queue.setdefault(a["queue_id"], []).append(dict(a))

        def clean_agent_ext(agent):
            agent = str(agent or "").strip()
            if "/" in agent: agent = agent.split("/")[-1]
            agent = agent.split("@")[0]
            if "-" in agent: agent = agent.split("-")[0]
            return agent

        for q in db_queues:
            qnum = q["queue_number"]
            qname = q["queue_name"]
            servicelevel = q["servicelevel"] if "servicelevel" in q.keys() else 30
            
            stats = stats_by_queue.get(qnum, {})
            completed = stats.get("completed") or 0
            abandoned = stats.get("abandoned") or 0
            total = completed + abandoned
            avg_hold = int(stats.get("avg_hold") or 0)
            avg_talk = int(stats.get("avg_talk") or 0)
            
            sla_pct = 100.0
            if total > 0:
                sla_pct = round(((stats.get("sla_met") or 0) / total) * 100, 1)

            live_rows = live_rows_by_queue.get(qnum, [])
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

            talking_rows = talking_rows_by_queue.get(qnum, [])
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

            all_agents = agents_by_queue.get(qnum, [])
            agents_active = [a for a in all_agents if a["status"] != 'OFFLINE']
            q_agents = len(all_agents)
            q_agents_active = len(agents_active)
            
            def map_agent_details(agent_list, break_limit_sec=3600):
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
                        
                    agent_queue_key = (ext, qnum)
                    status_duration = 0
                    last_evt_ts = agent_last_events.get((f"PJSIP/{ext}", qnum)) or agent_last_events.get((f"SIP/{ext}", qnum)) or agent_last_events.get(agent_queue_key)
                    if last_evt_ts:
                        try:
                            evt_dt = datetime.strptime(last_evt_ts, "%Y-%m-%d %H:%M:%S")
                            status_duration = int((now - evt_dt).total_seconds())
                        except Exception:
                            pass
                            
                    calls_taken = agent_calls_taken.get(agent_queue_key, 0)
                    
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
                            if ac["queue"] == qnum and clean_agent_ext(ac["agent"]) == ext and ac["state"] in ("TALKING", "RINGING"):
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
                    
                    formatted_caller = ""
                    if caller_id:
                        queue_display = qname or qnum
                        formatted_caller = f"{caller_id} ({queue_display} {qnum})"

                    # Combine PJSIP/SIP pause duration keys just in case
                    pause_dur_total = agent_pause_durations.get((f"PJSIP/{ext}", qnum), 0) + agent_pause_durations.get((f"SIP/{ext}", qnum), 0) + agent_pause_durations.get(agent_queue_key, 0)
                    
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
                        "paused_reason": dict(a).get("paused_reason") if paused_val else "",
                        "status_duration": status_duration,
                        "break_limit_sec": break_limit_sec,
                        "total_break_duration_today": pause_dur_total,
                        "calls_taken": calls_taken,
                        "type": a["type"],
                        "login_time": a["login_time"],
                        "logout_time": a["logout_time"],
                        "caller_id": formatted_caller,
                        "call_duration": call_duration,
                        "login_duration": login_duration,
                        "pause_duration": pause_duration
                    })
                return mapped

            import db
            cq_conf = next((x for x in db.get_queues() if x.get("queue_number") == qnum), {})
            try:
                break_limit_sec = int(cq_conf.get("total_break_time", "60")) * 60
            except ValueError:
                break_limit_sec = 3600
                
            members = map_agent_details(agents_active, break_limit_sec)
            roster = map_agent_details(all_agents, break_limit_sec)
            
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
            
        active_calls.sort(key=lambda x: (x["status"] == 'Waiting', x["duration"]), reverse=True)
        
        result = {
            "queues": queues,
            "active_calls": active_calls
        }
        _LIVE_DASHBOARD_CACHE["timestamp"] = now_ts
        _LIVE_DASHBOARD_CACHE["data"] = result
        return result
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"queues": {}, "active_calls": []}
    finally:
        conn.close()
