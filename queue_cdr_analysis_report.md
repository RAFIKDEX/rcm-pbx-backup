# Queue & CDR Subsystem Analysis Report

## 1. System Mental Model & Architecture
The subsystem handles telephony call data tracking, queue management, and reporting through a loosely coupled architecture of four main components:
- **`rcm_queue_collector.py` (Realtime Ingestion)**: A persistent background daemon that connects to the Asterisk AMI (port 5038). It parses raw PBX realtime events and dispatches them to database handler functions. It also runs periodic reconciliation checks (e.g., active channel syncs).
- **`rcm_queue_db.py` (Persistence Layer)**: Contains the data access objects for `rcm_queue.db`. It maps PBX lifecycle events (Enter, Ring, Answer, Hold, Hangup) into structured state tracking tables (`queue_calls`, `queue_live`, `queue_agent_events`).
- **`scheduler_service.py` (Background Worker)**: A polling daemon that handles asynchronous background jobs. It parses raw filesystem logs (`Master.csv` and `queue_log`), processes pending emails, and generates periodic (Daily/Weekly/Monthly) CDR metrics. 
- **`cdr_journey.py` (Presentation Aggregation)**: A read-heavy module responsible for dynamically reconstructing the timeline of a call. Instead of trusting pre-computed database fields, it analyzes discrete log streams to generate accurate intervals for the UI payload.

## 2. Event Collection & Data Flow Trace
1. **Initiation**: A caller enters a queue, triggering an AMI `QueueCallerJoin` or `Join` event.
2. **Ingestion**: `rcm_queue_collector.py` reads the TCP socket chunk, parses the headers, and triggers `handle_event()`.
3. **Storage**: The collector invokes `rcm_queue_db.db_call_enter()`, which:
   - Inserts a persistent record into `queue_calls`.
   - Adds the call to the realtime wallboard table `queue_live`.
   - Records an `ENTERQUEUE` marker in `queue_agent_events`.
   - Logs the queue position into `queue_call_positions`.
4. **Progression**: As Asterisk fires `AgentCalled`, `AgentConnect`, and `Hold`/`Unhold` events, the collector pushes updates, mapping statuses (e.g., ringing to answered) and computing ongoing wait times.
5. **Completion**: A `Hangup` or `AgentComplete` triggers the finalizer (`db_call_hangup`), which computes final `wait_time`, `talk_time`, and removes the call from `queue_live`.
6. **Reporting**: Background jobs in `scheduler_service` analyze CDRs independently, while `cdr_journey` provides a detailed reconstruction of the event streams upon user request.

## 3. Database Performance & Risk Patterns
The system exhibits several critical database anti-patterns that degrade scale and performance:
- **Dangerous Transaction Handling**: Almost every method in `rcm_queue_db.py` (e.g., `db_call_ring`, `db_call_answer`) instantiates a new SQLite connection (`get_db_connection()`), executes a single query, commits, and closes the connection. This constant connection churn causes massive filesystem I/O and lock contention under high PBX load.
- **N+1 Query Patterns**:
  - `rcm_queue_db.py:db_reindex_queue_positions`: It queries a queue's active calls, and then loops over the result array to execute an individual `UPDATE queue_live` per row instead of batching.
  - `scheduler_service.py:monitor_missed_calls`: In a loop over extensions, it queries the `mail_logs` table individually.
  - `scheduler_service.py:monitor_missed_calls`: In the `queue_log` parser block, it calls `get_caller_for_callid(callid)` for missed calls. This function opens and closes a new DB connection for *each individual call ID* inside the loop.
- **Concurrent Modification Risks**: While `rcm_queue_db.py` declares `_QUEUE_LOG_SYNC_LOCK = threading.RLock()`, it is only used deep inside sync mechanisms (e.g., `reconcile_with_asterisk_state`). The rapid-fire realtime handler functions bypass this lock entirely, leaving `queue_calls` vulnerable to SQLite `database is locked` deadlocks.

## 4. Logic Conflicts & Discrepancies
The most severe issue is the calculation of call duration metrics. There are conflicting sources of truth:
- **Wait Time / SLA**: 
  - `rcm_queue_db.py` subtracts the `entry_dt` from the `ans_dt` string. 
  - `cdr_journey.py` searches through a prioritized list of evidence (CDR events, queue CONNECT events) and correctly ignores helper applications (e.g., IVRs, Playbacks) to find the *true human answer time*.
- **Talk Time & Hold Time**:
  - **`rcm_queue_db.py` (Naive)**: Computes `talk_time = total_duration - hold_time`. The `hold_time` calculation only fetches the timestamp of the *most recent* `HOLD` event. If a call is placed on hold multiple times, the database irreparably corrupts the accumulated metrics.
  - **`cdr_journey.py` (Exact)**: Implements complex interval algebra (`_merge_duration_intervals`, `_subtract_duration_intervals`). It aggregates overlapping `BRIDGE` sessions and subtracts exact normalized `HOLD` intervals. The DB and UI metrics will clash for any complex call.

## 5. Legacy Code & Technical Debt
- **Commented/Abandoned Logic**: `rcm_queue_collector.py` contains comments explicitly noting disabled functionality: `# Removed BridgeLeave handling as it's not a true hangup`.
- **Database Migrations Anti-pattern**: `init_queue_db()` relies on a sequence of naked `try/except sqlite3.OperationalError` blocks attempting to `ALTER TABLE` fields.
- **Legacy Fallbacks**: `rcm_queue_db.py` contains hardcoded safety limits (`if talk_time > 43200: talk_time = 0`) to patch over clock sync drifts. `cdr_journey.py` implements a `legacy_fallback` explicitly to calculate un-bridged talk times using raw `billsec` for older CDR data structures.
- **Simultaneous Log Parsing**: `scheduler_service.py` directly parses `/var/log/asterisk/cdr-csv/Master.csv` and `/var/log/asterisk/queue_log` simultaneously while also relying on SQL data (`db.sync_cdr_records()`), leading to brittle duplicate checks and out-of-sync logic.