import re
import glob

for filename in ["templates/cleanup_auto.html", "templates/cleanup_manual.html"]:
    with open(filename, "r") as f:
        html = f.read()

    # Replace colors
    html = re.sub(r'color:\s*#f8fafc\s*;', 'color: var(--text-main);', html, flags=re.IGNORECASE)
    html = re.sub(r'color:\s*white\s*;', 'color: var(--text-main);', html, flags=re.IGNORECASE)
    html = re.sub(r'color:\s*#f1f5f9\s*;', 'color: var(--text-main);', html, flags=re.IGNORECASE)
    html = re.sub(r'color:\s*#e2e8f0\s*;', 'color: var(--text-main);', html, flags=re.IGNORECASE)

    html = re.sub(r'color:\s*#cbd5e1\s*;', 'color: var(--text-muted);', html, flags=re.IGNORECASE)
    html = re.sub(r'color:\s*#94a3b8\s*;', 'color: var(--text-muted);', html, flags=re.IGNORECASE)
    html = re.sub(r'color:\s*#64748b\s*;', 'color: var(--text-muted);', html, flags=re.IGNORECASE)
    html = re.sub(r'color:\s*#475569\s*;', 'color: var(--text-muted);', html, flags=re.IGNORECASE)

    # Gradients
    html = re.sub(r'background: linear-gradient\([^;]+\);', '', html)
    html = re.sub(r'-webkit-background-clip: text;', '', html)
    html = re.sub(r'-webkit-text-fill-color: transparent;', '', html)

    with open(filename, "w") as f:
        f.write(html)

print("Fixed cleanup templates")
