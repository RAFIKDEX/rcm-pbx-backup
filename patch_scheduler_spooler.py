import re

with open('/root/RCM_7021/scheduler_service.py', 'r') as f:
    content = f.read()

target = """def check_and_run_external_storage_export():
    try:
        from export_worker import ExportWorker
        worker = ExportWorker()
        worker.execute_scheduled_policies()
        worker.close()
    except Exception as e:
        print(f"[SCHEDULER] External Storage Export Error: {e}")"""

replacement = """def check_and_run_external_storage_export():
    try:
        from storage_spooler import StorageSpooler
        spooler = StorageSpooler()
        spooler.process_new_recordings()
        spooler.close()
    except Exception as e:
        print(f"[SCHEDULER] Storage Spooler Error: {e}")"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/scheduler_service.py', 'w') as f:
        f.write(content)
