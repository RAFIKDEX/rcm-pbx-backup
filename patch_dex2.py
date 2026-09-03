import re

with open("/root/RCM_7021/dex/routes.py", "r") as f:
    content = f.read()

target = """                device_id = repo.upsert_device({"normalized_mac": mac, "ip_address": ip, "vendor": vendor_name, "detected_model": model_name, "model_id": model_id, "mac_source": "Manual", "provision_status": status}, source="Manual")
                _audit("Device Added", f"MAC={mac}; Model={model_name}; InventoryOnly={inventory_only}")"""

replacement = """                device_id = repo.upsert_device({"normalized_mac": mac, "ip_address": ip, "vendor": vendor_name, "detected_model": model_name, "model_id": model_id, "mac_source": "Manual", "provision_status": status}, source="Manual")
                changes = [
                    {"setting": "MAC Address", "old": "", "new": mac},
                    {"setting": "Model", "old": "", "new": model_name},
                    {"setting": "Vendor", "old": "", "new": vendor_name},
                    {"setting": "IP Address", "old": "", "new": ip or ""}
                ]
                _audit("Device Added", f"MAC={mac}; Model={model_name}; InventoryOnly={inventory_only}", changes=changes)"""

if target in content:
    content = content.replace(target, replacement)
    with open("/root/RCM_7021/dex/routes.py", "w") as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Target not found")
