import json

transcript_path = "/root/.gemini/antigravity-cli/brain/cc95de8f-8fcf-434c-9be6-2646f119f550/.system_generated/logs/transcript_full.jsonl"
with open(transcript_path, "r") as f:
    for line in f:
        if "cat -n /root/RCM_7021/templates/ext_storage_dashboard.html | sed -n '40,80p'" in line:
            print("Found tool call")
        elif "ext_storage_dashboard.html:43" in line or "Recent Export Jobs" in line:
            print(line[:500])
