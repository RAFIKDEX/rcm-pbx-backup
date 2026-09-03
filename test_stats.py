import sys
sys.path.insert(0, "/root/RCM_7021")
import datetime
import db
import rcm_queue_db

filters = {
    "date_from": "",
    "date_to": "",
    "time_from": "",
    "time_to": "",
    "queue": "all",
    "agent": "all",
    "caller": "",
    "no_seed": False
}

if not filters["date_from"]:
    filters["date_from"] = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
if not filters["date_to"]:
    filters["date_to"] = datetime.datetime.now().strftime("%Y-%m-%d")

print("Filters:", filters)

try:
    calls = db.get_filtered_queue_stats(filters)
    print(f"Retrieved {len(calls)} calls")
    
    agents_perf = db.get_agent_analytics(filters)
    print(f"Retrieved {len(agents_perf)} agent analytics records")

    total_calls = len(calls)
    answered = [c for c in calls if c["status"].upper() == "ANSWERED"]
    abandoned = [c for c in calls if c["status"].upper() == "ABANDONED"]
    cancelled = [c for c in calls if c["status"].upper() in ("CANCELLED", "CANCELED")]
    
    answered_count = len(answered)
    abandoned_count = len(abandoned)
    cancelled_count = len(cancelled)
    
    ans_rate = round((answered_count / total_calls) * 100, 1) if total_calls > 0 else 0
    abandon_rate = round((abandoned_count / total_calls) * 100, 1) if total_calls > 0 else 0
    
    avg_wait = int(sum(c["wait_time"] for c in calls) / total_calls) if total_calls > 0 else 0
    avg_talk = int(sum(c["talk_time"] for c in answered) / answered_count) if answered_count > 0 else 0
    avg_hold = int(sum(c["hold_time"] for c in answered) / answered_count) if answered_count > 0 else 0
    
    longest_wait = max(c["wait_time"] for c in calls) if total_calls > 0 else 0
    longest_talk = max(c["talk_time"] for c in answered) if answered_count > 0 else 0
    shortest_talk = min(c["talk_time"] for c in answered) if answered_count > 0 else 0
    
    sla_met = sum(1 for c in answered if c["wait_time"] <= 20)
    sla_pct = round((sla_met / total_calls) * 100, 1) if total_calls > 0 else 100

    print("KPIs compiled successfully:")
    print("Total calls:", total_calls)
    print("Answered:", answered_count)
    print("Abandoned:", abandoned_count)
    print("Cancelled:", cancelled_count)
    print("Avg Wait:", avg_wait)
    print("Avg Talk:", avg_talk)
    print("SLA %:", sla_pct)

except Exception as e:
    import traceback
    traceback.print_exc()
