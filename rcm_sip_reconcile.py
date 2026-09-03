#!/usr/bin/env python3
import sys
import fcntl

sys.path.append('/root/RCM_7021')
import sip_security_manager

def main():
    lock_file = open('/tmp/rcm_sip_reconcile.lock', 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sip_security_manager.reconcile_bans()
    except BlockingIOError:
        print("Reconciliation is already running.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error during reconciliation: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

if __name__ == '__main__':
    main()
