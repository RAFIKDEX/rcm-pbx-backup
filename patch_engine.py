import re

with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

# Add scanning call
scan_call = """            self.update_progress(70, {"phase": "Scanning Queue Stats"})
            self.scan_queue()
            self.update_progress(85, {"phase": "Scanning Operation Logs"})
            self.scan_operation_log()
"""
content = content.replace('            self.update_progress(70, {"phase": "Scanning Queue Stats"})\n            self.scan_queue()\n', scan_call)

# Add cleaning call
clean_call = """            self.update_progress(70, {"phase": "Cleaning Queue Stats"})
            if self.config.get("Queue_Stats"):
                self.clean_queue()
                if self.cancel_flag: raise Exception("Cancelled")

            self.update_progress(85, {"phase": "Cleaning Operation Logs"})
            if self.config.get("Operation_Log"):
                self.clean_operation_log()
                if self.cancel_flag: raise Exception("Cancelled")
"""
content = content.replace('            self.update_progress(70, {"phase": "Cleaning Queue Stats"})\n            if self.config.get("Queue_Stats"):\n                self.clean_queue()\n                if self.cancel_flag: raise Exception("Cancelled")\n', clean_call)

# Add methods at the end
methods = """
    def scan_operation_log(self):
        if not self.config.get("Operation_Log"): return
        cat = self.config["Operation_Log"]
        threshold = self.get_date_threshold(cat)
        count = 0
        size = 0
        try:
            if os.path.exists(OPERATION_LOG):
                size = os.path.getsize(OPERATION_LOG)
                with open(OPERATION_LOG, "r") as f:
                    data = json.load(f)
                    logs = data.get("logs", [])
                    # Count logs older than threshold
                    for log in logs:
                        # Assuming log has 'timestamp' 
                        if log.get('timestamp', '9999-99-99') <= threshold:
                            count += 1
        except Exception:
            pass
        self.stats["Operation_Log"] = {"count": count, "size": size, "oldest": "-", "newest": "-"}

    def clean_operation_log(self):
        cat = self.config["Operation_Log"]
        threshold = self.get_date_threshold(cat)
        try:
            if os.path.exists(OPERATION_LOG):
                with open(OPERATION_LOG, "r") as f:
                    data = json.load(f)
                
                original_logs = data.get("logs", [])
                new_logs = [log for log in original_logs if log.get('timestamp', '9999-99-99') > threshold]
                
                deleted = len(original_logs) - len(new_logs)
                if deleted > 0:
                    data["logs"] = new_logs
                    # Save back safely
                    with open(OPERATION_LOG + ".tmp", "w") as f:
                        json.dump(data, f)
                    os.replace(OPERATION_LOG + ".tmp", OPERATION_LOG)
                    self.deleted_count += deleted
        except Exception:
            self.failed_count += 1
"""
content += methods

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)

