with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "cat_name" in line and "def get_date_threshold" not in line and "cat_name ==" not in line:
        if "def scan_cdr" in "".join(lines[max(0, i-5):i]):
            lines[i] = line.replace("cat_name", '"CDR"')
        elif "def clean_cdr" in "".join(lines[max(0, i-5):i]):
            lines[i] = line.replace("cat_name", '"CDR"')
        elif "def scan_dex" in "".join(lines[max(0, i-5):i]):
            lines[i] = line.replace("cat_name", '"Zero_Config"')
        elif "def scan_queue" in "".join(lines[max(0, i-5):i]):
            lines[i] = line.replace("cat_name", '"Queue_Stats"')

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.writelines(lines)
