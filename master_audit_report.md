# RCM_7021 Comprehensive Project Audit Report

## 1. Project Understanding
RCM_7021 is a comprehensive Call Center and PBX management platform, deeply integrated with the Asterisk telephony engine. It provides web-based configuration, real-time queue dashboards, Call Detail Record (CDR) reporting, and automated background processing. The system uses a monolithic Flask web backend (`app.py`), a suite of Python-based background collectors and daemons for real-time AMI parsing, and multiple SQLite databases for persistence. The architecture separates active configuration (mostly tracked in `rcm_7021.db` and JSON files) from high-throughput real-time queue metrics (`rcm_queue.db`). It also features specialized subsystems like DEX (for Grandstream phone provisioning) and AGI scripts for telephony features (e.g., surveys).

## 2. Project Structure
- **/root/RCM_7021/**: The root application directory.
  - `app.py`: The monolithic Flask application handling UI, API routes, and request security.
  - `db.py`: The data access layer for the main `rcm_7021.db` database.
  - `rcm_queue_db.py`: The data access layer for real-time queue states and analytics.
  - `asterisk_helper.py`: A wrapper module translating application logic into Asterisk configuration commands.
  - `rcm_queue_collector.py`: A persistent daemon connecting to the Asterisk AMI to ingest live queue events.
  - `scheduler_service.py`: A polling background worker managing email queues and generating periodic CDR metrics.
  - `cdr_journey.py`: A module dedicated to dynamically reconstructing call timelines using log streams.
- **templates/**: Contains Jinja2 server-side rendering templates.
- **static/**: Contains CSS and JavaScript assets, though much of the JS is embedded directly in templates.
- **scripts/**: Utility scripts, AGI survey handlers (`survey_agi.py`), and repair tools (`repair_media_center.py`).
- **deploy/**: Systemd service files and Apache configurations for phone provisioning.
- **dex/**: An internal Python module and framework dedicated to Grandstream phone Plug-and-Play (PnP) provisioning.

## 3. Major Components
1. **Web Core & Administration**: Managed by `app.py`, this handles routing, authentication, and the PBX UI. It interfaces directly with `db.py` to write configurations (extensions, trunks, queues).
2. **Real-time Queue Subsystem**: Asterisk emits live events over AMI. `rcm_queue_collector.py` parses these and invokes `rcm_queue_db.py` to update `queue_live` and `queue_calls` inside `rcm_queue.db`. This data drives the live wallboards and agent tracking.
3. **CDR & Metrics Aggregator**: Handled by `scheduler_service.py` and `cdr_journey.py`. They parse Asterisk CSV logs and queue logs, calculate SLAs, process answer/hold times, and prepare the data for the web UI.
4. **Provisioning Framework (DEX)**: Operates semi-independently on port 8091 (configured via `deploy/`), managing device deployments, MAC mapping, and configuration generation for specific phone brands.

## 4. Duplicate Code
- **Database Wrapper Duplication**:
  - *Location*: `db.py` (e.g., `get_trunk_dods` vs `get_outbound_route_dods`).
  - *Duplicate Behavior*: Identical schema patterns and data access logic wrapper functions for similar entities.
  - *Evidence*: Parallel logic flows mapping similar many-to-many relationships.
  - *Why it exists*: Likely a result of organic growth where new features were copy-pasted instead of abstracted.
  - *Risk of removing*: High. While technically duplicate, these wrappers are directly coupled to distinct routes in `app.py`. Refactoring requires altering both the database access layer and the API layer.
- **Frontend JavaScript Logic**:
  - *Location*: Embedded inside `templates/queue_form.html`, `paging_form.html`, etc.
  - *Duplicate Behavior*: Dual-list `<select>` box manipulation (move up/down, add/remove).
  - *Evidence*: Exact identical JS functions (`addSelected()`, `removeAll()`) exist in 4+ templates.
  - *Why it exists*: Lack of a unified modular `static/` JS architecture.
  - *Risk of removing*: Low to Medium. Extracting this into a single shared `.js` file is a safe refactor.

## 5. Potentially Unused Code
- **Unused/Empty Features**:
  - *Location*: `db.py` schema (`surveys`, `survey_questions` tables).
  - *Why it appears unused*: The main application does not interface heavily with these.
  - *Evidence*: AGI scripts (`survey_agi.py`) exist in `/scripts/`, but the primary web UI does not seem to fully manage or expose them.
  - *Confidence*: 75%. (Possible hidden dependency on Asterisk dialplan accessing the AGI script).
- **Extraneous Test Files**:
  - *Location*: `/root/RCM_7021/test_*.py`.
  - *Why it appears unused*: They are test harnesses mixed into the production deployment directory.
  - *Evidence*: File naming and contents represent test logic.
  - *Confidence*: 100%. (They do not execute in the runtime request flow).
- **Backup Templates**:
  - *Location*: `templates/cdr.html.bak_20260701_170600`.
  - *Why it appears unused*: Flask relies on specific exact file names for rendering.
  - *Evidence*: The `.bak` extension prevents Flask from actively referencing it.
  - *Confidence*: 100%.

## 6. Potential Problems
- **Database Connection Leaks**
  - *Severity*: High
  - *Confirmed*: Yes.
  - *Location*: `db.get_db()`, `rcm_queue_db.py`.
  - *Explanation*: New `sqlite3.connect()` calls are made per database query without a centralized connection pool. If exceptions occur before `.close()` is called, file descriptors are silently leaked.
  - *Impact*: Over time, the application will crash with "Too many open files" errors.
  - *Trigger*: Unhandled exceptions during API request processing or background task execution.
- **Dangerous Transaction Handling (Database Locking)**
  - *Severity*: Critical
  - *Confirmed*: Yes.
  - *Location*: `rcm_queue_db.py`.
  - *Explanation*: Real-time handlers (e.g., `db_call_ring`) instantiate, query, and close DB connections rapidly in response to AMI socket events.
  - *Impact*: High risk of SQLite `database is locked` deadlocks due to massive filesystem I/O contention during peak call volumes.
  - *Trigger*: High concurrent call volume flooding the queue collector.
- **N+1 Query Architectures**
  - *Severity*: High
  - *Confirmed*: Yes.
  - *Location*: `app.py` (`check_auth`), `rcm_queue_db.py` (`db_reindex_queue_positions`), `scheduler_service.py` (`monitor_missed_calls`).
  - *Explanation*: Functions loop over result sets and execute individual SQL queries per row instead of utilizing bulk `UPDATE` or `JOIN` statements.
  - *Impact*: Extreme latency scaling linearly with data size.
  - *Trigger*: Large queue arrays, high missed call volumes, or high active user request concurrency.

## 7. Legacy Code
- **Redundant Queue Metric Tables**: 
  - `rcm_7021.db` initializes tables like `rcm_queue_log`, `rcm_queue_calls`, and `rcm_agent_sessions`. These are legacy implementations that have been completely superseded by `rcm_queue.db`. They are still initialized in `db.py` and occasionally polled, creating technical debt and scattering telemetry data.
- **Database Migrations Anti-pattern**:
  - `init_queue_db()` relies on a brittle sequence of naked `try/except sqlite3.OperationalError` blocks attempting to `ALTER TABLE` fields to simulate schema migrations.

## 8. Conflicting Logic
- **Call Duration Metrics Conflict**:
  - *Conflict*: `rcm_queue_db.py` computes metrics naively (e.g., `talk_time = total - hold_time`), relying on the timestamp of the *most recent* `HOLD` event. `cdr_journey.py` calculates it exactly by subtracting precise, overlapping `BRIDGE` and `HOLD` intervals.
  - *Active Implementation*: `rcm_queue.db` drives the real-time dashboards and raw analytics, but `cdr_journey.py` generates the visual timelines in the UI. Thus, users will see completely different talk/hold durations between the Dashboard and the specific CDR Timeline for the same call.

## 9. Performance Concerns
- **CPU / Request Overhead**: `app.py` is a monolithic 640KB script executing a fresh database query on *every single request* via `@app.before_request` to verify the user session, completely lacking cache layers.
- **Database / Disk I/O**: Constant instantiation and destruction of SQLite connections for individual AMI events drastically elevates filesystem wait times and lock contention.
- **Memory**: The monolithic architecture of `app.py` enforces high baseline memory usage per worker process.

## 10. Security Concerns
- **Password Hashing Vulnerability**: `db.py` uses unsalted `hashlib.sha256()` for storing web application user passwords. This is heavily vulnerable to rainbow tables.
- **Hardcoded Secret Keys**: The Flask session signature key (`app.secret_key`) is hardcoded directly into `app.py`, allowing session manipulation if the source code is ever leaked.

## 11. Risky Areas
- **`rcm_queue_collector.py` & `rcm_queue_db.py` Threading**: The AMI collector dispatches events asynchronously. Refactoring database logic here risks triggering SQLite deadlocks, causing the collector daemon to crash and permanently dropping real-time call tracking metrics.
- **`app.py` Monolith**: Attempting to modularize the 14,000+ line Flask app via Blueprints runs a high risk of breaking dynamic routing paths, Jinja template context variables, and internal decorator dependency chains.

## 12. Recommended Cleanup Candidates
- **1. Legacy Queue Tables (`rcm_queue_log`, etc.)**
  - *Location*: `db.py`, `rcm_7021.db`.
  - *Reason*: Functionality was moved to `rcm_queue.db`.
  - *Confidence*: High.
  - *Dependencies checked*: Minimal references; occasionally queried in test routes.
  - *Risk if removed*: Low, provided the `db.py` references are scrubbed.
- **2. Extraneous Test & Backup Files**
  - *Location*: `/root/RCM_7021/test_*.py`, `*.bak`.
  - *Reason*: Cluttering production environment.
  - *Confidence*: 100%.
  - *Risk if removed*: None.
- **3. Embedded JavaScript Duplication**
  - *Location*: `templates/queue_form.html`, `templates/paging_form.html`, etc.
  - *Reason*: Extracting identical `<select>` manipulation logic to `static/js/common.js`.
  - *Confidence*: High.
  - *Dependencies checked*: Verified identical function names and DOM element mapping.
  - *Risk if removed*: Low, ensures consistency.
- **4. Dead `per_try` form submission**
  - *Location*: `ringgroup_form.html`.
  - *Reason*: Hidden UI fields submitting unused data to backend.
  - *Confidence*: High.
  - *Risk if removed*: Low.
