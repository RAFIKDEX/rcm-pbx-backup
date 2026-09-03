import sys
import io
import csv
import json
import traceback
from bs4 import BeautifulSoup

sys.path.insert(0, '/root/RCM_7021')
import app as flask_app
import db

client = flask_app.app.test_client()

def get_flashes(response_data):
    soup = BeautifulSoup(response_data, 'html.parser')
    flashes = []
    for alert in soup.find_all(class_=['alert', 'flash', 'message']):
        flashes.append(alert.get_text(strip=True))
    # Also look for alert divs
    for div in soup.find_all('div'):
        if div.get('class') and any('alert-' in c for c in div.get('class')):
            flashes.append(div.get_text(strip=True))
    return flashes

findings = []
def log_issue(category, title, details, severity="WARN"):
    findings.append({"category": category, "title": title, "details": details, "severity": severity})
    print(f"[{severity}] [{category}] {title}\n    Details: {details}")

print("=== DEEP DIAGNOSTIC RUNNER PART 2 ===")

with client.session_transaction() as sess:
    sess['logged_in'] = True
    sess['user_id'] = 1
    sess['username'] = 'admin'
    sess['role'] = 'admin'
    sess['session_version'] = 1

# 1. Investigate POST /users/edit/1 (self disable)
resp = client.post('/users/edit/1', data={
    "username": "admin",
    "email": "admin@local.host",
    "privilege_id": "1",
    "status": "disabled"
}, follow_redirects=True)
flashes = get_flashes(resp.data)
print("Flashes when self-disabling admin:", flashes)
if not any("cannot disable your own active account" in f.lower() or "cannot disable the last active super admin" in f.lower() for f in flashes):
    log_issue("User Edit API", "Missing or weak prevention when admin tries to disable own account via edit form", f"Flashes got: {flashes}", "ERROR")

# 2. Investigate Delete Privilege with Fallback
# Create test role and assign to test user
success, priv_id, err = db.save_privilege_atomic(None, "Temporary Role To Delete", "Test", "agent", [("cdr", "view")], {})
success_u, uid, err_u = db.create_user("temp_user_for_role_del", "Secret123!", email="del@local.host", privilege_id=priv_id)

# Try deleting without fallback
resp_del_no_fb = client.post(f'/privileges/delete/{priv_id}', follow_redirects=True)
flashes_no_fb = get_flashes(resp_del_no_fb.data)
print("Flashes when deleting assigned role without fallback:", flashes_no_fb)
if not any("cannot delete privilege assigned to" in f.lower() for f in flashes_no_fb):
    log_issue("Privilege Delete API", "Unassigned role deletion error message unclear when role has active users", f"Flashes got: {flashes_no_fb}", "WARN")

# Try deleting with fallback = 3 (Agent)
resp_del_fb = client.post(f'/privileges/delete/{priv_id}', data={"fallback_privilege_id": "3"}, follow_redirects=True)
flashes_fb = get_flashes(resp_del_fb.data)
print("Flashes when deleting assigned role WITH fallback:", flashes_fb)
if any("cannot delete privilege assigned to" in f.lower() or "cannot delete" in f.lower() or "error" in f.lower() for f in flashes_fb):
    log_issue("Privilege Delete API", "Deleting role WITH fallback failed!", f"Flashes got: {flashes_fb}", "ERROR")
else:
    # Check if user was reassigned
    check_u = db.get_user_by_id(uid)
    print("User after role deletion with fallback:", check_u["privilege_id"] if check_u else None)

# Cleanup
if uid: db.delete_user(uid)
if priv_id: db.delete_privilege(priv_id, fallback_privilege_id=3)

# 3. Check Privilege Permissions View Injection behavior & edge cases
# What if someone submits action='edit' without action='view'?
success, p_id_no_view, _ = db.save_privilege_atomic(None, "No View Test Role", "Test", "agent", [("extensions", "edit")], {})
perms = db.get_privilege_permissions(p_id_no_view)
print("Permissions stored when only 'edit' is submitted:", perms)
if ("extensions", "view") not in perms:
    log_issue("Privilege Save DB", "Auto-inject view permission missed 'extensions:edit'", f"Stored: {perms}", "ERROR")
db.delete_privilege(p_id_no_view)

# 4. Check user search with SQL wildcards (% and _)
resp_search_wild = client.get('/users?search=%25')
if resp_search_wild.status_code != 200:
    log_issue("User Search", "Search with SQL wildcard % returned non-200", f"Status {resp_search_wild.status_code}", "ERROR")
else:
    # Check if searching % returns all users or crashes
    soup_s = BeautifulSoup(resp_search_wild.data, 'html.parser')
    rows = soup_s.find_all('tr')
    print("Rows found when searching '%':", len(rows))

# 5. Check what happens if user enters privilege_id as string/SQL injection attempt in GET /users
resp_sqli = client.get('/users?privilege_id=1+OR+1=1')
if resp_sqli.status_code != 200:
    log_issue("User Search SQLi check", "SQL injection or invalid privilege_id in filter caused crash", f"Status {resp_sqli.status_code}", "WARN")

# 6. Check access control: what happens when an Agent (privilege_id=3) tries to access /users and /privileges
with client.session_transaction() as sess_agent:
    sess_agent['user_id'] = 3
    sess_agent['username'] = 'agent_test'
    sess_agent['role'] = 'agent'
    sess_agent['session_version'] = 1

resp_agent_u = client.get('/users')
resp_agent_p = client.get('/privileges')
resp_agent_api = client.get('/api/privileges/1/details')
print(f"Agent access check - /users: {resp_agent_u.status_code}, /privileges: {resp_agent_p.status_code}, /api/privileges/1/details: {resp_agent_api.status_code}")
if resp_agent_u.status_code == 200 or resp_agent_p.status_code == 200:
    log_issue("Access Control", "Agent role without permission allowed access to /users or /privileges!", f"/users: {resp_agent_u.status_code}, /privileges: {resp_agent_p.status_code}", "ERROR")

# 7. Check bulk assign role with invalid privilege ID or protected Super Admin ID (1)
with client.session_transaction() as sess_admin:
    sess_admin['user_id'] = 1
    sess_admin['username'] = 'admin'
    sess_admin['role'] = 'admin'

# Try assigning multiple users to Super Admin (privilege_id = 1)
# Create a temp user
success_u2, uid2, _ = db.create_user("temp_user_assign", "Secret123!", email="t2@local.host", privilege_id=3)
resp_bulk_super = client.post('/users/bulk-assign-role', data={"user_ids": [str(uid2)], "privilege_id": "1"}, follow_redirects=True)
flashes_bulk_super = get_flashes(resp_bulk_super.data)
print("Flashes assigning to Super Admin via bulk:", flashes_bulk_super)
if uid2: db.delete_user(uid2)

print("\n=== PART 2 COMPLETE ===")
