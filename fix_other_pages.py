import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

missing_cards = [
    ".studio-card", ".audio-preview-container",
    ".ql-card", ".ql-agents-card", ".ql-queue-card", ".wb-modal",
    ".um-panel", ".pm-panel", ".pm-scope-card"
]

new_block = ",\n".join(missing_cards) + ",\n" + ",\n".join([f"[data-theme='light'] {c}" for c in missing_cards]) + ",\n" + ",\n".join([f"[data-theme='dark'] {c}" for c in missing_cards])

new_css = f"""
/* Missing Pages Classes */
{new_block} {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow) !important;
    background-image: var(--glass-highlight) !important;
    border-radius: 12px !important;
}}

/* Force Text Colors to Adapt */
.studio-card-value, .studio-card-title, .studio-card-desc,
.ql-card, .ql-card h1, .ql-card h2, .ql-card h3, .wb-modal, .wb-card-sub, .ql-section-sub,
.um-modal-head h2, .um-panel, .um-control,
.pm-modal-head h2, .pm-panel, .pm-control, .pm-scope-card,
.cdr-modal-header h2, .cdr-call-summary strong, .cdr-timeline-item strong, .cdr-timeline-item span, .cdr-journey-step-top strong, .cdr-journey-step-bottom span,
.audio-preview-container, .modal-content, .header-panel h1, .header-panel h2 {{
    color: var(--text-main) !important;
}}

/* Muted Text */
.cdr-timeline-title, .cdr-timeline-item p, .cdr-call-summary span {{
    color: var(--text-muted) !important;
}}

/* Hardcoded Modal Text Fixes */
.um-control, .pm-control {{
    background: rgba(0, 0, 0, 0.1) !important;
}}
"""

with open("static/css/glass_theme.css", "w") as f:
    f.write(css + "\n" + new_css)
