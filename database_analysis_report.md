# RCM 7021 Database Analysis Report

## Overview
The RCM 7021 system relies primarily on two SQLite databases: `rcm_7021.db` (the main system database) and `rcm_queue.db` (dedicated to real-time call center and queue management). There are several other databases (`app.db`, `cdr.db`, `main.db`, `rcm.db`) present in the project root, but they appear to be unused or legacy test databases based on the active schemas and code connections.
The active schemas are managed programmatically via SQL execution in `db.py` and `rcm_queue_db.py`.

## Core Tables and Relationships

### 1. Main Database (`rcm_7021.db`)
Created and managed by `db.py` and `rcm_schema.sql`.

#### Users & Access Control
- `users`: Stores user accounts (management and extension users).
  - Primary Key: `id`
  - Foreign Keys: `privilege_id` references `privileges.id`, `extension_ext` references `extensions.ext`.
  - Indexes: `idx_users_username` (Unique), `idx_users_extension_ext` (Unique), `idx_users_user_type`, `idx_management_users_email_unique`.
  - Modules Writing: `db.py` (CRUD), `app.py`.
- `privileges`, `privilege_permissions`, `privilege_scope_settings`, `privilege_scope_items`: RBAC system.
  - Relationships: Foreign keys linking back to `privileges.id` with `ON DELETE CASCADE`.

#### PBX Configuration
- `extensions`: Central extension registry.
  - Primary Key: `ext`.
  - Modules Writing: `db.py`. Read by `dex/rcm_data.py`.
- `trunks`: SIP trunk configuration.
  - Primary Key: `name`.
- `inbound_routes`, `outbound_routes`, `trunk_dods`, `outbound_route_dods`: Call routing rules.
  - Relationships: Many-to-many relationship tables exist (e.g., `trunk_dod_extensions`).
- `rcm_feature_codes`: Configurable dial codes for PBX features.

#### Call Logs and Metrics
- `cdr_records`: Call Detail Records synced from Asterisk.
  - Primary Key: `uniqueid`
  - Indexes: `start_time`, `src`, `dst`, `status`.
  - Modules Writing: `cdr_journey.py`, `db.py`.
- `spy_audit_log`, `extension_spy_permissions`: Audit trail and ACL for call spying.

#### System and Features
- `mail_settings`, `mail_logs`, `mail_queue`: Email functionality and retry queues. Written by `mail_service.py` and `scheduler_service.py`.
- `otp_records`: Password reset records.
- `rcm_firewall_rules`, `rcm_firewall_events`: Network security, written by `firewall_manager.py`.
- `sip_security_settings`, `sip_security_whitelist`, `sip_security_blacklist`, `sip_security_events`: Written by `sip_security_manager.py`.

### 2. Queue Database (`rcm_queue.db`)
Created and managed by `rcm_queue_db.py`.

- `queues`: Queue configurations synced from Asterisk JSON.
  - Primary Key: `queue_id`
  - Indexes: `queue_number` is UNIQUE.
  - Modules Writing: `app.py`, `rcm_queue_db.py`.
- `queue_calls`: Comprehensive lifecycle record of every call entering a queue.
  - Primary Key: `call_id`
  - Indexes: `entry_time`, `queue_id`, `agent`, `status`, `uniqueid`.
  - Modules Writing: Heavily written to by `rcm_queue_collector.py` and `rcm_queue_db.py`.
- `queue_call_positions`: Tracks position-in-queue changes over time.
  - Indexes: `uniqueid`, `queue`, `event`.
- `queue_agents`: Current and historical status of agents logged into queues.
  - Indexes: UNIQUE constraint on `(extension, queue_id)`.
- `queue_agent_events`: Audit trail of all agent events (login, pause, answer, complete).
  - Indexes: `agent`, `queue`, `event_type`, `timestamp`, `uniqueid`.
- `queue_live`: Memory-friendly table tracking real-time waiting/ringing calls for dashboards. Written dynamically by queue collectors.

---

## Analysis Findings

### 1. Duplicate Tables and Legacy Schema
There is a massive duplication of queue-related schemas. The `rcm_7021.db` database contains several tables with the `rcm_` prefix that mirror functionality currently handled by `rcm_queue.db`:
- `rcm_queue_log` (duplicates `queue_agent_events` and general event tracking)
- `rcm_queue_calls` (duplicates `queue_calls`)
- `rcm_agent_sessions` / `rcm_agent_pauses` (duplicates `queue_agents` / `queue_agent_events`)

*Impact*: This creates technical debt. `DATABASE.md` correctly notes these "appear to be legacy or secondary", but they are still being initialized in `db.py` and occasionally written to by `db.py` endpoints, causing scattered logic and redundant data storage.

### 2. Missing Indexes
- `mail_logs`: Lacks indexes on `timestamp` and `sender_email`. This will cause performance degradation when loading email history pages as the log grows.
- `otp_records`: Lacks an index on `email` or `username`, which are used to look up valid password reset tokens during verification.
- `queues`: Filtering by `queue_name` or `strategy` lacks indexes, though queue count is generally small so this is a minor issue.
- `spy_audit_log`: Lacks an index on `caller_ext` (it only has indexes on `created_at` and `target_ext`).

### 3. Inconsistent Naming Conventions
- Table Naming Pluralization: Mixing of pluralization (`users`, `extensions`, `trunks`) vs singular context (`mail_queue`, `spy_audit_log`).
- Prefixes: Unpredictable use of prefixes. Some core tables use `rcm_` (e.g., `rcm_feature_codes`, `rcm_firewall_rules`), while others do not (`extensions`, `trunks`, `users`).
- Foreign Key Naming: Inconsistent foreign key column names. For example, `users.extension_ext` vs `trunk_dods.trunk_id` vs `office_time_rules.class_id`. The database generally uses `<table_singular>_id` but occasionally uses `_ext` or omits the table reference completely.

### 4. Unused or Empty Concepts
- `surveys`, `survey_questions`, `survey_responses`, `survey_ratings`: These exist in the `db.py` schema, but their handling modules (like `survey_agi.py` in `scripts/` or `add_survey_tables.py` in `scratch/`) indicate they might be incomplete or experimental features rather than core functionality actively accessed by the main application stack.
