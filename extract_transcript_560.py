import json

transcript_path = "/root/.gemini/antigravity-cli/brain/cc95de8f-8fcf-434c-9be6-2646f119f550/.system_generated/logs/transcript_full.jsonl"
with open(transcript_path, "r") as f:
    for line in f:
        if '"step_index":560,' in line:
            data = json.loads(line)
            print(data['tool_calls'][0]['args']['CommandLine'])
