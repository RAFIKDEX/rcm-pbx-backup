import re

with open("static/css/dex.css", "r") as f:
    css = f.read()

# Replace hardcoded light text with var(--text-main)
light_texts = ['#fff', '#ffffff', '#e2e8f0', '#cbd5e1', '#dbeafe', 'rgba(255,255,255,1)']
for color in light_texts:
    css = re.sub(rf'color:\s*{color}\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)

# Replace hardcoded gray text with var(--text-muted)
gray_texts = ['#94a3b8', '#a8b5c6', '#7c8aa0', '#8492a6', '#718096', '#78879a', '#8190a3', '#aebdce']
for color in gray_texts:
    css = re.sub(rf'color:\s*{color}\s*;', 'color: var(--text-muted);', css, flags=re.IGNORECASE)

# Replace dark backgrounds with transparent or theme variables
css = re.sub(r'background:\s*#0f172a\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#1e293b\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#334155\s*;', 'background: rgba(0,0,0,0.2);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(15,23,42,\.28\)\s*;', 'background: rgba(0,0,0,0.1);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(30,41,59,\.6\)\s*;', 'background: rgba(0,0,0,0.15);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(51,65,85,\.55\)\s*;', 'background: rgba(0,0,0,0.1);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(51,65,85,\.7\)\s*;', 'background: rgba(0,0,0,0.2);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(148,163,184,\.2\)\s*;', 'background: rgba(0,0,0,0.1);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(2,6,23,\.7\)\s*;', 'background: rgba(0,0,0,0.6);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#0c0f1d\s*;', 'background: transparent;', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#0b0f19\s*;', 'background: transparent;', css, flags=re.IGNORECASE)

# Replace border colors with var(--border-color)
css = re.sub(r'border(-[a-z]+)?:\s*1px\s+solid\s+rgba\(148,163,184,\.[0-9]+\)\s*;', r'border\1: 1px solid var(--border-color);', css, flags=re.IGNORECASE)

with open("static/css/dex.css", "w") as f:
    f.write(css)

print("dex.css colors fixed for theme compatibility.")
