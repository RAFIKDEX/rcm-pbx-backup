import re
with open("/root/RCM_7021/templates/pbx_operation_log.html", "r") as f:
    content = f.read()

# We need to change "Showing {{ logs|length }} of latest {{ limit }}" 
# to "Showing {{ logs|length }} of {{ total_count }} total"
content = content.replace(
    '<div class="log-filter-meta">\n            <i class="fa-solid fa-database"></i> Showing {{ logs|length }} of latest {{ limit }}\n        </div>',
    '<div class="log-filter-meta">\n            <i class="fa-solid fa-database"></i> Showing page {{ page }} ({{ logs|length }} items) of {{ total_count }} total operations\n        </div>'
)

# And add the pagination block after the </table> but inside the log-table-wrap or just after it inside the panel.
pagination_block = """
        </table>
    </div>
    
    <!-- Pagination Controls -->
    {% if total_pages > 1 %}
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.25rem; border-top: 1px solid rgba(255, 255, 255, 0.08); background: rgba(0,0,0,0.2);">
        <div style="color: #94a3b8; font-size: 0.85rem;">
            Showing <b>{{ (page - 1) * limit + 1 }}</b> to <b>{{ (page - 1) * limit + logs|length }}</b> of <b>{{ total_count }}</b> operations
        </div>
        <div style="display: flex; gap: 0.25rem;">
            <!-- Prev Button -->
            {% if page > 1 %}
            <button class="btn btn-secondary" style="min-height: 36px; padding: 0 0.75rem; border-radius: 6px; background: rgba(255,255,255,0.05); color: #e2e8f0; border: 1px solid rgba(255,255,255,0.1);" onclick="goToPage({{ page - 1 }})">
                <i class="fa-solid fa-chevron-left"></i>
            </button>
            {% else %}
            <button class="btn btn-secondary" style="min-height: 36px; padding: 0 0.75rem; border-radius: 6px; background: rgba(255,255,255,0.02); color: #475569; border: 1px solid rgba(255,255,255,0.05); cursor: not-allowed;" disabled>
                <i class="fa-solid fa-chevron-left"></i>
            </button>
            {% endif %}
            
            <!-- Page Indicator -->
            <div style="display: flex; align-items: center; justify-content: center; min-width: 40px; color: #f8fafc; font-weight: 700; background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.3); border-radius: 6px; padding: 0 0.5rem; font-size: 0.9rem;">
                {{ page }}
            </div>
            
            <!-- Next Button -->
            {% if page < total_pages %}
            <button class="btn btn-secondary" style="min-height: 36px; padding: 0 0.75rem; border-radius: 6px; background: rgba(255,255,255,0.05); color: #e2e8f0; border: 1px solid rgba(255,255,255,0.1);" onclick="goToPage({{ page + 1 }})">
                <i class="fa-solid fa-chevron-right"></i>
            </button>
            {% else %}
            <button class="btn btn-secondary" style="min-height: 36px; padding: 0 0.75rem; border-radius: 6px; background: rgba(255,255,255,0.02); color: #475569; border: 1px solid rgba(255,255,255,0.05); cursor: not-allowed;" disabled>
                <i class="fa-solid fa-chevron-right"></i>
            </button>
            {% endif %}
        </div>
    </div>
    
    <script>
    function goToPage(pageNum) {
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.set('page', pageNum);
        window.location.search = urlParams.toString();
    }
    </script>
    {% endif %}
"""

content = content.replace('        </table>\n    </div>', pagination_block)

with open("/root/RCM_7021/templates/pbx_operation_log.html", "w") as f:
    f.write(content)
