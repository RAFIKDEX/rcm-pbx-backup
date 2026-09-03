import re

with open('templates/queue_stats.html', 'r') as f:
    content = f.read()

new_styles = """<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    :root {
        --bg-main: #000000;
        --bg-panel: #09090b;
        --border-color: #27272a;
        --border-light: #3f3f46;
        --text-main: #ededed;
        --text-muted: #a1a1aa;
        --panel-radius: 12px;
    }

    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        background-color: var(--bg-main) !important;
        color: var(--text-main) !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }

    .container, .content, .main-content {
        background-color: transparent !important;
    }

    /* Cards & Panels */
    .panel, .kpi-card, .realtime-bar, .tab-content > div > .panel {
        background: var(--bg-panel) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: var(--panel-radius) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.8), inset 0 1px 0 rgba(255,255,255,0.02) !important;
        transition: all 0.2s ease !important;
    }
    
    .panel:hover, .kpi-card:hover {
        border-color: var(--border-light) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.8), inset 0 1px 0 rgba(255,255,255,0.04) !important;
    }

    /* Typography */
    * { font-family: 'Inter', sans-serif !important; }
    h1, h2, h3, h4, .realtime-num, [id^="kpi-"] {
        color: #ffffff !important;
        font-weight: 600 !important;
        letter-spacing: -0.03em !important;
    }
    
    /* Dynamic glow on realtime numbers */
    #realtime-waiting { color: #f59e0b !important; text-shadow: 0 0 16px rgba(245, 158, 11, 0.4) !important; }
    #realtime-talking { color: #ef4444 !important; text-shadow: 0 0 16px rgba(239, 68, 68, 0.4) !important; }

    /* Override ugly inline borders */
    [style*="border-left: 4px solid"] {
        border-left: 1px solid var(--border-color) !important;
    }

    /* Buttons */
    .btn {
        border-radius: 8px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        letter-spacing: 0 !important;
        border: 1px solid transparent !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.5) !important;
    }
    .btn-secondary {
        background: #18181b !important;
        color: #ededed !important;
        border-color: #27272a !important;
    }
    .btn-secondary:hover {
        background: #27272a !important;
        border-color: #3f3f46 !important;
    }
    .btn-info {
        background: #ffffff !important;
        color: #000000 !important;
        font-weight: 600 !important;
    }
    .btn-info:hover {
        background: #f4f4f5 !important;
    }

    /* Table */
    .table-responsive { border-radius: var(--panel-radius); border: 1px solid var(--border-color); overflow: hidden; background: var(--bg-panel); }
    .table { margin: 0 !important; border: none !important; }
    .table th {
        background: #09090b !important;
        color: var(--text-muted) !important;
        font-weight: 500 !important;
        text-transform: capitalize !important;
        font-size: 0.75rem !important;
        letter-spacing: 0 !important;
        border-bottom: 1px solid var(--border-color) !important;
        border-top: none !important;
        padding: 0.85rem 1.25rem !important;
    }
    .table td {
        background: #09090b !important;
        border-bottom: 1px solid rgba(255,255,255,0.03) !important;
        border-top: none !important;
        color: var(--text-main) !important;
        padding: 0.85rem 1.25rem !important;
        font-size: 0.85rem !important;
        vertical-align: middle !important;
    }
    .table tbody tr:last-child td { border-bottom: none !important; }
    .table tbody tr:hover td { background: #121214 !important; }
    
    /* Badges */
    .badge {
        font-weight: 500 !important;
        padding: 0.25rem 0.6rem !important;
        border-radius: 9999px !important;
        font-size: 0.7rem !important;
    }

    /* Realtime indicator */
    .realtime-indicator {
        display: flex; align-items: center; gap: 0.85rem;
    }
    .realtime-indicator i {
        background: #18181b !important;
        padding: 0.65rem !important;
        border-radius: 8px !important;
        border: 1px solid #27272a !important;
        font-size: 1rem !important;
    }
    
    /* Filters */
    .quick-range-btn {
        background: transparent !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        color: var(--text-muted) !important;
        transition: all 0.2s ease !important;
    }
    .quick-range-btn:hover {
        border-color: #3f3f46 !important;
        background: #18181b !important;
        color: #fff !important;
    }
    .filter-chip, .analytics-status {
        background: #18181b !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        font-weight: 500 !important;
        color: #e4e4e7 !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.3) !important;
    }
    .form-control, select.form-control {
        background: #18181b !important;
        border: 1px solid #27272a !important;
        color: #ededed !important;
        border-radius: 8px !important;
    }
    .form-control:focus {
        border-color: #ffffff !important;
        box-shadow: 0 0 0 1px #ffffff !important;
    }
    
    /* Micro-animations */
    @keyframes pulse {
        0% { transform: scale(1); opacity: 0.6; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
        50% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 0 4px rgba(16, 185, 129, 0); }
        100% { transform: scale(1); opacity: 0.6; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    .pulse-dot {
        width: 8px; height: 8px; background-color: #10b981; border-radius: 50%;
        animation: pulse 2s infinite; display: inline-block;
    }
    
    /* Tab nav */
    .sub-nav-bar {
        border-bottom: 1px solid var(--border-color) !important;
        padding-bottom: 0.5rem !important;
        gap: 1rem !important;
    }
    .tab-btn {
        background: transparent !important;
        border: none !important;
        color: var(--text-muted) !important;
        border-bottom: 2px solid transparent !important;
        border-radius: 0 !important;
        padding: 0.5rem 0.25rem !important;
        transition: all 0.2s ease !important;
    }
    .tab-btn:hover { color: var(--text-main) !important; }
    .tab-btn.active {
        color: #ffffff !important;
        border-bottom: 2px solid #ffffff !important;
    }
    
    /* Form label cleanup */
    label { font-weight: 500 !important; letter-spacing: 0 !important; }
</style>"""

new_content = re.sub(r'<style>.*?</style>', new_styles, content, flags=re.DOTALL)

with open('templates/queue_stats.html', 'w') as f:
    f.write(new_content)

print("CSS Upgraded to Premium Modern Aesthetic.")
