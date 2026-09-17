import re

with open("app.py", "r") as f:
    content = f.read()

# We need to extract the entire _query_cdr_records function and replace it.
# Let's find the start and end of it.
import ast
import sys

# Locate function
start_idx = content.find("def _query_cdr_records(")
if start_idx == -1:
    print("Function not found!")
    sys.exit(1)

# Find the next function definition to know where it ends
end_idx = content.find("\ndef _portal_extension()", start_idx)
if end_idx == -1:
    print("End not found!")
    sys.exit(1)

new_func = """def _query_cdr_records(args, page=1, limit=10, for_export=False):
    db.sync_cdr_records()
    date_from = args.get('date_from', '').strip()
    date_to = args.get('date_to', '').strip()
    extension = args.get('extension', '').strip()
    status = args.get('status', '').strip()
    search_q = args.get('q', '').strip()
    call_type = args.get('call_type', '').strip()
    call_from = args.get('call_from', '').strip()
    call_to = args.get('call_to', '').strip()
    min_duration = args.get('min_duration', '').strip()
    max_duration = args.get('max_duration', '').strip()

    conn = db.get_db()
    cursor = conn.cursor()
    query_parts = []
    params = []
    
    if date_from:
        query_parts.append("start_time >= ?")
        params.append(date_from if len(date_from) > 10 else date_from + " 00:00:00")
    if date_to:
        query_parts.append("start_time <= ?")
        params.append(date_to if len(date_to) > 10 else date_to + " 23:59:59")
    if extension:
        q_ext = f"%{extension}%"
        query_parts.append("(src LIKE ? OR dst LIKE ? OR clid LIKE ?)")
        params.extend([q_ext, q_ext, q_ext])
        
    allowed_extensions = reporting_scope_allowed_extensions('cdr_reports')
    if allowed_extensions is not None:
        if not allowed_extensions:
            query_parts.append("1 = 0")
        else:
            placeholders = ",".join("?" for _ in allowed_extensions)
            query_parts.append(f"(src IN ({placeholders}) OR dst IN ({placeholders}))")
            allowed_values = sorted(allowed_extensions)
            params.extend(allowed_values + allowed_values)
            
    if search_q:
        q_wild = f"%{search_q}%"
        query_parts.append("(src LIKE ? OR dst LIKE ? OR clid LIKE ? OR uniqueid LIKE ? OR linkedid LIKE ? OR COALESCE(channel,'') LIKE ? OR COALESCE(dstchannel,'') LIKE ? OR COALESCE(lastapp,'') LIKE ? OR COALESCE(lastdata,'') LIKE ? OR COALESCE(userfield,'') LIKE ?)")
        params.extend([q_wild] * 10)
        
    if call_from:
        q_src = f"%{call_from}%"
        query_parts.append("(src LIKE ? OR clid LIKE ?)")
        params.extend([q_src, q_src])
    if call_to:
        query_parts.append("dst LIKE ?")
        params.append(f"%{call_to}%")
        
    if call_type:
        try:
            trunks_list = db.get_all_trunks()
            trunk_names = [str(t.get("name") or "").strip() for t in trunks_list if str(t.get("name") or "").strip()]
        except Exception:
            trunk_names = []
            
        if not trunk_names:
            if call_type == 'internal':
                query_parts.append("1 = 1")
            else:
                query_parts.append("1 = 0")
        else:
            inbound_cond = " OR ".join(["COALESCE(channel, '') LIKE ?" for _ in trunk_names])
            outbound_cond = " OR ".join(["COALESCE(dstchannel, '') LIKE ?" for _ in trunk_names])
            inbound_params = [f"%/{t}-%" for t in trunk_names]
            outbound_params = [f"%/{t}-%" for t in trunk_names]
            
            if call_type == 'inbound':
                query_parts.append(f"({inbound_cond})")
                params.extend(inbound_params)
            elif call_type == 'outbound':
                query_parts.append(f"({outbound_cond})")
                params.extend(outbound_params)
            elif call_type == 'internal':
                query_parts.append(f"({inbound_cond} IS NOT 1 AND {outbound_cond} IS NOT 1)")
                params.extend(inbound_params + outbound_params)
                
    if status:
        requested_status = status.upper().replace("_", " ")
        query_parts.append("UPPER(disposition) = ?")
        params.append(requested_status)
    if min_duration.isdigit():
        query_parts.append("CAST(billsec AS INTEGER) >= ?")
        params.append(int(min_duration))
    if max_duration.isdigit():
        query_parts.append("CAST(billsec AS INTEGER) <= ?")
        params.append(int(max_duration))

    where_clause = " WHERE " + " AND ".join(query_parts) if query_parts else ""
    
    # 1. Stats Query (Aggregated on logical calls)
    stats_query = f\"\"\"
        SELECT 
            COUNT(DISTINCT COALESCE(NULLIF(linkedid, ''), uniqueid)) as total_calls,
            SUM(billsec_max) as total_talk_time,
            SUM(CASE WHEN disp_max = 'ANSWERED' THEN 1 ELSE 0 END) as answered_count,
            SUM(CASE WHEN disp_max = 'NO ANSWER' THEN 1 ELSE 0 END) as missed_count
        FROM (
            SELECT 
                COALESCE(NULLIF(linkedid, ''), uniqueid) as grp, 
                MAX(CAST(billsec AS INTEGER)) as billsec_max, 
                MAX(UPPER(disposition)) as disp_max
            FROM cdr_records
            {where_clause}
            GROUP BY COALESCE(NULLIF(linkedid, ''), uniqueid)
        )
    \"\"\"
    
    cursor.execute(stats_query, params)
    stat_row = cursor.fetchone()
    total_rows = stat_row[0] if stat_row and stat_row[0] else 0
    total_talk_sec = stat_row[1] if stat_row and stat_row[1] else 0
    answered_count = stat_row[2] if stat_row and stat_row[2] else 0
    missed_count = stat_row[3] if stat_row and stat_row[3] else 0
    
    answered_ratio = round((answered_count / total_rows) * 100) if total_rows else 0
    missed_ratio = round((missed_count / total_rows) * 100) if total_rows else 0
    
    h, remainder = divmod(total_talk_sec, 3600)
    m, s = divmod(remainder, 60)
    stats_dict = {
        "total_calls": total_rows,
        "total_talk_time": f"{h}h {m}m {s}s" if h else f"{m}m {s}s",
        "answered_ratio": answered_ratio,
        "missed_ratio": missed_ratio,
    }

    # 2. Paginated rows Query
    if for_export:
        # Fetch all matching logical calls
        query = f\"\"\"
            SELECT * FROM cdr_records 
            WHERE COALESCE(NULLIF(linkedid, ''), uniqueid) IN (
                SELECT DISTINCT COALESCE(NULLIF(linkedid, ''), uniqueid)
                FROM cdr_records {where_clause}
            )
            ORDER BY start_time DESC
        \"\"\"
        cursor.execute(query, params)
    else:
        # Fetch only the limited logical calls
        offset = (page - 1) * limit
        query = f\"\"\"
            SELECT * FROM cdr_records 
            WHERE COALESCE(NULLIF(linkedid, ''), uniqueid) IN (
                SELECT group_id FROM (
                    SELECT COALESCE(NULLIF(linkedid, ''), uniqueid) as group_id, MAX(start_time) as max_time
                    FROM cdr_records 
                    {where_clause}
                    GROUP BY group_id
                    ORDER BY max_time DESC
                    LIMIT {limit} OFFSET {offset}
                )
            )
            ORDER BY start_time DESC
        \"\"\"
        cursor.execute(query, params)
        
    raw_rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    all_ids = []
    for row in raw_rows:
        all_ids.extend([row.get("uniqueid"), row.get("linkedid")])
        
    queue_statuses = _cdr_queue_statuses(all_ids)
    queue_talk_times = _cdr_queue_talk_times(all_ids)
    queue_details = _cdr_queue_details(all_ids)
    
    rows = _cdr_group_rows(raw_rows, queue_statuses, queue_talk_times, queue_details)
    rows.sort(key=lambda row: str(row.get("start_time") or ""), reverse=True)
    
    # We don't slice again if not export, since SQL did the LIMIT
    # Except if the grouping logic returned slightly different count, but it shouldn't.

    if for_export:
        return rows, stats_dict, [], total_rows

    import rcm_queue_db
    queue_names = {
        str(q["id"]): q["name"]
        for q in rcm_queue_db.get_queues()
    }
    for row in rows:
        qn = str(row.get("queue_number") or "").strip()
        if qn and not row.get("queue_name") and qn in queue_names:
            row["queue_name"] = queue_names[qn]

    return rows, stats_dict, [], total_rows
"""

new_content = content[:start_idx] + new_func + content[end_idx:]

with open("app.py", "w") as f:
    f.write(new_content)

print("Replaced _query_cdr_records in app.py")
