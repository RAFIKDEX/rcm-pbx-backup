import re

with open("/root/RCM_7021/templates/pbx_operation_log.html", "r") as f:
    content = f.read()

# Replace the old CSS for changes with the new one
old_css = """    .change-list {
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
    }"""

new_css = """    .change-list {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        min-width: 300px;
    }
    .change-item {
        background: rgba(15, 23, 42, 0.4);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 6px;
        padding: 0.5rem 0.6rem;
        transition: border-color 0.2s, background 0.2s;
    }
    .change-item:hover {
        border-color: rgba(255, 255, 255, 0.15);
        background: rgba(15, 23, 42, 0.6);
    }
    .change-setting {
        color: #f8fafc;
        font-weight: 700;
        font-size: 0.75rem;
        margin-bottom: 0.4rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        padding-bottom: 0.3rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .change-setting i { color: #0ea5e9; font-size: 0.7rem; }
    
    .change-diff {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.75rem;
    }
    .diff-row {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.25rem 0.4rem;
        border-radius: 4px;
        word-break: break-all;
        line-height: 1.4;
    }
    .diff-old {
        background: rgba(239, 68, 68, 0.08);
        color: #fca5a5;
        border-left: 2px solid #ef4444;
    }
    .diff-new {
        background: rgba(16, 185, 129, 0.08);
        color: #6ee7b7;
        border-left: 2px solid #10b981;
    }
    .diff-icon {
        opacity: 0.7;
        font-size: 0.65rem;
        margin-top: 0.15rem;
        width: 12px;
        text-align: center;
    }
    .empty-val {
        opacity: 0.5;
        font-style: italic;
    }"""

content = content.replace(old_css, new_css)

# Replace HTML
old_html = """                                <div class="change-item">
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
                                </div>"""

new_html = """                                <div class="change-item">
                                    <div class="change-setting"><i class="fa-solid fa-wrench"></i> {{ change.setting }}</div>
                                    <div class="change-diff">
                                        <div class="diff-row diff-old">
                                            <div class="diff-icon"><i class="fa-solid fa-minus"></i></div>
                                            <div class="{% if change.old is none or change.old == '' %}empty-val{% endif %}">{{ change.old if change.old is not none and change.old != '' else 'empty' }}</div>
                                        </div>
                                        <div class="diff-row diff-new">
                                            <div class="diff-icon"><i class="fa-solid fa-plus"></i></div>
                                            <div class="{% if change.new is none or change.new == '' %}empty-val{% endif %}">{{ change.new if change.new is not none and change.new != '' else 'empty' }}</div>
                                        </div>
                                    </div>
                                </div>"""

content = content.replace(old_html, new_html)

# Replace HTML for the details block
old_html_details = """                                    <div class="change-item">
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
                                    </div>"""

new_html_details = """                                    <div class="change-item">
                                        <div class="change-setting"><i class="fa-solid fa-wrench"></i> {{ change.setting }}</div>
                                        <div class="change-diff">
                                            <div class="diff-row diff-old">
                                                <div class="diff-icon"><i class="fa-solid fa-minus"></i></div>
                                                <div class="{% if change.old is none or change.old == '' %}empty-val{% endif %}">{{ change.old if change.old is not none and change.old != '' else 'empty' }}</div>
                                            </div>
                                            <div class="diff-row diff-new">
                                                <div class="diff-icon"><i class="fa-solid fa-plus"></i></div>
                                                <div class="{% if change.new is none or change.new == '' %}empty-val{% endif %}">{{ change.new if change.new is not none and change.new != '' else 'empty' }}</div>
                                            </div>
                                        </div>
                                    </div>"""

content = content.replace(old_html_details, new_html_details)

with open("/root/RCM_7021/templates/pbx_operation_log.html", "w") as f:
    f.write(content)
