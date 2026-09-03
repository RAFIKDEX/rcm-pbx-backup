import re
with open("/root/RCM_7021/templates/pbx_operation_log.html", "r") as f:
    content = f.read()

# Make it better. Replace the `<style>` block and everything below it.
# We will use CSS variables and make the layout sleek.
# Instead of replacing everything, let's just create the new content.
new_content = """{% extends 'base.html' %}

{% block title %}Operation Log - RCM 7021{% endblock %}

{% block content %}
<style>
    /* Sleek UI Improvements */
    .header-panel {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        margin-bottom: 1.5rem;
    }
    .header-panel h1 {
        margin: 0;
        font-size: 1.8rem;
        font-weight: 800;
        background: linear-gradient(90deg, #fff, #94a3b8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .log-filter-panel {
        margin-bottom: 1.5rem;
        padding: 1.25rem;
        background: rgba(15, 23, 42, 0.4);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        box-shadow: 0 4px 20px -2px rgba(0,0,0,0.2);
    }
    .log-filter-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 1rem;
        padding-bottom: 0.75rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }
    .log-filter-title {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: #f8fafc;
        font-weight: 800;
        font-size: 1.05rem;
    }
    .log-filter-title i { color: #0ea5e9; }
    .log-filter-meta {
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 600;
        background: rgba(255, 255, 255, 0.05);
        padding: 0.25rem 0.6rem;
        border-radius: 20px;
    }
    .log-toolbar {
        display: grid;
        grid-template-columns: minmax(260px, 1.5fr) minmax(170px, 1fr) minmax(150px, 1fr) minmax(110px, 0.5fr) auto auto;
        gap: 1rem;
        align-items: center;
    }
    .filter-control { position: relative; }
    .filter-control label {
        position: absolute;
        top: 0.4rem;
        left: 2.5rem;
        color: #94a3b8;
        font-size: 0.65rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        pointer-events: none;
    }
    .filter-control .control-icon {
        position: absolute;
        left: 1rem;
        top: 50%;
        transform: translateY(-50%);
        color: #0ea5e9;
        font-size: 0.9rem;
        pointer-events: none;
    }
    .filter-control input,
    .filter-control select {
        width: 100%;
        min-height: 52px;
        padding: 1.4rem 1rem 0.4rem 2.5rem;
        border-radius: 10px;
        background: rgba(2, 6, 23, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #f8fafc;
        font-size: 0.9rem;
        outline: none;
        transition: all 0.2s;
        appearance: none;
    }
    .filter-control select {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2394a3b8'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 1rem center;
        background-size: 1rem;
        padding-right: 2.5rem;
    }
    .filter-control input:focus,
    .filter-control select:focus {
        border-color: #0ea5e9;
        box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
        background: rgba(2, 6, 23, 0.8);
    }
    .btn {
        min-height: 52px;
        border-radius: 10px;
        font-weight: 700;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        padding: 0 1.25rem;
        transition: all 0.2s;
        border: none;
        cursor: pointer;
    }
    .btn-primary {
        background: linear-gradient(135deg, #0ea5e9, #0284c7);
        color: white;
        box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
    }
    .btn-primary:hover {
        background: linear-gradient(135deg, #38bdf8, #0ea5e9);
        box-shadow: 0 6px 16px rgba(14, 165, 233, 0.4);
        transform: translateY(-1px);
    }
    .filter-reset {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        min-height: 52px;
        padding: 0 1.25rem;
        border-radius: 10px;
        color: #94a3b8;
        text-decoration: none;
        border: 1px solid rgba(255, 255, 255, 0.1);
        background: rgba(255, 255, 255, 0.03);
        font-weight: 700;
        transition: all 0.2s;
    }
    .filter-reset:hover {
        color: #fff;
        border-color: rgba(255, 255, 255, 0.2);
        background: rgba(255, 255, 255, 0.08);
    }
    .active-filter-chips {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
        margin-top: 1rem;
        padding-top: 1rem;
        border-top: 1px dashed rgba(255, 255, 255, 0.08);
    }
    .active-filter-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.35rem 0.75rem;
        border-radius: 20px;
        background: rgba(14, 165, 233, 0.15);
        border: 1px solid rgba(14, 165, 233, 0.3);
        color: #bae6fd;
        font-size: 0.8rem;
        font-weight: 700;
    }
    
    .panel.table-panel {
        background: rgba(15, 23, 42, 0.4);
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 0;
        overflow: hidden;
    }
    .log-table-wrap {
        overflow-x: auto;
    }
    .log-table {
        width: 100%;
        min-width: 1200px;
        border-collapse: separate;
        border-spacing: 0;
    }
    .log-table th,
    .log-table td {
        padding: 1rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        text-align: left;
        vertical-align: middle;
    }
    .log-table th {
        background: rgba(255, 255, 255, 0.02);
        color: #94a3b8;
        font-size: 0.75rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        white-space: nowrap;
    }
    .log-table tbody tr {
        transition: background-color 0.15s;
    }
    .log-table tbody tr:hover {
        background: rgba(255, 255, 255, 0.02);
    }
    .log-table tbody tr:last-child td { border-bottom: none; }
    
    .log-time {
        white-space: nowrap;
        color: #cbd5e1;
        font-weight: 600;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.85rem;
    }
    .log-time i { color: #64748b; margin-right: 4px; }
    .log-user {
        color: #f8fafc;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .log-user i { color: #0ea5e9; }
    
    .module-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        border-radius: 6px;
        padding: 0.3rem 0.6rem;
        font-size: 0.75rem;
        font-weight: 800;
        white-space: nowrap;
        background: rgba(139, 92, 246, 0.15);
        color: #c4b5fd;
        border: 1px solid rgba(139, 92, 246, 0.3);
    }
    .log-action {
        font-weight: 800;
        color: #f1f5f9;
        font-size: 0.9rem;
    }
    .details-cell {
        max-width: 350px;
        overflow-wrap: break-word;
        color: #94a3b8;
        font-size: 0.85rem;
        line-height: 1.5;
    }
    .ip-cell {
        white-space: nowrap;
        color: #94a3b8;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 0.8rem;
    }
    
    .result-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        border-radius: 20px;
        padding: 0.3rem 0.75rem;
        font-size: 0.75rem;
        font-weight: 800;
        white-space: nowrap;
        text-transform: capitalize;
    }
    .result-success { background: rgba(16, 185, 129, 0.15); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }
    .result-started { background: rgba(56, 189, 248, 0.15); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); }
    .result-failed { background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); }
    .result-rejected { background: rgba(244, 63, 94, 0.15); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.3); }
    .result-other { background: rgba(245, 158, 11, 0.15); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.3); }

    .change-list {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        min-width: 280px;
    }
    .change-item {
        background: rgba(0, 0, 0, 0.2);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 0.6rem;
        transition: border-color 0.2s;
    }
    .change-item:hover {
        border-color: rgba(255, 255, 255, 0.15);
    }
    .change-setting {
        color: #e2e8f0;
        font-weight: 700;
        font-size: 0.8rem;
        margin-bottom: 0.4rem;
        display: flex;
        align-items: center;
        gap: 0.3rem;
    }
    .change-setting i { color: #64748b; font-size: 0.7rem; }
    .change-values {
        display: flex;
        flex-direction: column;
        gap: 0.3rem;
    }
    .change-row {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        font-size: 0.75rem;
    }
    .change-label {
        width: 35px;
        color: #64748b;
        font-weight: 800;
        text-transform: uppercase;
        font-size: 0.65rem;
        padding-top: 0.2rem;
    }
    .value-pill {
        background: rgba(30, 41, 59, 0.8);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 6px;
        padding: 0.2rem 0.5rem;
        color: #f1f5f9;
        font-family: ui-monospace, SFMono-Regular, monospace;
        word-break: break-all;
        flex: 1;
    }
    .value-pill.empty-val {
        color: #64748b;
        font-style: italic;
    }

    /* Details styling for more changes */
    details.more-changes {
        margin-top: 0.5rem;
    }
    details.more-changes summary {
        cursor: pointer;
        color: #38bdf8;
        font-size: 0.8rem;
        font-weight: 700;
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.3rem 0.6rem;
        background: rgba(56, 189, 248, 0.1);
        border-radius: 6px;
        transition: all 0.2s;
        user-select: none;
    }
    details.more-changes summary:hover {
        background: rgba(56, 189, 248, 0.2);
    }
    details.more-changes summary::marker,
    details.more-changes summary::-webkit-details-marker {
        display: none;
    }
    details.more-changes[open] summary {
        margin-bottom: 0.5rem;
    }
    details.more-changes[open] summary .fa-chevron-down {
        transform: rotate(180deg);
    }
    .summary-icon {
        transition: transform 0.2s ease;
    }

    .empty-log {
        padding: 4rem 2rem;
        color: #94a3b8;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
    }
    .empty-log-icon {
        font-size: 3rem;
        color: rgba(14, 165, 233, 0.5);
        background: rgba(14, 165, 233, 0.1);
        width: 80px;
        height: 80px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        margin-bottom: 0.5rem;
    }
    .empty-log h3 { color: #f8fafc; margin: 0; font-size: 1.25rem; font-weight: 800; }

    @media (max-width: 1024px) {
        .log-toolbar { grid-template-columns: 1fr 1fr; }
        .filter-actions { justify-content: stretch; }
    }
    @media (max-width: 640px) {
        .log-toolbar { grid-template-columns: 1fr; }
        .log-filter-head { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
        .header-panel { flex-direction: column; align-items: flex-start; gap: 1rem; }
    }
</style>

<div class="header-panel">
    <div>
        <h1>Operation Log</h1>
        <div style="font-size: 0.9rem; color: #94a3b8; margin-top: 0.4rem; display: flex; align-items: center; gap: 0.5rem;">
            <i class="fa-solid fa-shield-halved" style="color: #0ea5e9;"></i>
            Complete audit trail with full data integrity
        </div>
    </div>
    <a href="{{ url_for('pbx_settings') }}" class="btn btn-secondary" style="text-decoration: none; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.1); color: white;">
        <i class="fa-solid fa-sliders"></i> Global Settings
    </a>
</div>

<div class="log-filter-panel">
    <div class="log-filter-head">
        <div class="log-filter-title"><i class="fa-solid fa-filter"></i> Advanced Filters</div>
        <div class="log-filter-meta">
            <i class="fa-solid fa-database"></i> Showing {{ logs|length }} of latest {{ limit }}
        </div>
    </div>
    <form method="get" class="log-toolbar">
        <div class="filter-control">
            <i class="fa-solid fa-magnifying-glass control-icon"></i>
            <label>Smart Search</label>
            <input type="text" name="search" value="{{ filters.search }}" placeholder="Search user, action, detail, IP, changes...">
        </div>
        <div class="filter-control">
            <i class="fa-solid fa-layer-group control-icon"></i>
            <label>Module</label>
            <select name="module">
                <option value="">All Modules</option>
                {% for module in modules %}
                <option value="{{ module }}" {% if filters.module == module %}selected{% endif %}>{{ module }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="filter-control">
            <i class="fa-solid fa-circle-check control-icon"></i>
            <label>Result</label>
            <select name="result">
                <option value="">All Results</option>
                {% for result in facets.results %}
                <option value="{{ result }}" {% if filters.result == result %}selected{% endif %}>{{ result }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="filter-control">
            <i class="fa-solid fa-list-ol control-icon"></i>
            <label>Limit</label>
            <select name="limit">
                {% for item in [100, 200, 500, 1000] %}
                <option value="{{ item }}" {% if limit == item %}selected{% endif %}>{{ item }}</option>
                {% endfor %}
            </select>
        </div>
        <button class="btn btn-primary" type="submit"><i class="fa-solid fa-check"></i> Apply</button>
        <a href="{{ url_for('pbx_operation_log') }}" class="filter-reset" title="Clear all filters">
            <i class="fa-solid fa-rotate-left"></i> Reset
        </a>
    </form>
    {% if filters.search or filters.module or filters.result %}
    <div class="active-filter-chips">
        {% if filters.search %}<span class="active-filter-chip"><i class="fa-solid fa-magnifying-glass"></i> "{{ filters.search }}"</span>{% endif %}
        {% if filters.module %}<span class="active-filter-chip"><i class="fa-solid fa-layer-group"></i> {{ filters.module }}</span>{% endif %}
        {% if filters.result %}<span class="active-filter-chip"><i class="fa-solid fa-circle-check"></i> {{ filters.result }}</span>{% endif %}
    </div>
    {% endif %}
</div>

<div class="panel table-panel">
    {% if logs %}
    <div class="log-table-wrap">
        <table class="log-table">
            <thead>
                <tr>
                    <th style="width: 140px;">Timestamp</th>
                    <th style="width: 130px;">User</th>
                    <th style="width: 130px;">Module</th>
                    <th style="width: 140px;">Action</th>
                    <th style="width: 220px;">Details</th>
                    <th style="width: 120px;">IP Address</th>
                    <th style="width: 120px;">Result</th>
                    <th>Data Changes</th>
                </tr>
            </thead>
            <tbody>
                {% for log in logs %}
                {% set result = (log.result or log.status or 'Success') %}
                {% set result_key = result|lower %}
                <tr>
                    <td class="log-time">
                        <i class="fa-regular fa-clock"></i> {{ log.timestamp or '-' }}
                    </td>
                    <td class="log-user">
                        <i class="fa-solid fa-user-astronaut"></i> {{ log.username or log.user or '-' }}
                    </td>
                    <td>
                        <span class="module-pill">
                            <i class="fa-solid fa-cube"></i> {{ log.module or 'PBX Settings' }}
                        </span>
                    </td>
                    <td class="log-action">{{ log.action or '-' }}</td>
                    <td class="details-cell">{{ log.details or log.message or '-' }}</td>
                    <td class="ip-cell"><i class="fa-solid fa-network-wired" style="color: #64748b; margin-right:4px;"></i>{{ log.ip_address or log.ip or '-' }}</td>
                    <td>
                        <span class="result-pill {% if result_key in ['success'] %}result-success{% elif result_key in ['started'] %}result-started{% elif result_key in ['failed', 'failure', 'error'] %}result-failed{% elif result_key in ['rejected'] %}result-rejected{% else %}result-other{% endif %}">
                            {% if result_key in ['success'] %}<i class="fa-solid fa-circle-check"></i>
                            {% elif result_key in ['started'] %}<i class="fa-solid fa-play"></i>
                            {% elif result_key in ['failed', 'failure', 'error'] %}<i class="fa-solid fa-circle-xmark"></i>
                            {% elif result_key in ['rejected'] %}<i class="fa-solid fa-ban"></i>
                            {% else %}<i class="fa-solid fa-circle-info"></i>{% endif %}
                            {{ result }}
                        </span>
                    </td>
                    <td>
                        {% if log.changes %}
                            <div class="change-list">
                                {% for change in log.changes[:3] %}
                                <div class="change-item">
                                    <div class="change-setting"><i class="fa-solid fa-pen-to-square"></i> {{ change.setting }}</div>
                                    <div class="change-values">
                                        <div class="change-row">
                                            <span class="change-label">Old</span>
                                            <span class="value-pill {% if change.old is none or change.old == '' %}empty-val{% endif %}">{{ change.old if change.old is not none and change.old != '' else 'empty' }}</span>
                                        </div>
                                        <div class="change-row">
                                            <span class="change-label">New</span>
                                            <span class="value-pill {% if change.new is none or change.new == '' %}empty-val{% endif %}">{{ change.new if change.new is not none and change.new != '' else 'empty' }}</span>
                                        </div>
                                    </div>
                                </div>
                                {% endfor %}
                            </div>
                            
                            {% if log.changes|length > 3 %}
                            <details class="more-changes">
                                <summary>
                                    <i class="fa-solid fa-layer-group"></i> 
                                    Show {{ log.changes|length - 3 }} more changes 
                                    <i class="fa-solid fa-chevron-down summary-icon"></i>
                                </summary>
                                <div class="change-list" style="margin-top: 0.5rem;">
                                    {% for change in log.changes[3:] %}
                                    <div class="change-item">
                                        <div class="change-setting"><i class="fa-solid fa-pen-to-square"></i> {{ change.setting }}</div>
                                        <div class="change-values">
                                            <div class="change-row">
                                                <span class="change-label">Old</span>
                                                <span class="value-pill {% if change.old is none or change.old == '' %}empty-val{% endif %}">{{ change.old if change.old is not none and change.old != '' else 'empty' }}</span>
                                            </div>
                                            <div class="change-row">
                                                <span class="change-label">New</span>
                                                <span class="value-pill {% if change.new is none or change.new == '' %}empty-val{% endif %}">{{ change.new if change.new is not none and change.new != '' else 'empty' }}</span>
                                            </div>
                                        </div>
                                    </div>
                                    {% endfor %}
                                </div>
                            </details>
                            {% endif %}
                        {% else %}
                        <span style="color: #64748b; font-style: italic;">No changes recorded</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <div class="empty-log">
        <div class="empty-log-icon">
            <i class="fa-solid fa-clipboard-list"></i>
        </div>
        <div>
            <h3>No Operations Found</h3>
            <p style="margin-top: 0.5rem;">Try adjusting your filters or search terms.</p>
        </div>
        <a href="{{ url_for('pbx_operation_log') }}" class="btn btn-secondary" style="border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #e2e8f0;">
            <i class="fa-solid fa-rotate-left"></i> Reset Filters
        </a>
    </div>
    {% endif %}
</div>

{% endblock %}
"""

with open("/root/RCM_7021/templates/pbx_operation_log.html", "w") as f:
    f.write(new_content)

print("Rewrite successful!")
