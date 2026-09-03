# Frontend Consistency Analysis Report: RCM_7021

## 1. Frontend Architecture Mapping
The frontend is primarily built using Server-Side Rendering (SSR) via **Jinja2** templates inside the `templates/` directory, paired with Flask controllers in `app.py`.
- **Base Layouts**: `base.html` serves as the global layout wrapper containing common CSS and JS.
- **Component Forms**: Entity creations/editions use a `*_form.html` (e.g., `queue_form.html`, `extension_form.html`) convention.
- **Lists/Data**: Data tables are rendered in `*_list.html` or dedicated pages (e.g., `extensions.html`, `cdr.html`).
- **Client-Side Interactions**: Vanilla JS is heavily embedded directly inside the `{% block extra_scripts %}` sections of each HTML file rather than extracted into the `static/` folder.

## 2. Flask Routes <-> Jinja Templates Relationship
The UI routing tightly couples Flask endpoints and Jinja templates:
- Rendering: `@app.route` decorators return `render_template('template_name.html', context_vars...)`.
- Form Submission: Standard `POST` requests are directed to dedicated backend handlers (e.g., `extensions_add`, `queue_edit`), where `app.py` leverages `request.form.get()` and `request.form.getlist()` to extract values mirroring the `name=""` attributes in the forms.
- *Exceptions*: Specific sub-modules like the Conductor application use separate routing files (`con_routes.py`) to render templates (`con_agent.html`, `con_supervisor.html`).

## 3. Frontend <-> Backend Inconsistencies
- **Missing / Ignored Form Fields**: The `extension_form.html` sends `fwd_always_status`, `fwd_noanswer_status`, and `fwd_busy_status` fields, which are not directly retrieved by `extensions_add()` but are effectively parsed through an abstract `parse_extension_features_form()` helper method. The overall form bindings are largely synchronized correctly.
- **Dead UI Controls**: The Ring Strategy selection (`strategy`) in `ringgroup_form.html` correctly toggles the visibility of the `per_try` input group. However, when set to `ringall` (which hides the `per_try` field), the form still submits `per_try` which is captured by the backend indiscriminately.
- **Routes with No UI Callers**: Several `app.py` POST endpoints like `/extensions/bulk-delete`, `/extensions/bulk-edit`, and `/queues/<num>/agents/*` are API-like routes. They do not render Jinja templates on success and instead are invoked asynchronously (fetch/AJAX) by the frontend JavaScript (found in `extensions.html` and `queue_live.html`).

## 4. Duplicate UI Logic & Repeated JS Blocks
There is significant code duplication in embedded JavaScript across multiple templates. This logic should ideally be modularized into a shared `.js` file within `static/`:
- **Tab Switching Logic**: A `switchTab()` function for handling visibility of tabbed content sections is defined redundantly across:
  - `extension_form.html`
  - `queue_form.html`
  - `queue_stats.html`
  - `privileges_management.html`
  - `media_center.html`
  - `queue_detail.html`
- **Dual-List Select Controls**: The exact same JS logic for moving items between two `<select multiple>` boxes (`addSelected()`, `removeSelected()`, `addAll()`, `removeAll()`, `filterSelect()`, `moveUp()`, `moveDown()`) is duplicated across:
  - `queue_form.html`
  - `paging_form.html`
  - `ringgroup_form.html`
  - `pickup_groups_form.html`

## 5. Unused Templates and Obsolete Files
- **Obsolete Backups**: `cdr.html.bak_20260701_170600` exists in the `templates/` directory and should be safely removed to clean up the codebase.
- **Orphan-Looking Templates**: `con_agent.html` and `con_supervisor.html` appear disconnected when inspecting `app.py`. However, they are actively utilized by the `con_routes.py` blueprint and are therefore *not* obsolete.