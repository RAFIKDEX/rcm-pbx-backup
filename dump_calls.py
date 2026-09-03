import time
import subprocess
import json

def get_channels():
    out = subprocess.run(["asterisk", "-rx", "core show channels concise"], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line]

def get_channel_detail(chan):
    out = subprocess.run(["asterisk", "-rx", f"core show channel {chan}"], capture_output=True, text=True).stdout
    return out

print("Waiting for active calls...")
for _ in range(60):
    chans = get_channels()
    if len(chans) >= 2:
        print("Found active calls! Dumping details...")
        details = {}
        for c in chans:
            parts = c.split('!')
            chan_name = parts[0]
            details[chan_name] = {
                "concise": c,
                "full": get_channel_detail(chan_name)
            }
        
        with open("/tmp/active_calls_dump.json", "w") as f:
            json.dump(details, f, indent=4)
        print("Done!")
        break
    time.sleep(1)
