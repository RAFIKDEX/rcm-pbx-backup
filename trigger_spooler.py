#!/usr/bin/env python3
import sys
import os

# Ensure the script can find local modules
sys.path.append('/root/RCM_7021')

try:
    from storage_spooler import StorageSpooler
    s = StorageSpooler()
    s.process_new_recordings()
    s.close()
except Exception as e:
    with open('/var/log/rcm_spooler_cron.log', 'a') as f:
        f.write(f"Error: {e}\n")
