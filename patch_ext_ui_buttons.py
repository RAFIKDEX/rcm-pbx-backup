# Patch providers UI
with open('/root/RCM_7021/templates/ext_storage_providers.html', 'r') as f:
    prov_ui = f.read()

target_prov = """<form method="POST" action="/external-storage/providers/delete/{{ p.id }}" style="display:inline;" onsubmit="return confirm('Are you sure?');">
                    <button type="submit" style="background: #ef4444; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer;"><i class="fa-solid fa-trash"></i> Delete</button>
                </form>"""

replacement_prov = """<form method="POST" action="/external-storage/providers/test/{{ p.id }}" style="display:inline;">
                    <button type="submit" style="background: #10b981; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; margin-right: 5px;"><i class="fa-solid fa-vial"></i> Test</button>
                </form>
                <form method="POST" action="/external-storage/providers/delete/{{ p.id }}" style="display:inline;" onsubmit="return confirm('Are you sure?');">
                    <button type="submit" style="background: #ef4444; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer;"><i class="fa-solid fa-trash"></i> Delete</button>
                </form>"""

if target_prov in prov_ui:
    prov_ui = prov_ui.replace(target_prov, replacement_prov)
    with open('/root/RCM_7021/templates/ext_storage_providers.html', 'w') as f:
        f.write(prov_ui)

# Patch policies UI
with open('/root/RCM_7021/templates/ext_storage_policies.html', 'r') as f:
    pol_ui = f.read()
    
target_pol = """<h3 style="color: white; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px;">Active Policies</h3>"""

replacement_pol = """<div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-bottom: 15px;">
    <h3 style="color: white; margin: 0;">Active Policies</h3>
    <form method="POST" action="/external-storage/policies/run_now">
        <button type="submit" style="background: #f59e0b; color: white; padding: 8px 15px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;"><i class="fa-solid fa-bolt"></i> Run Engine Now</button>
    </form>
</div>"""

if target_pol in pol_ui:
    pol_ui = pol_ui.replace(target_pol, replacement_pol)
    with open('/root/RCM_7021/templates/ext_storage_policies.html', 'w') as f:
        f.write(pol_ui)
