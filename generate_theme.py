with open("stars.css", "r") as f:
    stars = f.read()

theme_css = f"""
/* ====================================================
   GLASSMORPHISM THEME (Dark & Light)
   ==================================================== */

:root, [data-theme="dark"] {{
    --glass-bg: rgba(21, 29, 48, 0.45);
    --glass-border: rgba(255, 255, 255, 0.08);
    --glass-blur: blur(12px);
    --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    --glass-highlight: inset 0 1px 0 0 rgba(255, 255, 255, 0.15);
    
    --theme-bg-color: #0b0f19;
    --star-color: #ffffff;
    --sidebar-bg: rgba(12, 15, 29, 0.6);
}}

[data-theme="light"] {{
    --glass-bg: rgba(255, 255, 255, 0.55);
    --glass-border: rgba(255, 255, 255, 0.4);
    --glass-blur: blur(16px);
    --glass-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.1);
    --glass-highlight: inset 0 1px 0 0 rgba(255, 255, 255, 0.7);
    
    --theme-bg-color: #e2e8f0;
    --star-color: rgba(15, 23, 42, 0.25);
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

/* Ensure text remains legible */
body {{
    background-color: transparent !important; 
    color: var(--text-main);
    transition: color 0.5s ease;
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
   APPLYING GLASSMORPHISM
   ==================================================== */

/* Sidebar */
.sidebar {{
    background: var(--sidebar-bg) !important;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-right: 1px solid var(--glass-border) !important;
}}

/* Top Bar / Header */
.top-bar, .header-panel {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}}

/* General Cards & Panels */
.card, .panel, .modal-content, .toast {{
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
    background-image: var(--glass-highlight);
    border-radius: 12px !important; /* Unified radius */
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
.fm-table th, .table th {{
    background: rgba(0, 0, 0, 0.15);
    backdrop-filter: blur(4px);
    border-bottom: 1px solid var(--glass-border) !important;
}}

[data-theme="light"] .fm-table th, [data-theme="light"] .table th {{
    background: rgba(255, 255, 255, 0.3);
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
.card:hover {{
    transform: translateY(-4px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
    border-color: var(--primary) !important;
}}

[data-theme="light"] .card:hover {{
    box-shadow: 0 12px 40px rgba(31, 38, 135, 0.2);
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
.theme-toggle-icon {{
    transition: transform 0.5s cubic-bezier(0.4, 0, 0.2, 1), color 0.3s ease;
}}
.theme-toggle-icon.rotating {{
    transform: rotate(360deg) scale(1.1);
}}

/* ====================================================
   UIVERSE STARS CSS
   ==================================================== */
"""

with open("static/css/glass_theme.css", "w") as f:
    f.write(theme_css + "\n" + stars)

print("Generated glass_theme.css")
