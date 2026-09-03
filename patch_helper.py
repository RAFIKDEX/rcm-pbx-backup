import re

filepath = "/root/RCM_7021/asterisk_helper.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""    video_support = bool\(data\.get\("video_support", False\)\)
    endpoint_codecs = codecs
    if video_support:
        codec_parts = endpoint_codecs\.split\(","\) if endpoint_codecs else \[\]
        for codec in VIDEO_CODECS:
            if codec not in codec_parts:
                codec_parts\.append\(codec\)
        endpoint_codecs = ","\.join\(codec_parts\)"""

replacement = """    video_support = bool(data.get("video_support", False))
    endpoint_codecs = codecs
    has_video = any(v in endpoint_codecs.lower() for v in VIDEO_CODECS)
    if video_support and not has_video:
        endpoint_codecs = endpoint_codecs + ",h264,vp8" if endpoint_codecs else "h264,vp8"
    
    # Update video_support flag based on codecs presence as well
    if has_video:
        video_support = True"""

content = re.sub(target, replacement, content)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
