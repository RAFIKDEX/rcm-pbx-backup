#!/usr/bin/env python3
import sys
import os
sys.path.append('/root/RCM_7021')

import sqlite3
from storage_providers import get_provider_instance

def main():
    try:
        conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
        conn.row_factory = sqlite3.Row
        providers = conn.execute("SELECT id FROM external_storage_providers WHERE enabled=1").fetchall()
        for p in providers:
            try:
                print(f"Attempting to auto-mount provider {p['id']}...")
                prov = get_provider_instance(p['id'])
                if prov:
                    success = prov.connect()
                    if success:
                        print(f"Successfully mounted provider {p['id']}.")
                    else:
                        print(f"Failed to mount provider {p['id']}: {prov.last_error}")
            except Exception as e:
                print(f"Error handling provider {p['id']}: {e}")
        conn.close()
    except Exception as e:
        print(f"Critical error in auto-mount: {e}")

if __name__ == "__main__":
    main()
