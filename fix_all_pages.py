with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# We need to find the sections where we apply backgrounds to .card and .panel and append the other classes.

glass_classes = [
    ".action-card", ".cdr-stat-card", ".contact-dialog-card", ".credentials-card",
    ".dex-modal-card", ".dex-progress-card", ".firewall-card", ".firewall-summary-card",
    ".ivr-check-card", ".ivr-header-card", ".login-card", ".pbx-header-card",
    ".pm-modal-card", ".preview-card", ".q-check-card", ".q-header-card",
    ".sip-status-card", ".stat-card", ".storage-card", ".studio-card",
    ".survey-card", ".um-modal-card", ".wb-card-sub",
    ".cdr-chart-panel", ".cdr-table-panel", ".content-panel", ".sip-panel",
    ".tab-content", ".info-box"
]

# Create a robust selector string
dark_selectors = ", \n".join([f"{c}, [data-theme='dark'] {c}" for c in glass_classes])
light_selectors = ", \n".join([f"[data-theme='light'] {c}" for c in glass_classes])

all_selectors = dark_selectors + ", \n" + light_selectors

new_css = f"""
/* Apply glass to ALL specific page cards and panels */
{all_selectors} {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
    border-radius: 12px !important;
}}
"""

# Now, we also need to fix specificity for light mode overrides that might exist for these specific classes
specificity_fixes = f"""
/* Fix Specificity for all these classes */
{all_selectors} {{
    background: var(--glass-bg) !important;
}}
"""

css = css.replace("/* ====================================================", new_css + "\n/* ====================================================")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

