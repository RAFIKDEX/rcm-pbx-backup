import re

with open("/root/RCM_7021/dex/routes.py", "r") as f:
    content = f.read()

target = """                if request.form.get("save_mode", "notify") == "notify":
                    submit_notify(current_app._get_current_object(), device_id, session.get("username", ""))
                    flash("Assignments saved. Provisioning was queued; you can continue working in DEXPhone and follow the result in Operation history.", "success")
                else:
                    flash("Assignments saved without sending a provisioning request.", "success")
                _audit("Device Edited", f"Device ID={device_id}")"""

replacement = """                changes = []
                old_accounts = {a.get("account_index"): a for a in device.get("accounts", [])}
                for new_acc in accounts:
                    idx = new_acc["account_index"]
                    old_acc = old_accounts.get(idx, {})
                    old_ext = str(old_acc.get("extension") or "")
                    new_ext = str(new_acc.get("extension") or "")
                    old_enabled = str(bool(old_acc.get("enabled", False)))
                    new_enabled = str(bool(new_acc.get("enabled", False)))
                    if old_ext != new_ext:
                        changes.append({"setting": f"Account {idx} Extension", "old": old_ext, "new": new_ext})
                    if old_enabled != new_enabled:
                        changes.append({"setting": f"Account {idx} Enabled", "old": old_enabled, "new": new_enabled})

                old_blf = {b.get("key_index"): b for b in device.get("blf", [])}
                for new_b in blf:
                    idx = new_b["key_index"]
                    old_b = old_blf.get(idx, {})
                    old_type = str(old_b.get("semantic_type") or "None")
                    new_type = str(new_b.get("semantic_type") or "None")
                    if old_type != new_type:
                        changes.append({"setting": f"BLF {idx} Type", "old": old_type, "new": new_type})
                    old_title = str(old_b.get("title") or "")
                    new_title = str(new_b.get("title") or "")
                    if old_title != new_title:
                        changes.append({"setting": f"BLF {idx} Title", "old": old_title, "new": new_title})
                    old_val = str(old_b.get("value") or "")
                    new_val = str(new_b.get("value") or "")
                    if old_val != new_val:
                        changes.append({"setting": f"BLF {idx} Value", "old": old_val, "new": new_val})

                if request.form.get("save_mode", "notify") == "notify":
                    submit_notify(current_app._get_current_object(), device_id, session.get("username", ""))
                    flash("Assignments saved. Provisioning was queued; you can continue working in DEXPhone and follow the result in Operation history.", "success")
                else:
                    flash("Assignments saved without sending a provisioning request.", "success")
                _audit("Device Edited", f"Device ID={device_id}", changes=changes)"""

if target in content:
    content = content.replace(target, replacement)
    with open("/root/RCM_7021/dex/routes.py", "w") as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Target not found")
