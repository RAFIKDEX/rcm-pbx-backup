import json
import os
import glob

brain_dir = "/root/.gemini/antigravity-cli/brain"
for convo_dir in glob.glob(f"{brain_dir}/*"):
    if not os.path.isdir(convo_dir):
        continue
    convo_id = os.path.basename(convo_dir)
    full_log_path = os.path.join(convo_dir, ".system_generated/logs/transcript_full.jsonl")
    if not os.path.exists(full_log_path):
        continue
        
    with open(full_log_path, 'r') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if data.get("type") == "PLANNER_RESPONSE":
                    for tc in data.get("tool_calls", []):
                        if tc.get("name") == "write_to_file":
                            target = tc.get("args", {}).get("TargetFile", "")
                            content = tc.get("args", {}).get("CodeContent", "")
                            if target:
                                print(f"--- Found file attempt: {target} in convo {convo_id} ---")
                                print(content[:500] + "...\n")
                                # Save it locally for me to read
                                with open(f"/root/RCM_7021/{os.path.basename(target)}", "w") as out:
                                    out.write(content)
            except Exception as e:
                pass
