# Architecture and Database Audit

## 1. Missing File Locking causing Race Conditions and Config Corruption
- **Severity:** P0 - Critical
- **Category:** Architecture / Concurrency
- **Exact file(s):** `/root/RCM_7021/asterisk_helper.py`
- **Exact function/class/route/component:** `update_section()`
- **What is happening:** The application reads entire Asterisk `.conf` files into memory, parses and modifies lines, and writes them back without any mutual exclusion locks (e.g. `fcntl.flock` or a Python `threading.Lock`).
- **Why it is a problem:** If two users concurrently add, update, or delete extensions/trunks, or if a bulk import is running while a user is modifying an object, the file writes will interleave or overwrite each other. The thread that writes last will clobber the other's changes, leading to silently dropped Asterisk configurations and a corrupted file state.
- **How a user can encounter it:** Two administrators editing endpoints concurrently, or triggering a bulk update while normal system usage happens.
- **Expected behavior:** Concurrent file I/O operations must be strictly synchronized using a file-based lock before opening the file for reading and writing.
- **Current behavior:** File reads and writes are fully unguarded.
- **Technical root cause:** Unsynchronized shared mutable state (file system) within a multi-threaded Flask environment.
- **Possible consequences:** Complete loss of newly configured PBX extensions or trunks. Asterisk failure to parse broken config files due to missing section headers or interleaved lines.
- **Recommended solution:** Wrap the `with open(filepath, 'r')` and `with open(filepath, 'w')` logic with a file locking mechanism (e.g., `fcntl.flock(f.fileno(), fcntl.LOCK_EX)`) to enforce atomic read-modify-write cycles per file.
- **Whether it requires database changes:** No
- **Whether it affects Asterisk:** Yes
- **Whether it affects GUI/UI/UX:** No
- **Whether it affects security:** No
- **Whether it affects performance:** No
- **Whether it requires tests:** Yes

## 2. Partial Writes Between SQLite and File System 
- **Severity:** P1 - High
- **Category:** Architecture
- **Exact file(s):** `/root/RCM_7021/app.py`, `/root/RCM_7021/db.py`, `/root/RCM_7021/asterisk_helper.py`
- **Exact function/class/route/component:** `/extensions/add` (route) and `write_extension_configs()`
- **What is happening:** The application sequentially commits changes to the SQLite database (`db.add_extension`), and *then* attempts to write the corresponding Asterisk configuration fragments into multiple `.conf` files (`pjsip.gui.endpoint.conf`, `pjsip.gui.auth.conf`, `pjsip.gui.aor.conf`, etc.).
- **Why it is a problem:** If writing to `pjsip.gui.endpoint.conf` succeeds but writing to `pjsip.gui.auth.conf` fails (due to a crash, `write` timeout, disk space error, or permissions issue), the system is left in a "split-brain" state. The DB successfully committed, making the extension appear active in the UI, but Asterisk is missing the required configuration chunks to allow the device to register. There is no rollback.
- **How a user can encounter it:** An edge-case failure on the host OS during configuration generation.
- **Expected behavior:** Either the DB changes and File System changes succeed atomically, or the configuration files are dynamically derived entirely from the DB on reload.
- **Current behavior:** DB transaction completes, followed by sequentially unguarded file I/O operations.
- **Technical root cause:** Mixed persistent stores without two-phase commit or transactional atomicity.
- **Possible consequences:** Orphaned UI extensions that do not function in the PBX and cannot be easily fixed without manual DB/File surgery.
- **Recommended solution:** The application should either build complete `.conf` files exclusively by querying the DB on a "Deploy/Reload" action instead of incrementally editing them on each HTTP POST, or write to a staging file system and move files atomically.
- **Whether it requires database changes:** No
- **Whether it affects Asterisk:** Yes
- **Whether it affects GUI/UI/UX:** No
- **Whether it affects security:** No
- **Whether it affects performance:** No
- **Whether it requires tests:** Yes

## 3. Critical N+1 Query and Connection Exhaustion in Queue Sync
- **Severity:** P1 - High
- **Category:** Database / Performance
- **Exact file(s):** `/root/RCM_7021/db.py` and `/root/RCM_7021/rcm_queue_db.py`
- **Exact function/class/route/component:** `save_queues()` (in `db.py`) and `db_sync_queue()` (in `rcm_queue_db.py`)
- **What is happening:** `save_queues()` loops over a list of all queues in the system. For every queue in the loop, it invokes `db_sync_queue()`. Inside `db_sync_queue()`, a brand new database connection is instantiated, a cursor is spawned, an `INSERT ... ON CONFLICT DO UPDATE` statement is executed, and then the connection is committed and closed.
- **Why it is a problem:** Executing database connection lifecycle management (connect, commit, close) inside a loop (O(N) times) generates enormous I/O bottleneck and CPU overhead. This is a classic N+1 query issue exacerbated by connection churn.
- **How a user can encounter it:** When saving a large number of call queues in the UI (e.g. bulk update). The application may lock up, hang, or hit gateway timeouts.
- **Expected behavior:** The application should use a single connection, initiate a transaction, use `executemany` (or iterate with a single cursor) to push all queue updates, and commit exactly once at the end.
- **Current behavior:** Re-connects and commits for each individual queue.
- **Technical root cause:** Misplaced database connection boundary placed within an iterator.
- **Possible consequences:** Application timeouts, lock contention on SQLite (`database is locked`), and thread exhaustion in Flask.
- **Recommended solution:** Refactor `db_sync_queue()` to accept a list of dictionary/tuple updates and process them inside one single `conn = get_db_connection()` block with a single `conn.commit()`.
- **Whether it requires database changes:** No (Only Python query logic adjustment)
- **Whether it affects Asterisk:** No
- **Whether it affects GUI/UI/UX:** Yes (causes sluggish UI saving operations)
- **Whether it affects security:** No
- **Whether it affects performance:** Yes
- **Whether it requires tests:** Yes

## 4. Schema Inconsistency and Overlapping Queue Tables
- **Severity:** P2 - Medium
- **Category:** Database Schema
- **Exact file(s):** `rcm_schema.sql` and `/root/RCM_7021/db.py`
- **Exact function/class/route/component:** `rcm_queue_calls` Table Initialization
- **What is happening:** `rcm_schema.sql` defines the `rcm_queue_calls` table with `callid TEXT PRIMARY KEY`. However, `db.py` initializes the exact same table with `id INTEGER PRIMARY KEY AUTOINCREMENT, callid TEXT UNIQUE`. Additionally, multiple duplicate queue tracking tables exist between `rcm_7021.db` and `rcm_queue.db`.
- **Why it is a problem:** The schema script and the application initialization logic are out of sync. This results in inconsistent database definitions depending on how the application was deployed, causing unpredictable SQL constraint errors. The overlapping databases also create split sources of truth.
- **How a user can encounter it:** During fresh application installs vs. manual schema migrations, or when queries assume `id` exists but the table was built via `rcm_schema.sql`.
- **Expected behavior:** The SQL schema definition file should perfectly mirror the inline `init_db()` commands, and data should reside in a single canonical place to avoid sync issues.
- **Current behavior:** Conflicting primary keys for the exact same table.
- **Technical root cause:** Duplicate, unmanaged definitions of DB schemas across multiple files.
- **Possible consequences:** SQLite integrity constraint failures and application crashes when querying `rcm_queue_calls`.
- **Recommended solution:** Reconcile `db.py` table creation schema for `rcm_queue_calls` with `rcm_schema.sql` so both match perfectly. Unify the queue configuration state to reside entirely in `rcm_queue.db` or `rcm_7021.db`.
- **Whether it requires database changes:** Yes
- **Whether it affects Asterisk:** No
- **Whether it affects GUI/UI/UX:** No
- **Whether it affects security:** No
- **Whether it affects performance:** No
- **Whether it requires tests:** Yes

## 5. Missing Foreign Key Indexes
- **Severity:** P2 - Medium
- **Category:** Database / Performance
- **Exact file(s):** `rcm_schema.sql` and `/root/RCM_7021/db.py`
- **Exact function/class/route/component:** `office_time_rules`, `privilege_permissions`, `survey_questions`, `survey_ratings`
- **What is happening:** Tables with explicit `FOREIGN KEY` constraints are missing corresponding `CREATE INDEX` declarations for the child columns (e.g. `office_time_rules.class_id`).
- **Why it is a problem:** In SQLite, deleting or updating a parent record forces a full table scan on the child table to enforce the cascading foreign key constraint. This causes significant query latency and extended read-locking on the entire child table.
- **How a user can encounter it:** Deleting a heavily used office time class or survey could hang or timeout if the child tables grow large.
- **Expected behavior:** Every column involved in a foreign key constraint lookup should be explicitly indexed.
- **Current behavior:** The indexes are completely missing.
- **Technical root cause:** Omission during schema creation.
- **Possible consequences:** Progressively slower API responses on DELETE operations, `database is locked` errors due to prolonged blocking.
- **Recommended solution:** Add `CREATE INDEX idx_office_time_rules_class_id ON office_time_rules(class_id);` (and similarly for other child tables) to both `db.py` and `rcm_schema.sql`.
- **Whether it requires database changes:** Yes
- **Whether it affects Asterisk:** No
- **Whether it affects GUI/UI/UX:** Yes (Performance during deletion)
- **Whether it affects security:** No
- **Whether it affects performance:** Yes
- **Whether it requires tests:** No

## 6. Missing Foreign Key Constraints on Surveys
- **Severity:** P3 - Low
- **Category:** Database Schema
- **Exact file(s):** `/root/RCM_7021/db.py`
- **Exact function/class/route/component:** `survey_responses` Table Schema
- **What is happening:** The `survey_responses` table defines a `survey_id INTEGER` column but omits the actual `FOREIGN KEY(survey_id) REFERENCES surveys(id)` constraint.
- **Why it is a problem:** If a survey is deleted, the corresponding responses are left behind as orphaned rows, bloating the database and causing errors if an inner joined query executes against the main surveys table.
- **How a user can encounter it:** Deleting an old survey leaves behind historical responses that could break reporting dashboards.
- **Expected behavior:** Referential integrity should be strictly enforced via Foreign Key constraints.
- **Current behavior:** The relationship column exists but lacks the explicit SQLite constraint.
- **Technical root cause:** Omitted SQL syntax during table definition.
- **Possible consequences:** Orphaned records in the database.
- **Recommended solution:** Add `FOREIGN KEY(survey_id) REFERENCES surveys(id) ON DELETE CASCADE` to the `survey_responses` table definition.
- **Whether it requires database changes:** Yes
- **Whether it affects Asterisk:** No
- **Whether it affects GUI/UI/UX:** No
- **Whether it affects security:** No
- **Whether it affects performance:** No
- **Whether it requires tests:** Yes