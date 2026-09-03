import rcm_queue_db
calls = rcm_queue_db.get_filtered_queue_stats({})
analyzed = [c for c in calls if c.get("ai_sentiment")]
print("Found", len(analyzed), "analyzed calls")
if analyzed: print(analyzed[0])
