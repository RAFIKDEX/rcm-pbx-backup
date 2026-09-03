import sys
import json
sys.path.append('/root/RCM_7021')
import db

filters = {
    "date_from": "2020-01-01",
    "date_to": "2028-01-01",
    "time_from": "",
    "time_to": "",
    "queue": "all",
    "agent": "all",
    "agent_name": "",
    "caller": "",
    "call_status": "all",
    "wait_time": "all",
    "talk_time": "all",
    "no_seed": False,
    "page": 1,
    "limit": 10
}

try:
    calls = db.get_filtered_queue_stats(filters)
    print("Total calls fetched from DB:", len(calls))
    
    answered = [c for c in calls if (c.get("status") or "").upper() == "ANSWERED"]
    answered_count = len(answered)
    
    avg_hold = int(sum(c.get("hold_time", 0) for c in answered) / answered_count) if answered_count else 0
    longest_hold = max((c.get("hold_time", 0) for c in answered), default=0)
    
    avg_talk = int(sum(c.get("talk_time", 0) for c in answered) / answered_count) if answered_count else 0
    
    print("Answered Calls Count:", answered_count)
    print("Avg Hold:", avg_hold, "seconds")
    print("Longest Hold:", longest_hold, "seconds")
    print("Avg Talk:", avg_talk, "seconds")
    
    if answered_count > 0:
        print("\nSample Answered Call Data:")
        print(json.dumps(answered[0], indent=2))
except Exception as e:
    print("Error:", e)