with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

content = content.replace('def scan_dex(self):\n        if not self.config.get("Zero_Config"): return\n        cat = self.config["Zero_Config"]\n        threshold = self.get_date_threshold("CDR", cat)', 
                          'def scan_dex(self):\n        if not self.config.get("Zero_Config"): return\n        cat = self.config["Zero_Config"]\n        threshold = self.get_date_threshold("Zero_Config", cat)')

content = content.replace('def scan_queue(self):\n        if not self.config.get("Queue_Stats"): return\n        cat = self.config["Queue_Stats"]\n        threshold = self.get_date_threshold("CDR", cat)', 
                          'def scan_queue(self):\n        if not self.config.get("Queue_Stats"): return\n        cat = self.config["Queue_Stats"]\n        threshold = self.get_date_threshold("Queue_Stats", cat)')

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)
