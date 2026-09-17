with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

new_rules = """
/* Light Mode Badges Fix */
[data-theme='light'] .badge-available { color: #059669 !important; background: rgba(16, 185, 129, 0.15) !important; border-color: rgba(16, 185, 129, 0.4) !important; }
[data-theme='light'] .badge-busy { color: #d97706 !important; background: rgba(245, 158, 11, 0.15) !important; border-color: rgba(245, 158, 11, 0.4) !important; }
[data-theme='light'] .badge-ringing { color: #0284c7 !important; background: rgba(6, 182, 212, 0.15) !important; border-color: rgba(6, 182, 212, 0.4) !important; }
[data-theme='light'] .badge-paused { color: #7c3aed !important; background: rgba(139, 92, 246, 0.15) !important; border-color: rgba(139, 92, 246, 0.4) !important; }
[data-theme='light'] .badge-offline { color: #475569 !important; }

/* Invert donut center for true dark/light */
.ql-donut {
    background: radial-gradient(circle at center, var(--panel-dark) 0 52%, transparent 53%), var(--donut-fill) !important;
}
"""

css += "\n" + new_rules

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Badges and donut fixed")
