import re

with open("static/css/cdr_custom.css", "r") as f:
    css = f.read()

# Text Colors
css = re.sub(r'color:\s*#fff(fff)?\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)
css = re.sub(r'color:\s*#e2e8f0\s*;', 'color: var(--text-main);', css, flags=re.IGNORECASE)
css = re.sub(r'color:\s*#cbd5e1\s*;', 'color: var(--text-muted);', css, flags=re.IGNORECASE)
css = re.sub(r'color:\s*#94a3b8\s*;', 'color: var(--text-muted);', css, flags=re.IGNORECASE)
css = re.sub(r'color:\s*#64748b\s*;', 'color: var(--text-muted);', css, flags=re.IGNORECASE)

# Borders
css = re.sub(r'border(-[a-z]+)?:\s*1px\s+solid\s+rgba\(255,255,255,0\.1\)\s*;', r'border\1: 1px solid var(--border-color);', css, flags=re.IGNORECASE)
css = re.sub(r'border(-[a-z]+)?:\s*1px\s+solid\s+#1e293b\s*;', r'border\1: 1px solid var(--border-color);', css, flags=re.IGNORECASE)

# Backgrounds
css = re.sub(r'background:\s*#0f172a\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*#1e293b\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background-color:\s*#0f172a\s*;', 'background-color: var(--glass-bg);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(255,255,255,0\.05\)\s*;', 'background: rgba(0,0,0,0.05);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(255,255,255,0\.1\)\s*;', 'background: rgba(0,0,0,0.1);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*rgba\(255,255,255,0\.02\)\s*;', 'background: rgba(0,0,0,0.02);', css, flags=re.IGNORECASE)
css = re.sub(r'background:\s*linear-gradient\(135deg,\s*rgba\(30, 41, 59, 0\.9\),\s*rgba\(15, 23, 42, 0\.9\)\)\s*;', 'background: var(--glass-bg);', css, flags=re.IGNORECASE)

with open("static/css/cdr_custom.css", "w") as f:
    f.write(css)

print("Scrubbed cdr_custom.css")
