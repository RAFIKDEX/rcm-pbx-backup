# Frontend & Security Audit Findings

## 1. Broken CSRF Protection Decorator (Bypass for PBX Modules)
**Severity:** P0 - Critical
**Category:** Security
**Exact file(s):** `app.py`
**Exact function/class/route/component:** `require_csrf` decorator
**What is happening:** The `require_csrf` decorator only enforces CSRF checks if the request path starts with `/users/`, `/privileges/`, `/sip_security`, or `/security`. For all other routes (e.g., `/extensions/`, `/queues/`, `/api/apply-changes`), it silently skips the CSRF check and executes the underlying route function.
**Why it is a problem:** Malicious websites can forge cross-site requests to perform dangerous actions on the PBX (like deleting extensions, changing queue settings, applying changes) without the administrator's consent because the CSRF token validation is skipped.
**How a user can encounter it:** A logged-in administrator visits a malicious webpage that sends hidden POST requests to the PBX server.
**Expected behavior:** All state-changing POST requests decorated with `@require_csrf` should strictly enforce the CSRF token validation, regardless of the route path.
**Current behavior:** The CSRF check is bypassed for most modules due to a hardcoded `protected_path` allowlist inside the decorator.
**Technical root cause:** The `protected_path` condition in the `require_csrf` decorator restricts CSRF validation to a small subset of URL prefixes, effectively disabling the protection for the rest of the application.
**Possible consequences:** Complete compromise of PBX configuration, deletion of users/extensions, unauthorized outbound calls, system downtime.
**Recommended solution:** Remove the `protected_path` check entirely from `require_csrf` and validate the token for all non-GET/HEAD/OPTIONS requests handled by the decorator. (Note: frontend API calls in various modules will need to be updated to pass the token as well).
**Whether it requires database changes:** No
**Whether it affects Asterisk:** Yes
**Whether it affects GUI/UI/UX:** No
**Whether it affects security:** Yes
**Whether it affects performance:** No
**Whether it requires tests:** Yes

## 2. Missing CSRF Tokens in Frontend Fetch Requests & Inline Forms
**Severity:** P1 - High
**Category:** Frontend / Security
**Exact file(s):** `templates/extensions.html`
**Exact function/class/route/component:** `submitBulkDelete`, `submitBulkEdit` Javascript functions, and inline `deleteAction` form.
**What is happening:** Frontend Javascript `fetch` calls for bulk actions send POST requests but do not include the CSRF token in the headers or payload. Additionally, the dynamically injected inline form for single extension deletion does not include the hidden `csrf_token` input.
**Why it is a problem:** Once the backend CSRF decorator is fixed, these actions will immediately fail with a 403 Forbidden error, breaking PBX administration workflows.
**How a user can encounter it:** By attempting to edit or delete extensions after backend CSRF security is enforced.
**Expected behavior:** All POST requests, including those triggered via Javascript `fetch` or dynamically built forms, must include a valid CSRF token.
**Current behavior:** The UI attempts to submit POST data without any CSRF authentication mechanism.
**Technical root cause:** The frontend templates were not built to append the global CSRF token into fetch headers or dynamically built DOM forms.
**Possible consequences:** Broken UI functionality once backend security is enforced.
**Recommended solution:** Update the `deleteAction` template string in `extensions.html` to inject `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. For `fetch` calls, read the token and append it to the `X-CSRF-Token` header.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** Yes
**Whether it affects performance:** No
**Whether it requires tests:** Yes

## 3. Stored XSS in User Activity Audit Trail
**Severity:** P1 - High
**Category:** Security
**Exact file(s):** `templates/users_management.html`
**Exact function/class/route/component:** `openUserActivityModal` JavaScript function
**What is happening:** Audit log data (`log.action`, `log.module`, `log.details`, `log.message`, `log.ip_address`) returned from the `/api/users/.../activity` endpoint is directly injected into the DOM using template literals and `.innerHTML` without any HTML escaping.
**Why it is a problem:** If an attacker can inject malicious payloads into audit logs (e.g., via a crafted User-Agent, spoofed IP address, or by triggering an error message containing payload string), the script will execute in the context of the administrator viewing the activity log.
**How a user can encounter it:** An administrator opens the "Audit Trail" (Activity Modal) for a user account that has logged maliciously crafted entries.
**Expected behavior:** All dynamically loaded text data should be properly HTML-escaped before insertion using `.innerHTML`, or inserted using `.textContent`.
**Current behavior:** Untrusted log data is interpolated into an HTML string and appended via `item.innerHTML`.
**Technical root cause:** The Javascript code lacks an `escapeHtml()` helper for the `log` object properties when building the `item.innerHTML` string.
**Possible consequences:** Session hijacking, unauthorized actions performed on behalf of the administrator viewing the logs.
**Recommended solution:** Apply a client-side HTML sanitization or escaping function (like the one used in `extensions.html`) to all variable properties before injecting them into the HTML template literal.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** No
**Whether it affects security:** Yes
**Whether it affects performance:** No
**Whether it requires tests:** Yes

## 4. Missing Session Expiry / Error Handling in Dashboard & Table Polling
**Severity:** P3 - Low
**Category:** UI/UX / User Workflow
**Exact file(s):** `templates/dashboard.html`, `templates/extensions.html`
**Exact function/class/route/component:** `updateDashboard()`, `loadExtensionsTable()`
**What is happening:** The dashboard and extension pages rely on `fetch` or `setInterval` polling to update data. If the user's session expires, the backend responds with a 401 Unauthorized (or a redirect to login which fails JSON parsing). The `.catch()` blocks simply log the error to the console.
**Why it is a problem:** The user sees a frozen UI or infinite "Loading..." spinners and does not know their session expired until they attempt to interact with the page, resulting in a jarring workflow interruption. The browser also continuously spams the backend with unauthenticated requests.
**How a user can encounter it:** Leaving the PBX tab open until the login session times out, or encountering a network disruption.
**Expected behavior:** When a 401 Unauthorized response is received, or if JSON parsing fails on a redirected HTML login page, the UI should halt polling and gracefully redirect the user to `/login` (or display a "Session Expired" alert).
**Current behavior:** Polling endpoints fail silently to the console, while UI components (like the extensions table) remain in an infinite loading state.
**Technical root cause:** The Javascript `.catch()` and `then()` logic for these endpoints does not inspect `res.status` or handle non-JSON responses gracefully.
**Possible consequences:** User confusion over stale data, unnecessary load on the server from constant 401 requests.
**Recommended solution:** Inspect the HTTP response code before calling `res.json()`. If it is a 401, execute `window.location.href = '/login';`. If the fetch fails entirely, show a user-visible error state in the UI (e.g., an error icon/text inside the table body instead of the loading spinner).
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** No

## 5. Inconsistent CSRF Header Key Implementation
**Severity:** P2 - Medium
**Category:** Security / Broken Logic
**Exact file(s):** `templates/base.html`, `app.py`
**Exact function/class/route/component:** Global "Apply Changes" fetch request (`base.html`), `require_csrf` (`app.py`)
**What is happening:** In `base.html`, the fetch request for `/api/apply-changes` sends the CSRF token using the header `'X-CSRFToken'`. However, `app.py`'s `require_csrf` function strictly looks for `'X-CSRF-Token'` (with a hyphen).
**Why it is a problem:** Even if the `protected_path` bug in `app.py` is fixed, the "Apply Changes" button will break globally because the header names do not match, causing a false-positive CSRF rejection.
**How a user can encounter it:** By clicking "Apply Changes" after backend CSRF security is properly enforced.
**Expected behavior:** Client and server must agree on the exact HTTP header key used for CSRF token transmission.
**Current behavior:** The client uses `X-CSRFToken` while the server expects `X-CSRF-Token`. It only works currently because `/api/apply-changes` is completely skipped by the CSRF check.
**Technical root cause:** Typo/inconsistency between frontend implementation and backend validation logic.
**Possible consequences:** The global "Apply Changes" feature breaks entirely.
**Recommended solution:** Standardize the header. Update `base.html` to send `X-CSRF-Token: ...` instead of `X-CSRFToken`.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** Yes
**Whether it affects performance:** No
**Whether it requires tests:** Yes