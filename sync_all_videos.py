import sys
import sqlite3
sys.path.append('/root/RCM_7021')
import db
import asterisk_helper

def sync_all():
    print("Syncing extensions...")
    for ext in db.get_all_extensions():
        asterisk_helper.write_extension_configs(ext)
    
    print("Syncing trunks...")
    for trunk in db.get_all_trunks():
        asterisk_helper.write_trunk_configs(trunk)
        
    asterisk_helper.run_asterisk_cmd("pjsip reload")
    print("Done")

sync_all()
