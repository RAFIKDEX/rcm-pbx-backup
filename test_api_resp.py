import os, sys
sys.path.append('/root/RCM_7021')
import rcm_queue_db as db
print("Logins:")
for s in db.get_queue_sessions("6500"):
    print(s)
print("\nPauses:")
for p in db.get_queue_pauses("6500"):
    print(p)
