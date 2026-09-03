import sys
import os
import io
import csv
import json
import traceback

# Add RCM_7021 to sys.path
sys.path.insert(0, '/root/RCM_7021')

import app as flask_app
import db

print("=== STARTING USER & PRIVILEGE SYSTEM DIAGNOSTIC RUNNER ===")

client = flask_app.app.test_client()

# We will simulate a logged in super_admin user first to test all endpoints
with client.session_transaction() as sess:
    sess['logged_in'] = True
    sess['user_id'] = 1
    sess['username'] = 'admin'
    sess['role'] = 'admin'
    sess['session_version'] = 1

findings = []

def record_finding(category, title, details, severity="WARN"):
    findings.append({
        "category": category,
        "title": title,
        "details": details,
        "severity": severity
    })
    print(f"[{severity}] [{category}] {title}")

# 1. Test GET /users
print("\n--- 1. Testing GET /users ---")
try:
    resp = client.get('/users')
    if resp.status_code != 200:
        record_finding("GET /users", "Non-200 Status Code on /users", f"Expected 200, got {resp.status_code}", "ERROR")
    else:
        # Check pagination & filters
        resp2 = client.get('/users?search=admin&status=enabled&privilege_id=1&page=1&per_page=10')
        if resp2.status_code != 200:
            record_finding("GET /users Filters", "Filter query failed", f"Status code {resp2.status_code}", "ERROR")
        # Check out-of-bounds page or invalid per_page
        resp3 = client.get('/users?page=-5&per_page=abc')
        if resp3.status_code != 200:
            record_finding("GET /users Edge Case", "Invalid page/per_page caused error", f"Status {resp3.status_code}", "WARN")
except Exception as e:
    record_finding("GET /users", "Exception on /users", traceback.format_exc(), "ERROR")

# 2. Test User Creation /users/add
print("\n--- 2. Testing POST /users/add ---")
try:
    # A. Valid user creation
    resp = client.post('/users/add', data={
        "username": "test_agent_user",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "email": "agent@test.local",
        "privilege_id": "3",
        "status": "enabled"
    }, follow_redirects=True)
    if b"test_agent_user" not in resp.data and b"created successfully" not in resp.data:
        record_finding("POST /users/add", "Failed or silent failure when adding valid user", f"Response length: {len(resp.data)}", "WARN")
    
    # B. Duplicate username
    resp_dup = client.post('/users/add', data={
        "username": "test_agent_user",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "email": "agent2@test.local",
        "privilege_id": "3",
        "status": "enabled"
    }, follow_redirects=True)
    if b"already exists" not in resp_dup.data and b"Error" not in resp_dup.data:
        record_finding("POST /users/add", "Duplicate username handling unclear", "No clear duplicate username flash message detected", "WARN")

    # C. Invalid email format
    resp_bad_email = client.post('/users/add', data={
        "username": "bad_email_user",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "email": "not-an-email",
        "privilege_id": "3",
        "status": "enabled"
    }, follow_redirects=True)
    if b"Invalid email format" not in resp_bad_email.data:
        record_finding("POST /users/add", "Missing email validation message or accepted bad email", "Did not flash 'Invalid email format'", "WARN")

    # D. Password mismatch
    resp_pw_mismatch = client.post('/users/add', data={
        "username": "pw_mismatch_user",
        "password": "Password123!",
        "confirm_password": "Password456!",
        "email": "test@test.local",
        "privilege_id": "3"
    }, follow_redirects=True)
    if b"do not match" not in resp_pw_mismatch.data:
        record_finding("POST /users/add", "Password mismatch not properly flashed", "Did not flash mismatch error", "WARN")
except Exception as e:
    record_finding("POST /users/add", "Exception during user creation tests", traceback.format_exc(), "ERROR")

# Find created user ID
uobj = db.get_user_by_username("test_agent_user")
test_uid = uobj["id"] if uobj else None
print(f"Created test user ID: {test_uid}")

# 3. Test User Edit /users/edit/<id>
print("\n--- 3. Testing POST /users/edit/<id> ---")
if test_uid:
    try:
        # Edit email & status
        resp = client.post(f'/users/edit/{test_uid}', data={
            "username": "test_agent_user_mod",
            "email": "agent_mod@test.local",
            "privilege_id": "3",
            "status": "enabled"
        }, follow_redirects=True)
        if b"updated successfully" not in resp.data:
            record_finding("POST /users/edit/<id>", "User edit flash message missing or update failed", "", "WARN")
        
        # Check if user can disable own account (should be blocked for admin)
        resp_self_disable = client.post('/users/edit/1', data={
            "username": "admin",
            "email": "admin@local.host",
            "privilege_id": "1",
            "status": "disabled"
        }, follow_redirects=True)
        if b"cannot disable your own active account" not in resp_self_disable.data and b"Cannot disable the last active Super Admin" not in resp_self_disable.data:
            record_finding("POST /users/edit/1", "Self-disable or last super admin check response missing/unclear", "", "WARN")
    except Exception as e:
        record_finding("POST /users/edit/<id>", "Exception during user edit", traceback.format_exc(), "ERROR")

# 4. Test Password Reset /users/change-password/<id>
print("\n--- 4. Testing POST /users/change-password/<id> ---")
if test_uid:
    try:
        resp = client.post(f'/users/change-password/{test_uid}', data={
            "password": "NewSecret123!",
            "confirm_password": "NewSecret123!"
        }, follow_redirects=True)
        if b"Password reset successfully" not in resp.data:
            record_finding("POST /users/change-password/<id>", "Password reset response missing", "", "WARN")
    except Exception as e:
        record_finding("POST /users/change-password/<id>", "Exception during password reset", traceback.format_exc(), "ERROR")

# 5. Test Status Toggle /users/toggle/<id> and Revoke Session
print("\n--- 5. Testing POST /users/toggle/<id> and /users/revoke-session/<id> ---")
if test_uid:
    try:
        resp = client.post(f'/users/toggle/{test_uid}', follow_redirects=True)
        if b"is now disabled" not in resp.data and b"is now enabled" not in resp.data:
            record_finding("POST /users/toggle/<id>", "Toggle status message unclear", "", "WARN")
            
        resp_rev = client.post(f'/users/revoke-session/{test_uid}', follow_redirects=True)
        if b"terminated" not in resp_rev.data:
            record_finding("POST /users/revoke-session/<id>", "Revoke session message unclear", "", "WARN")
    except Exception as e:
        record_finding("POST /users/toggle & revoke", "Exception during toggle/revoke", traceback.format_exc(), "ERROR")

# 6. Test Bulk Operations (/users/bulk-toggle, /users/bulk-delete, /users/bulk-assign-role)
print("\n--- 6. Testing Bulk Operations ---")
try:
    # Create a second temp user for bulk testing
    db.create_user("temp_bulk_1", "Secret123!", email="b1@local.host", privilege_id=3)
    db.create_user("temp_bulk_2", "Secret123!", email="b2@local.host", privilege_id=3)
    u1 = db.get_user_by_username("temp_bulk_1")
    u2 = db.get_user_by_username("temp_bulk_2")
    bids = [str(u1["id"]), str(u2["id"])] if u1 and u2 else []
    
    if bids:
        # Bulk toggle
        resp_bt = client.post('/users/bulk-toggle', data={"user_ids": bids, "action": "disable"}, follow_redirects=True)
        if b"disabled 2 selected user" not in resp_bt.data and b"Successfully disabled" not in resp_bt.data:
            record_finding("Bulk Toggle", "Bulk toggle message unexpected", f"Response snippet: {resp_bt.data[:300]}", "WARN")
            
        # Bulk assign role
        resp_br = client.post('/users/bulk-assign-role', data={"user_ids": bids, "privilege_id": "2"}, follow_redirects=True)
        if b"reassigned 2 user account" not in resp_br.data and b"Successfully reassigned" not in resp_br.data:
            record_finding("Bulk Assign Role", "Bulk assign role message unexpected", f"Response snippet: {resp_br.data[:300]}", "WARN")
            
        # Bulk delete
        resp_bd = client.post('/users/bulk-delete', data={"user_ids": bids}, follow_redirects=True)
        if b"deleted 2 selected user" not in resp_bd.data and b"Successfully deleted" not in resp_bd.data:
            record_finding("Bulk Delete", "Bulk delete message unexpected", f"Response snippet: {resp_bd.data[:300]}", "WARN")
            
        # Check what happens when bulk deleting empty or non-existent IDs
        resp_bd_empty = client.post('/users/bulk-delete', data={"user_ids": []}, follow_redirects=True)
        if b"No users selected" not in resp_bd_empty.data:
            record_finding("Bulk Delete Empty", "Did not flash warning on empty selection", "", "WARN")
except Exception as e:
    record_finding("Bulk Operations", "Exception during bulk ops", traceback.format_exc(), "ERROR")

# 7. Test Export/Import CSV
print("\n--- 7. Testing Export / Import CSV ---")
try:
    resp_exp = client.get('/users/export-csv')
    if resp_exp.status_code != 200 or resp_exp.mimetype != "text/csv":
        record_finding("Export CSV", "Users export CSV failed or wrong mimetype", f"Status {resp_exp.status_code}", "ERROR")
    else:
        # Parse output CSV
        csv_data = resp_exp.data.decode('utf-8')
        lines = csv_data.strip().split('\n')
        if len(lines) < 2:
            record_finding("Export CSV", "Exported CSV is empty or only header", f"Line count: {len(lines)}", "WARN")
            
    # Test Import CSV
    csv_input = io.BytesIO(b"Username,Password,Email\ncsv_user_1,Pass123!,c1@test.local\ncsv_user_2,Pass456!,c2@test.local\n")
    resp_imp = client.post('/users/import-csv', data={
        "csv_file": (csv_input, "test_users.csv"),
        "default_privilege_id": "3"
    }, content_type="multipart/form-data", follow_redirects=True)
    if b"Successfully imported" not in resp_imp.data:
        record_finding("Import CSV", "CSV import did not report success", f"Response: {resp_imp.data[:300]}", "WARN")
    else:
        # Clean up imported users
        for cname in ["csv_user_1", "csv_user_2"]:
            cu = db.get_user_by_username(cname)
            if cu: db.delete_user(cu["id"])
except Exception as e:
    record_finding("Export/Import CSV", "Exception during CSV export/import", traceback.format_exc(), "ERROR")

# 8. Test Privileges Management /privileges & /api/privileges/<id>/details
print("\n--- 8. Testing /privileges & Details API ---")
try:
    resp = client.get('/privileges')
    if resp.status_code != 200:
        record_finding("GET /privileges", "Non-200 Status on /privileges", f"Status {resp.status_code}", "ERROR")
        
    resp_det = client.get('/api/privileges/1/details')
    if resp_det.status_code != 200 or not resp_det.is_json:
        record_finding("GET /api/privileges/<id>/details", "Details API failed for Super Admin role", f"Status {resp_det.status_code}", "ERROR")
    else:
        pdata = resp_det.get_json()
        if "permissions" not in pdata or "scopes" not in pdata:
            record_finding("GET details API", "Missing permissions/scopes in details JSON", str(pdata.keys()), "WARN")
            
    # Check invalid details API ID
    resp_bad_det = client.get('/api/privileges/99999/details')
    if resp_bad_det.status_code != 404:
        record_finding("GET details API", "Did not return 404 for non-existent privilege ID", f"Status {resp_bad_det.status_code}", "WARN")
except Exception as e:
    record_finding("Privilege Details", "Exception testing privilege list/details", traceback.format_exc(), "ERROR")

# 9. Test Scopes Options API
print("\n--- 9. Testing /api/scopes/options/<scope_type> ---")
for st in ['queue_live', 'queue_stats', 'cdr_reports', 'call_records', 'unknown_type']:
    try:
        resp_sc = client.get(f'/api/scopes/options/{st}')
        if resp_sc.status_code != 200 or not resp_sc.is_json:
            record_finding(f"Scope Options ({st})", f"Non-200 or non-json on scope options for {st}", f"Status {resp_sc.status_code}", "ERROR")
        else:
            sdata = resp_sc.get_json()
            if "options" not in sdata:
                record_finding(f"Scope Options ({st})", "Missing 'options' key in JSON response", str(sdata), "WARN")
    except Exception as e:
        record_finding(f"Scope Options ({st})", "Exception on scope options", traceback.format_exc(), "ERROR")

# 10. Test Save Privilege (/privileges/save) JSON vs Form
print("\n--- 10. Testing POST /privileges/save ---")
test_priv_id = None
try:
    # A. Create custom role via JSON
    resp_json = client.post('/privileges/save', json={
        "name": "Test Custom Role JSON",
        "description": "Created via diagnostic runner",
        "legacy_role": "agent",
        "permissions": [{"module": "cdr", "action": "view"}, {"module": "extensions", "action": "view"}],
        "scopes": {"settings": {"cdr_reports": "selected"}, "items": {"cdr_reports": ["101", "102"]}}
    })
    if resp_json.status_code != 200:
        record_finding("POST /privileges/save (JSON)", "Non-200 when creating role via JSON", f"Status {resp_json.status_code}, {resp_json.data}", "ERROR")
    else:
        jres = resp_json.get_json()
        if not jres.get("success"):
            record_finding("POST /privileges/save (JSON)", "JSON response reported failure", str(jres), "ERROR")
        else:
            test_priv_id = jres.get("id")
            
    # B. Test Duplicate Role Name
    resp_dup_role = client.post('/privileges/save', json={
        "name": "Test Custom Role JSON",
        "description": "Duplicate test",
        "legacy_role": "agent",
        "permissions": []
    })
    if resp_dup_role.status_code == 200 and resp_dup_role.get_json().get("success"):
        record_finding("POST /privileges/save", "Allowed duplicate privilege name!", "", "ERROR")
    else:
        # Check error message
        if "already exists" not in str(resp_dup_role.data):
            record_finding("POST /privileges/save", "Duplicate role error message unclear", str(resp_dup_role.data), "WARN")
            
    # C. Create via Form data
    resp_form = client.post('/privileges/save', data={
        "name": "Test Custom Role Form",
        "description": "Created via form",
        "legacy_role": "supervisor",
        "perm_cdr:view": "on",
        "perm_cdr:export": "on",
        "scope_mode_cdr_reports": "selected",
        "scope_items_cdr_reports": "105"
    }, follow_redirects=True)
    if b"saved successfully" not in resp_form.data:
        record_finding("POST /privileges/save (Form)", "Form save did not report success", f"Snippet: {resp_form.data[:300]}", "WARN")
        
    # Check that auto view injection worked for form role
    form_role = db.get_privileges_list(search="Test Custom Role Form")
    if form_role:
        f_id = form_role[0]["id"]
        f_perms = db.get_privilege_permissions(f_id)
        if ("cdr", "view") not in f_perms:
            record_finding("Auto View Injection", "Auto-injection of view permission failed when saving via Form", str(f_perms), "ERROR")
except Exception as e:
    record_finding("Save Privilege", "Exception during privilege save", traceback.format_exc(), "ERROR")

# 11. Test Duplicate & Delete Privileges
print("\n--- 11. Testing Duplicate & Delete Privilege ---")
if test_priv_id:
    try:
        # Duplicate
        resp_dup = client.post(f'/privileges/duplicate/{test_priv_id}', data={"new_name": "Test Custom Role Copy"}, follow_redirects=True)
        if b"duplicated as" not in resp_dup.data and b"successfully" not in resp_dup.data:
            record_finding("Duplicate Privilege", "Duplicate privilege message missing/unexpected", "", "WARN")
        
        # Find copy ID and delete copy
        copy_role = db.get_privileges_list(search="Test Custom Role Copy")
        if copy_role:
            c_id = copy_role[0]["id"]
            resp_del = client.post(f'/privileges/delete/{c_id}', follow_redirects=True)
            if b"deleted successfully" not in resp_del.data:
                record_finding("Delete Privilege", "Delete unassigned custom role failed or silent", "", "WARN")
                
        # Test deleting role currently assigned to a user without fallback
        if test_uid:
            db.update_user(test_uid, privilege_id=test_priv_id)
            resp_del_blocked = client.post(f'/privileges/delete/{test_priv_id}', follow_redirects=True)
            if b"Select a fallback role to reassign" not in resp_del_blocked.data and b"Cannot delete privilege assigned" not in resp_del_blocked.data:
                record_finding("Delete Assigned Privilege", "Did not properly block or warn when deleting assigned role without fallback", "", "ERROR")
                
            # Now delete WITH fallback
            resp_del_fallback = client.post(f'/privileges/delete/{test_priv_id}', data={"fallback_privilege_id": "3"}, follow_redirects=True)
            if b"deleted successfully" not in resp_del_fallback.data:
                record_finding("Delete Privilege with Fallback", "Failed to delete role even when fallback role was provided", f"Snippet: {resp_del_fallback.data[:300]}", "ERROR")
            else:
                # Verify that user was reassigned to fallback (id 3)
                updated_u = db.get_user_by_id(test_uid)
                if updated_u and str(updated_u.get("privilege_id")) != "3":
                    record_finding("Delete Privilege Fallback Reassignment", f"User was not correctly reassigned to fallback role! Current priv: {updated_u.get('privilege_id')}", "", "ERROR")
    except Exception as e:
        record_finding("Duplicate/Delete Privilege", "Exception testing duplicate/delete", traceback.format_exc(), "ERROR")

# 12. Test Export JSON & CSV for Privileges
print("\n--- 12. Testing Export JSON/CSV for Privileges ---")
try:
    r_pjson = client.get('/privileges/export-json')
    if r_pjson.status_code != 200 or not r_pjson.is_json:
        record_finding("Export Privileges JSON", "Export JSON non-200 or not JSON", f"Status {r_pjson.status_code}", "ERROR")
    r_pcsv = client.get('/privileges/export-csv')
    if r_pcsv.status_code != 200 or r_pcsv.mimetype != "text/csv":
        record_finding("Export Privileges CSV", "Export CSV non-200 or wrong mimetype", f"Status {r_pcsv.status_code}", "ERROR")
except Exception as e:
    record_finding("Export Privileges", "Exception testing privilege exports", traceback.format_exc(), "ERROR")

# Clean up any remaining test user/role
print("\n--- Cleaning up test artifacts ---")
if test_uid:
    db.delete_user(test_uid)
for rname in ["Test Custom Role Form", "Test Custom Role JSON"]:
    rl = db.get_privileges_list(search=rname)
    if rl: db.delete_privilege(rl[0]["id"], fallback_privilege_id=3)

print("\n=== DIAGNOSTIC RUN COMPLETE ===")
with open('/root/RCM_7021/scratch/diagnostic_results.json', 'w') as f:
    json.dump(findings, f, indent=2)
print(f"Total findings recorded: {len(findings)}")
