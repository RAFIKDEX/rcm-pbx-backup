# RCM_7021 Backend Architecture Analysis

This report documents the architectural, security, and performance analysis of the core backend components (`app.py`, `db.py`, `asterisk_helper.py`, and security managers) for the RCM_7021 application.

## 1. Application Entry Point and Configuration
- **Entry Point**: The Flask application is initialized directly inside `app.py` on line 19 (`app = Flask(__name__)`).
- **Configuration Loading**: The configuration is hardcoded directly into the script rather than utilizing `app.config.from_pyfile()` or environment variables.
  - E.g., `app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024`
- **Security Issue**: The session secret key is hardcoded as `app.secret_key = "RCM_7021_SECURE_KEY_@123"`.

## 2. Request Lifecycle & Authentication Flow
- **Request Interception**: Handled globally via the `@app.before_request` decorator (`def check_auth()`).
- **Bypass Check**: Skips authentication for predefined `open_endpoints` (e.g., `login`, `static`, `global_favicon`).
- **Session Validation**: Checks for the `logged_in` key in the session. Missing sessions trigger a JSON `401 Unauthorized` for `/api/*` paths or redirect to `/` (login) for standard HTML pages.
- **User Verification (Bottleneck)**: Extracts `username` and performs a fresh database query (`db.get_user_by_username(username)`) on **every single request** to ensure the user's status is `enabled`.
- **Role Assignment**: Validates user type (e.g., `extension_user`) and restricts specific paths dynamically via an `EXTENSION_PORTAL_ENDPOINTS` allowlist.
- **Tokens**: Injects newly generated `csrf_token` and `reboot_token` strings into the session.

## 3. Major Routing Structures
- **Monolithic Route Definition**: `app.py` contains over **230 endpoints** natively without utilizing modular Blueprints (except for one small `con_bp` blueprint appended at the bottom).
- **Structure Mixing**: Standard HTML template routes (e.g., `/extensions`, `/trunks`) are heavily intermingled with REST-like API routes (e.g., `/api/extensions-status`, `/api/apply-changes`).
- **API Convention**: API endpoints typically verify headers (`X-Requested-With`) or paths (`/api/`) to return appropriate JSON error payloads instead of HTML redirects.

## 4. Duplicate or Near-Duplicate Logic
- **Routing Duplication**: Explicitly defined separate, redundant routes for the same static logo asset:
  - `@app.route('/LOGO.jpg')`
  - `@app.route('/Logo.png')`
  - `@app.route('/logo.png')`
- **Permission Checking**: Overlapping security checks. The application utilizes decorator-based controls (`@require_permission(...)`), but endpoints often manually replicate this exact logic via `if session.get('role') != 'admin':`.
- **Database Functions**: Duplicate wrapper schemas in `db.py` handling exact parallel logic, such as `get_trunk_dods` and `get_outbound_route_dods`, or `add_extension` vs `add_extension_with_spy_permissions`.

## 5. Runtime Issues, Performance Slowdowns, and Security Leaks

> [!CAUTION]
> **Severe Password Hashing Vulnerability**: In `db.py`, the `hash_password()` method uses unsalted SHA-256 (`hashlib.sha256(password.encode('utf-8')).hexdigest()`). This is highly susceptible to rainbow tables and extremely weak against modern brute-forcing.

> [!CAUTION]
> **Hardcoded App Secret**: The Flask session cookie signature key is publicly hardcoded into the source (`app.secret_key = "RCM_7021_SECURE_KEY_@123"`).

> [!WARNING]
> **Performance Impact (N+1 Queries)**: The `check_auth` before-request handler queries the user table for *every single incoming request*. Since there is no caching (e.g., Redis or in-memory LRU), this will severely degrade PBX application performance under high load.

> [!WARNING]
> **Database Connection Leaks**: The `db.get_db()` function establishes a new `sqlite3.connect()` connection per request. There is no DB connection pooling logic, and unhandled exceptions during request processing may skip `.close()` calls, silently leaking file descriptors over time.

> [!NOTE]
> **Monolithic Overhead**: `app.py` is nearly 640KB and runs over 14,000 lines of code. Single-file architecture causes slow application cold-starts, high baseline memory utilization, and makes maintenance significantly harder.

## 6. Potentially Unused Routes or Functions
- **Late Script Imports**: Modules like `sip_security_manager` are imported locally deep within `app.py` around line 13,641, suggesting they are disjointed additions.
- **Extraneous Test Files**: Unused test endpoints and scripts (e.g., `test_api.py`, `test_api_speed.py`, `test_sql.py`) are still present in the production `RCM_7021` directory alongside active code, increasing the footprint.
- **Redundant Helpers**: Multiple un-namespaced helper functions like `_is_con_agent()` exist but appear to only serve as internal bindings for the Jinja `inject_user_permissions` context, rather than strictly accessed utilities.