with open('/root/RCM_7021/templates/base.html', 'r') as f:
    content = f.read()

target = """                            {% if can_access_module('global_settings') %}
                            <li class="{% if request.blueprint == 'cleanup_bp' %}active{% endif %}">
                                <a href="/cleanup/" data-tooltip="System Cleaner">
                                    <i class="fa-solid fa-broom" style="color: #a855f7;"></i> <span class="menu-text">System Cleaner</span>
                                </a>
                            </li>
                            {% endif %}"""

replacement = """                            {% if can_access_module('global_settings') %}
                            <li class="{% if request.blueprint == 'cleanup_bp' %}active{% endif %}">
                                <a href="/cleanup/" data-tooltip="System Cleaner">
                                    <i class="fa-solid fa-broom" style="color: #a855f7;"></i> <span class="menu-text">System Cleaner</span>
                                </a>
                            </li>
                            <li class="{% if request.blueprint == 'ext_storage_bp' %}active{% endif %}">
                                <a href="/external-storage/" data-tooltip="External Storage">
                                    <i class="fa-solid fa-hard-drive" style="color: #3b82f6;"></i> <span class="menu-text">External Storage</span>
                                </a>
                            </li>
                            {% endif %}"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/templates/base.html', 'w') as f:
        f.write(content)
    print("Sidebar patched successfully")
else:
    print("Target not found")
