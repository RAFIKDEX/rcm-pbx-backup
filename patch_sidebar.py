with open('/root/RCM_7021/templates/base.html', 'r') as f:
    content = f.read()

target = """                            {% if can_access_module('global_settings') %}
                            <li>
                                <a href="javascript:void(0)" onclick="showNotification('System auto-cleaner script configuration is scheduled to be integrated.', 'info')" data-tooltip="System Cleaner">
                                    <i class="fa-solid fa-broom" style="color: #a855f7;"></i> <span class="menu-text">System Cleaner</span> <span class="sidebar-badge coming-soon">Soon</span>
                                </a>
                            </li>
                            {% endif %}"""

replacement = """                            {% if can_access_module('global_settings') %}
                            <li class="{% if request.blueprint == 'cleanup_bp' %}active{% endif %}">
                                <a href="/cleanup/" data-tooltip="System Cleaner">
                                    <i class="fa-solid fa-broom" style="color: #a855f7;"></i> <span class="menu-text">System Cleaner</span>
                                </a>
                            </li>
                            {% endif %}"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/templates/base.html', 'w') as f:
        f.write(content)
    print("Patched successfully!")
else:
    print("Target not found!")
