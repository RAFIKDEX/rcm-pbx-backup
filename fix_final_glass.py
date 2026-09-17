import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# Make sure --panel-dark and --bg-dark are transparent or glassy in BOTH modes
# Actually, I'll just add it to the :root blocks.
css = css.replace("--sidebar-bg: rgba(255, 255, 255, 0.02);", "--sidebar-bg: rgba(255, 255, 255, 0.02);\n    --panel-dark: var(--glass-bg) !important;\n    --bg-dark: transparent !important;")

# For light mode, it already has:
#    --bg-dark: transparent;
#    --panel-dark: transparent;
# I'll upgrade them to var(--glass-bg) and transparent !important
css = css.replace("--panel-dark: transparent;", "--panel-dark: var(--glass-bg) !important;")
css = css.replace("--bg-dark: transparent;", "--bg-dark: transparent !important;")

# Add the missing panel classes to the all_selectors block.
missing = [
    ".ld-card", ".info-card", ".res-card", ".ts-card", ".ext-card", ".trk-card", ".intf-card",
    ".cdr-filters", ".cdr-modal-dialog", ".form-section", ".ivr-section", ".q-section", ".pbx-section", ".ext-section",
    ".dashboard-widget", ".dashboard-wrapper"
]

# We can append these to the CSS by adding a new block at the end.
new_block = ",\n".join(missing) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing])

new_css = f"""
/* Missing Dashboard & Form Classes */
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

print("Applied final fixes to glass theme.")
