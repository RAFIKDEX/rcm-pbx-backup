import re

with open("stars.css", "r") as f:
    stars = f.read()

stars = stars.replace("--star-color: rgba(15, 23, 42, 0.25);", "--star-color: rgba(15, 23, 42, 0.45);")
stars = stars.replace("--star-color: rgba(15, 23, 42, 0.2);", "--star-color: rgba(15, 23, 42, 0.45);")

stars = re.sub(r'(#stars\s*\{\s*width:\s*)[0-9]+px(\s*;\s*height:\s*)[0-9]+px', r'\g<1>2px\g<2>2px', stars)
stars = re.sub(r'(#stars2\s*\{\s*width:\s*)[0-9]+px(\s*;\s*height:\s*)[0-9]+px', r'\g<1>3px\g<2>3px', stars)
stars = re.sub(r'(#stars3\s*\{\s*width:\s*)[0-9]+px(\s*;\s*height:\s*)[0-9]+px', r'\g<1>4px\g<2>4px', stars)

stars = re.sub(r'(#stars:after\s*\{.*?width:\s*)[0-9]+px(\s*;\s*height:\s*)[0-9]+px', r'\g<1>2px\g<2>2px', stars, flags=re.DOTALL)
stars = re.sub(r'(#stars2:after\s*\{.*?width:\s*)[0-9]+px(\s*;\s*height:\s*)[0-9]+px', r'\g<1>3px\g<2>3px', stars, flags=re.DOTALL)
stars = re.sub(r'(#stars3:after\s*\{.*?width:\s*)[0-9]+px(\s*;\s*height:\s*)[0-9]+px', r'\g<1>4px\g<2>4px', stars, flags=re.DOTALL)

stars = stars.replace("animation: animStar 50s linear infinite;", "animation: animStar 120s linear infinite;")
stars = stars.replace("animation: animStar 100s linear infinite;", "animation: animStar 80s linear infinite;")
stars = stars.replace("animation: animStar 150s linear infinite;", "animation: animStar 45s linear infinite;")

glass_classes = [
    ".card", ".panel", ".modal-content", ".toast",
    ".action-card", ".cdr-stat-card", ".contact-dialog-card", ".credentials-card",
    ".dex-modal-card", ".dex-progress-card", ".firewall-card", ".firewall-summary-card",
    ".ivr-check-card", ".ivr-header-card", ".login-card", ".pbx-header-card",
    ".pm-modal-card", ".preview-card", ".q-check-card", ".q-header-card",
    ".sip-status-card", ".stat-card", ".storage-card", ".studio-card",
    ".survey-card", ".um-modal-card", ".wb-card-sub",
    ".cdr-chart-panel", ".cdr-table-panel", ".content-panel", ".sip-panel"
]
all_selectors = ", \n".join(glass_classes) + ", \n" + ", \n".join([f"[data-theme='light'] {c}" for c in glass_classes]) + ", \n" + ", \n".join([f"[data-theme='dark'] {c}" for c in glass_classes])

theme_css = f"""
/* ====================================================
   GLASSMORPHISM THEME (Dark & Light)
   ==================================================== */

:root, [data-theme="dark"] {{
    --glass-bg: rgba(11, 15, 25, 0.55);
    --glass-border: rgba(255, 255, 255, 0.12);
    --glass-blur: blur(20px);
    --glass-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    --glass-highlight: inset 0 1px 0 0 rgba(255, 255, 255, 0.15);
    
    --theme-bg-color: #0b0f19;
    --star-color: #ffffff;
    --sidebar-bg: rgba(6, 8, 15, 0.65);
}}

[data-theme="light"] {{
    --glass-bg: rgba(255, 255, 255, 0.75);
    --glass-border: rgba(255, 255, 255, 0.6);
    --glass-blur: blur(24px);
    --glass-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.1);
    --glass-highlight: inset 0 1px 0 0 rgba(255, 255, 255, 0.7);
    
    --theme-bg-color: #e2e8f0;
    --star-color: rgba(15, 23, 42, 0.45);
    --sidebar-bg: rgba(255, 255, 255, 0.6);
    
    /* Override core variables for light mode */
    --bg-dark: transparent;
    --panel-dark: transparent;
    --border-color: rgba(15, 23, 42, 0.1);
    --border-color-hover: rgba(15, 23, 42, 0.2);
    --text-main: #0f172a;
    --text-muted: #475569;
    --text-dark: #64748b;
}}

/* ====================================================
   SPECIFICITY OVERRIDES (Fixing Opaque Backgrounds)
   ==================================================== */
body, [data-theme="light"] body, [data-theme="dark"] body {{
    background: transparent !important;
    background-color: transparent !important;
    color: var(--text-main);
    transition: color 0.5s ease;
}}

.app-container, [data-theme="light"] .app-container, [data-theme="dark"] .app-container,
.main-content, [data-theme="light"] .main-content, [data-theme="dark"] .main-content {{
    background: transparent !important;
    background-color: transparent !important;
}}

/* Global Background Container */
.uiverse-bg-container {{
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: -999;
    overflow: hidden;
    background: radial-gradient(ellipse at bottom, var(--theme-bg-color) 0%, #000000 100%);
    transition: background 0.5s ease;
}}

[data-theme="light"] .uiverse-bg-container {{
    background: radial-gradient(ellipse at bottom, #f8fafc 0%, #cbd5e1 100%);
}}

/* ====================================================
   APPLYING GLASSMORPHISM TO ALL CARDS AND PANELS
   ==================================================== */

/* Sidebar */
.sidebar, [data-theme="light"] .sidebar, [data-theme="dark"] .sidebar {{
    background: var(--sidebar-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
    border-right: 1px solid var(--glass-border) !important;
}}

/* Top Bar / Header */
.top-bar, .header-panel, .cdr-header {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}}

/* All Panels and Cards generated dynamically */
{all_selectors} {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur) !important;
    -webkit-backdrop-filter: var(--glass-blur) !important;
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow) !important;
    background-image: var(--glass-highlight) !important;
    border-radius: 12px !important;
}}

/* Modals background overlay */
.modal {{
    background-color: rgba(11, 15, 25, 0.4) !important;
    backdrop-filter: blur(8px);
}}

/* Form Controls */
.form-control, .switch-group {{
    background: rgba(0, 0, 0, 0.1) !important;
    border: 1px solid var(--glass-border) !important;
    color: var(--text-main) !important;
    backdrop-filter: blur(4px);
}}

[data-theme="light"] .form-control, [data-theme="light"] .switch-group {{
    background: rgba(255, 255, 255, 0.4) !important;
}}

.form-control:focus {{
    background: rgba(0, 0, 0, 0.2) !important;
    border-color: var(--primary) !important;
}}

/* Table Headers */
.fm-table th, .table th, .cdr-table th {{
    background: rgba(0, 0, 0, 0.15) !important;
    backdrop-filter: blur(4px) !important;
    border-bottom: 1px solid var(--glass-border) !important;
}}

[data-theme="light"] .fm-table th, [data-theme="light"] .table th, [data-theme="light"] .cdr-table th {{
    background: rgba(255, 255, 255, 0.3) !important;
}}

/* Table Background Fix */
.fm-table, .table, .cdr-table {{
    background: transparent !important;
}}

/* Table Rows */
.fm-table tr, .table tr, .cdr-table tr {{
    background: transparent !important;
}}

.fm-table tr:hover, .table tr:hover, .cdr-table tr:not(.cdr-details-row):hover {{
    background: rgba(14,165,233,0.1) !important;
}}

[data-theme="light"] .fm-table tr:hover, [data-theme="light"] .table tr:hover, [data-theme="light"] .cdr-table tr:not(.cdr-details-row):hover {{
    background: rgba(14,165,233,0.05) !important;
}}


/* ====================================================
   ANIMATIONS (Page Load, Hover, etc.)
   ==================================================== */

/* Page Load Fade-Up */
.main-content {{
    animation: pageLoadFadeUp 0.6s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
}}

@keyframes pageLoadFadeUp {{
    from {{ opacity: 0; transform: translateY(15px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

/* Card Hover Elevation */
{', '.join([c + ':hover' for c in glass_classes])} {{
    transform: translateY(-4px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.5) !important;
    border-color: var(--primary) !important;
}}

{', '.join([f"[data-theme='light'] {c}:hover" for c in glass_classes])} {{
    box-shadow: 0 12px 40px rgba(31, 38, 135, 0.2) !important;
}}

/* Modal Animations */
.modal-content {{
    animation: modalScaleFade 0.4s cubic-bezier(0.2, 0.8, 0.2, 1) forwards !important;
}}

@keyframes modalScaleFade {{
    from {{ opacity: 0; transform: scale(0.95) translateY(10px); }}
    to {{ opacity: 1; transform: scale(1) translateY(0); }}
}}

/* Theme Toggle Button Animation */
#themeIcon {{
    transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1), color 0.4s ease;
}}
[data-theme="light"] #themeIcon {{
    transform: rotate(360deg);
}}

/* ====================================================
   UIVERSE STARS CSS
   ==================================================== */
"""

with open("static/css/glass_theme.css", "w") as f:
    f.write(theme_css + "\n" + stars)

print("Glass theme cleanly rebuilt for all pages")
