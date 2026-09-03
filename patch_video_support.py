import re

filepath = "/root/RCM_7021/asterisk_helper.py"

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Patch Extension Endpoints
# Target:
#         "transport": "transport-udp",
#         "dtmf_mode": dtmf_mode,
target_ext = """        "transport": "transport-udp",
        "dtmf_mode": dtmf_mode,"""
replacement_ext = """        "transport": "transport-udp",
        "dtmf_mode": dtmf_mode,
        "max_video_streams": 1 if video_support else 0,"""

content = content.replace(target_ext, replacement_ext)

# 2. Patch Trunk Endpoints
# Look for: if nat:\n            ep_lines.extend(["rtp_symmetric=yes", "rewrite_contact=yes", "force_rport=yes"])
# There are 3 occurrences. I will do a regex sub to add the video check right after `if caller_id: ...` or just before `ep_block = "\n".join(ep_lines) + "\n"`
target_trunk = r'(?P<indent>\s*)ep_block = "\\n"\.join\(ep_lines\) \+ "\\n"'
replacement_trunk = r"""\g<indent>if any(v in codecs.lower() for v in ["h264", "h263", "vp8", "vp9"]):
\g<indent>    ep_lines.append("max_video_streams=1")
\g<indent>ep_block = "\\n".join(ep_lines) + "\\n"
"""
content = re.sub(target_trunk, replacement_trunk, content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
