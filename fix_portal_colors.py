import re

with open("static/css/extension_portal.css", "r") as f:
    css = f.read()

# Replace hardcoded light text
light_texts = ['#fff', '#ffffff', '#e2e8f0', '#cbd5e1', '#dbeafe']
for color in light_texts:
    css = re.sub(rf'color:\s*{color}\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)

# Replace hardcoded gray text
gray_texts = ['#94a3b8', '#a8b5c6', '#7c8aa0', '#8492a6', '#718096', '#78879a']
for color in gray_texts:
    css = re.sub(rf'color:\s*{color}\s*;', 'color: var(--text-muted);', css, flags=re.IGNORECASE)

# Replace dark backgrounds
css = re.sub(r'background:\s*#0f172a\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#1e293b\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#334155\s*;', 'background: rgba(0,0,0,0.2);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#0c0f1d\s*;', 'background: transparent;', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#0b0f19\s*;', 'background: rgba(0,0,0,0.1);', css, flags=re.IGNORECASE)

with open("static/css/extension_portal.css", "w") as f:
    f.write(css)

print("extension_portal.css colors fixed.")
