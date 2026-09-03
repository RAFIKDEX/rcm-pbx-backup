import asterisk_helper
import db

asterisk_helper.sync_inbound_routes_dialplan()
asterisk_helper.sync_outbound_routes(db.get_outbound_routes())
asterisk_helper.sync_queue_dialplan(db.get_queues())
print("Dialplans synced successfully.")
