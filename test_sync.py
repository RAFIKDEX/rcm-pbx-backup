import sys
sys.path.append("/root/RCM_7021")
import db
import asterisk_helper

queues = db.get_queues()
print("Loaded queues:", queues)
asterisk_helper.sync_queue_dialplan(queues)
print("Sync complete.")
