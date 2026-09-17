import re

with open("static/css/cdr_custom.css", "r") as f:
    css = f.read()

# Replace hardcoded backgrounds with glass-bg
css = re.sub(r'background:\s*rgba\(30,\s*41,\s*59,\s*0\.4\)\s*;', 'background: var(--glass-bg);', css)
css = re.sub(r'background:\s*rgba\(15,\s*23,\s*42,\s*0\.6\)\s*;', 'background: var(--glass-bg);', css)
css = re.sub(r'background:\s*rgba\(30,\s*41,\s*59,\s*0\.5\)\s*;', 'background: var(--glass-bg);', css)
css = re.sub(r'background:\s*rgba\(15,\s*23,\s*42,\s*0\.3\)\s*;', 'background: var(--glass-bg);', css)
css = re.sub(r'background:\s*rgba\(15,\s*23,\s*42,\s*0\.95\)\s*;', 'background: var(--glass-bg);', css)
css = re.sub(r'background:\s*rgba\(15,\s*23,\s*42,\s*0\.62\)\s*;', 'background: var(--glass-bg);', css)
css = re.sub(r'background:\s*linear-gradient\(135deg,\s*rgba\(14, 165, 233, 0\.08\),\s*rgba\(15, 23, 42, 0\.45\)\)\s*;', 'background: var(--glass-bg);', css)

# Replace borders
css = re.sub(r'border(-[a-z]+)?:\s*1px\s+solid\s+rgba\(255,255,255,0\.05\)\s*;', r'border\1: 1px solid var(--border-color);', css, flags=re.IGNORECASE)
css = re.sub(r'border(-[a-z]+)?:\s*1px\s+solid\s+rgba\(255, 255, 255, 0\.07\)\s*;', r'border\1: 1px solid var(--border-color);', css, flags=re.IGNORECASE)
css = re.sub(r'border(-[a-z]+)?:\s*1px\s+solid\s+rgba\(255,255,255,0\.15\)\s*;', r'border\1: 1px solid var(--border-color);', css, flags=re.IGNORECASE)
css = re.sub(r'border-color:\s*rgba\(255,255,255,0\.15\)\s*;', 'border-color: var(--border-color);', css, flags=re.IGNORECASE)
css = re.sub(r'border:\s*3px\s+solid\s+#0f172a\s*;', 'border: 3px solid var(--border-color);', css, flags=re.IGNORECASE)

# Text Colors
css = re.sub(r'color:\s*#bae6fd\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)
css = re.sub(r'color:\s*#60a5fa\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)
css = re.sub(r'color:\s*#f1f5f9\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)

with open("static/css/cdr_custom.css", "w") as f:
    f.write(css)

print("Fixed cdr_custom.css again")
