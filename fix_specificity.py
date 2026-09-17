with open("static/css/glass_theme.css", "r") as f:
    content = f.read()

fixes = """
/* ====================================================
   SPECIFICITY OVERRIDES (Fixing Opaque Backgrounds)
   ==================================================== */
body, 
[data-theme="light"] body, 
[data-theme="dark"] body {
    background: transparent !important;
    background-color: transparent !important;
}

.app-container, 
[data-theme="light"] .app-container, 
[data-theme="dark"] .app-container {
    background: transparent !important;
    background-color: transparent !important;
}

.main-content, 
[data-theme="light"] .main-content, 
[data-theme="dark"] .main-content {
    background: transparent !important;
    background-color: transparent !important;
}

/* Ensure glassmorphism cards override light mode white backgrounds */
.card, 
[data-theme="light"] .card, 
[data-theme="dark"] .card {
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
}

.sidebar, 
[data-theme="light"] .sidebar, 
[data-theme="dark"] .sidebar {
    background: var(--sidebar-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
}
"""

with open("static/css/glass_theme.css", "w") as f:
    # Insert fixes right after the APPLYING GLASSMORPHISM block
    f.write(content + "\n" + fixes)
print("Specificity fixed")
