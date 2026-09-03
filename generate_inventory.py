import csv
import sys
import os
import inspect
import app as rcm_app

def generate_route_inventory():
    flask_app = rcm_app.app
    inventory = []

    for rule in sorted(flask_app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint == 'static':
            continue

        func = flask_app.view_functions.get(rule.endpoint)
        if not func:
            continue

        methods = sorted(list(rule.methods - {'HEAD', 'OPTIONS'}))
        methods_str = ", ".join(methods)

        # Traverse wrapper chain
        curr = func
        perm_info = None
        csrf_required = False

        while curr:
            if hasattr(curr, '_required_permission'):
                perm_info = curr._required_permission
            if hasattr(curr, '_requires_csrf'):
                csrf_required = True
            curr = getattr(curr, '__wrapped__', None)

        # Check source code if no decorator found or to check super admin / login
        src = inspect.getsource(func)
        super_admin_check = "system_key == 'super_admin'" in src or 'require_super_admin' in src
        login_check = 'session.get("user")' in src or 'session.get("username")' in src or 'session.get("role")' in src

        module = ""
        action = ""
        scope_param = ""
        scope_type = ""
        fallback = ""

        if perm_info:
            module = str(perm_info[0]) if len(perm_info) > 0 and perm_info[0] else ""
            action = str(perm_info[1]) if len(perm_info) > 1 and perm_info[1] else ""
            scope_param = str(perm_info[2]) if len(perm_info) > 2 and perm_info[2] else ""
            scope_type = str(perm_info[3]) if len(perm_info) > 3 and perm_info[3] else ""
            if len(perm_info) > 4 and perm_info[4]:
                fallback = str(perm_info[4])
        elif super_admin_check:
            module = "super_admin"
            action = "all"
        elif login_check:
            module = "authenticated_user"
            action = "access"

        # Determine status/sensitivity
        public_endpoints = {
            'global_favicon', 'global_logo_png', 'login',
            'forgot_password', 'forgot_password_verify', 'forgot_password_reset',
            'logout'
        }

        if rule.endpoint in public_endpoints:
            status = "Public / Auth"
            if rule.endpoint in ('login', 'forgot_password', 'forgot_password_verify', 'forgot_password_reset'):
                csrf_required = True
        elif module or super_admin_check:
            status = "Secured (Role/Scope)"
        else:
            status = "Secured (Session)"

        # Check if CSRF required implicitly on modifying methods
        modifying_methods = {'POST', 'PUT', 'DELETE'}
        has_modifying = any(m in modifying_methods for m in methods)
        if has_modifying and rule.endpoint in public_endpoints and rule.endpoint != 'logout':
            csrf_status = "Yes (Auth CSRF)"
        elif has_modifying and csrf_required:
            csrf_status = "Yes"
        elif not has_modifying:
            csrf_status = "N/A (GET)"
        else:
            csrf_status = "Missing/No"

        inventory.append({
            "endpoint": rule.endpoint,
            "route": rule.rule,
            "methods": methods_str,
            "module": module,
            "action": action,
            "scope_param": scope_param or "-",
            "scope_type": scope_type or (module if scope_param else "-"),
            "csrf": csrf_status,
            "status": status
        })

    # Write CSV
    csv_path = "/root/RCM_7021/route_inventory.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "endpoint", "route", "methods", "module", "action", "scope_param", "scope_type", "csrf", "status"
        ])
        writer.writeheader()
        writer.writerows(inventory)

    # Write Markdown
    md_path = "/root/RCM_7021/route_inventory.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Flask Route Security & Scope Inventory\n\n")
        f.write(f"Total Routes Mapped: **{len(inventory)}**\n\n")
        f.write("| Endpoint | Route Pattern | HTTP Methods | Permission Module | Action | Scope Param | Scope Type | CSRF Protection | Security Status |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for row in inventory:
            f.write(f"| `{row['endpoint']}` | `{row['route']}` | {row['methods']} | {row['module'] or '-'} | {row['action'] or '-'} | {row['scope_param']} | {row['scope_type']} | {row['csrf']} | **{row['status']}** |\n")

    print(f"Successfully generated route inventory: {len(inventory)} routes recorded.")
    print(f"CSV saved to {csv_path}")
    print(f"Markdown saved to {md_path}")

if __name__ == "__main__":
    generate_route_inventory()
