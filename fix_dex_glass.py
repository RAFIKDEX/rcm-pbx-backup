import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

missing = [
    ".dex-config-card", ".dex-model-status-card", ".dex-blf-card"
]
new_block = ",\n".join(missing) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing])

new_css = f"""
/* Missing DEX Card Classes */
{new_block} {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow) !important;
    background-image: var(--glass-highlight) !important;
    border-radius: 12px !important;
}}
"""

with open("static/css/glass_theme.css", "w") as f:
    f.write(css + "\n" + new_css)
