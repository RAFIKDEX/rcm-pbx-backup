import re

filepath = "/root/RCM_7021/templates/extension_form.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""<div class="form-group">\s*<label>Allowed Codecs</label>\s*<div class="codec-grid".*?{% endfor %}\s*</div>\s*</div>"""

replacement = """<div class="form-group">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
        <label style="margin: 0;">Audio Codecs</label>
        <label class="switch-group" style="margin: 0; font-size: 0.9rem;">
            <label class="switch">
                <input type="checkbox" name="video_support" {% if extension and extension.video_support %}checked{% endif %}>
                <span class="slider"></span>
            </label>
            <span style="margin-left: 10px;">Enable Video Support</span>
        </label>
    </div>
    <div class="codec-grid">
        {% set selected_codecs = (extension.codecs.split(',') if extension and extension.codecs else ['ulaw', 'alaw']) %}
        {% for codec, label in [('alaw', 'G.711 A-Law'), ('ulaw', 'G.711 U-Law'), ('g722', 'G.722 HD'), ('g729', 'G.729'), ('gsm', 'GSM'), ('opus', 'Opus')] %}
        <label class="codec-option">
            <input type="checkbox" name="codecs[]" value="{{ codec }}" {% if codec in selected_codecs %}checked{% endif %}>
            <span>{{ label }}</span>
        </label>
        {% endfor %}
    </div>
</div>

<div class="form-group" style="margin-top: 15px;">
    <label>Video Codecs</label>
    <div class="codec-grid">
        {% for codec, label in [('h264', 'H.264'), ('vp8', 'VP8'), ('vp9', 'VP9'), ('h263', 'H.263')] %}
        <label class="codec-option">
            <input type="checkbox" name="codecs[]" value="{{ codec }}" {% if codec in selected_codecs %}checked{% endif %}>
            <span>{{ label }}</span>
        </label>
        {% endfor %}
    </div>
</div>"""

content = re.sub(target, replacement, content, flags=re.DOTALL)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
