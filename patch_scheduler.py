import re

with open('/root/RCM_7021/scheduler_service.py', 'r') as f:
    content = f.read()

# Add the new function before start_background_scheduler
new_func = """
def check_and_run_external_storage_export():
    try:
        from export_worker import ExportWorker
        worker = ExportWorker()
        worker.execute_scheduled_policies()
        worker.close()
    except Exception as e:
        print(f"[SCHEDULER] External Storage Export Error: {e}")

def start_background_scheduler():
"""

content = content.replace("def start_background_scheduler():", new_func)

# Add the try block inside the while loop
hook = """
            try:
                check_and_run_auto_cleanup()
            except Exception as e:
                print(f"[SCHEDULER] Error in check_and_run_auto_cleanup: {e}")
"""

hook_new = hook + """
            try:
                check_and_run_external_storage_export()
            except Exception as e:
                print(f"[SCHEDULER] Error in check_and_run_external_storage_export: {e}")
"""

content = content.replace(hook, hook_new)

with open('/root/RCM_7021/scheduler_service.py', 'w') as f:
    f.write(content)
