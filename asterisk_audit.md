# Asterisk & Telephony Audit Report

## 1. AMI Socket Sync Drops Live Events (Truncation/Buffer Loss)
**Severity:** P0 - Critical
**Category:** Asterisk / Integration
**Exact file(s):** `rcm_queue_collector.py`
**Exact function/class/route/component:** `sync_queue_status` and `sync_active_channels_with_asterisk`
**What is happening:** When fetching active queues or channels, the collector reads from the socket into a local `res` buffer until it sees a `Complete` message. It splits and parses this local string but discards any extra events (or partial fragments) that arrived in the same TCP chunk.
**Why it is a problem:** Any live AMI events (e.g., Hangup, Join, AgentConnect) that arrive during the sync execution window are permanently lost or partially truncated.
**How a user can encounter it:** Every 30 seconds when the periodic sync runs, active calls can randomly freeze in the dashboard or lose their talk time due to missed events.
**Expected behavior:** Sync requests should parse events out of the shared, continuous global main loop buffer to guarantee zero event loss.
**Current behavior:** Sync requests use isolated local string buffers and discard trailing bytes.
**Technical root cause:** Bypassing the robust `\r\n\r\n` boundary handling of the main socket read loop in favor of an isolated `while` loop that terminates early on `*Complete`.
**Possible consequences:** Stuck calls in the UI, dropped call recordings, missing CDR connections, inaccurate agent statuses.
**Recommended solution:** Refactor the sync functions to send the command asynchronously and let the main `while True` loop handle the `QueueMember` and `CoreShowChannel` events.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** Yes (AMI integration)
**Whether it affects GUI/UI/UX:** Yes (Ghost calls)
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 2. Queue Hopping Overwrites Original Queue Record
**Severity:** P1 - High
**Category:** Database / Queue logic
**Exact file(s):** `rcm_queue_db.py`
**Exact function/class/route/component:** `db_call_enter`
**What is happening:** The `queue_calls` table enforces `UNIQUE(uniqueid)`. When a call enters a second queue (e.g., due to a timeout in the first), the `ON CONFLICT DO UPDATE` fires. It does NOT update the `queue_id` field but updates `status = ENTERED`.
**Why it is a problem:** The database can only hold one attempt per call. The call retains the `queue_id` of Queue 1, but when answered in Queue 2, the agent from Queue 2 is credited to Queue 1, while Queue 2 loses the call entirely.
**How a user can encounter it:** A caller waits in Sales, times out, falls over to Support, and is answered. The report will show the Support agent answering a call in the Sales queue.
**Expected behavior:** Each queue attempt should generate an independent record.
**Current behavior:** A single row is maintained per Asterisk channel uniqueid, causing subsequent queue attempts to scramble the state.
**Technical root cause:** Using `UNIQUE(uniqueid)` in `queue_calls` instead of a composite key or autoincrement PK to represent individual queue entry attempts.
**Possible consequences:** Completely broken queue SLAs, lost abandoned calls, and corrupted agent metrics.
**Recommended solution:** Remove the `UNIQUE(uniqueid)` constraint. Use a new row for each `ENTERQUEUE` event, perhaps tying them together using `linkedid`.
**Whether it requires database changes:** Yes (Schema/Constraint change)
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 3. Mixed Timezones Corrupt Call Durations
**Severity:** P1 - High
**Category:** Database / Logic
**Exact file(s):** `rcm_queue_db.py`
**Exact function/class/route/component:** `_event_time_string`, `db_call_enter`, `db_call_answer`
**What is happening:** `_event_time_string` hardcodes `Africa/Cairo` time. However, `datetime.now()` uses System Local time, and SQLite's `CURRENT_TIMESTAMP` uses UTC.
**Why it is a problem:** `queue_live.start_time` gets inserted in Cairo time, while `queue_live.last_update` gets UTC. Wait time calculations subtract a Cairo timestamp from a Local/UTC timestamp.
**How a user can encounter it:** A user looking at the live wallboard will see a call that has been waiting for -2 hours, or +3 hours instantly upon arriving.
**Expected behavior:** All database timestamps should be normalized to UTC, or exclusively rely on local system time uniformly.
**Current behavior:** Three different timezones are mixed within duration calculations.
**Technical root cause:** Hardcoding `ZoneInfo("Africa/Cairo")` as a fallback alongside `datetime.now()` and SQL `CURRENT_TIMESTAMP`.
**Possible consequences:** Massive negative or inflated durations, broken SLAs.
**Recommended solution:** Standardize on UTC. Remove `Africa/Cairo` hardcoding. Use `datetime.now(timezone.utc)` globally.
**Whether it requires database changes:** Yes (Data migration/cleanup might be needed)
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 4. Missing Bridge Events Cause Zero Talk Time for Direct Calls
**Severity:** P1 - High
**Category:** CDR / Telephony
**Exact file(s):** `cdr_journey.py`
**Exact function/class/route/component:** `calculate_call_durations`
**What is happening:** If an `ANSWER` event exists but `BRIDGE`/`CONNECT` events are absent (common in direct non-queue extension calls), `talk_intervals` evaluates to empty. The legacy fallback to `billsec` is skipped because `has_answer_event` is True.
**Why it is a problem:** Valid, answered direct calls will report exactly 0 seconds of talk time.
**How a user can encounter it:** User makes an internal extension-to-extension call. In the Call History details, the Talk Time shows 00:00:00 despite the call lasting 10 minutes.
**Expected behavior:** If bridge events are absent, the system should fall back to the CDR `billsec` duration.
**Current behavior:** The presence of an `ANSWER` event actively blocks the `billsec` fallback logic.
**Technical root cause:** `not has_answer_event` is incorrectly used as a strict gate for the `legacy_fallback`.
**Possible consequences:** Incorrect billing, ruined analytics for non-queue traffic.
**Recommended solution:** Only block the legacy fallback if explicit *Bridge* evidence exists, rather than just an *Answer* event.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 5. Invalid Global String Replacement for Queue Pause
**Severity:** P2 - Medium
**Category:** Asterisk CLI
**Exact file(s):** `asterisk_helper.py`
**Exact function/class/route/component:** `run_asterisk_cmd`
**What is happening:** The function applies `.replace(" from ", " queue ")` to incoming CLI commands to map the web pause commands to Asterisk syntax.
**Why it is a problem:** If a PJSIP endpoint name inherently contains the word "from" (e.g., `PJSIP/agent_from_sales`), the replace alters the member interface to `PJSIP/agent_queue_sales`.
**How a user can encounter it:** Admin attempts to pause an agent named `agent_from_us`. The system reports success, but the agent continues receiving calls.
**Expected behavior:** The command should only replace the specific keyword identifying the queue target.
**Current behavior:** A greedy global replace corrupts interface targets.
**Technical root cause:** Use of Python's generic `str.replace` without regex boundaries.
**Possible consequences:** Silent failures when manipulating queue members.
**Recommended solution:** Use a regex `re.sub(r" from (queue.*)$", r" queue \1", cmd)` or parse the web command cleanly upstream.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** Yes
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 6. Missing 'Leave' Event Handling Causes False Abandons & Stuck Calls
**Severity:** P2 - Medium
**Category:** Telephony
**Exact file(s):** `rcm_queue_collector.py`
**Exact function/class/route/component:** `handle_event`
**What is happening:** The collector ignores the AMI `Leave` event. It only tracks `QueueCallerAbandon`, `AgentComplete`, and `Hangup`.
**Why it is a problem:** If a call exits a queue because of a timeout or full queue, it fires `Leave`. Since the call doesn't hang up immediately (it goes to voicemail or IVR), its status remains `ENTERED` or `WAITING` until the final hangup.
**How a user can encounter it:** A caller waits 1 minute, times out, and spends 4 minutes leaving a voicemail. The queue dashboard shows the caller still waiting for 5 minutes. The final report logs 5 minutes of wait time and marks it as `ABANDONED`.
**Expected behavior:** A `Leave` event should immediately mark the queue attempt as `TIMEOUT` or `EXIT` and record the wait time precisely.
**Current behavior:** The queue session stays open and bleeds into the post-queue IVR time.
**Technical root cause:** Omission of `Leave` in the `if evt in (...)` block.
**Possible consequences:** Broken SLAs, false abandon rates, ghost calls on wallboards.
**Recommended solution:** Catch `Leave` events. Determine if it was a timeout or full queue based on Asterisk variables, and finalize the queue leg immediately.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 7. Thread-Safety Bug with Global DEFER_RELOAD
**Severity:** P2 - Medium
**Category:** Architecture
**Exact file(s):** `asterisk_helper.py`
**Exact function/class/route/component:** `DEFER_RELOAD` global variable
**What is happening:** `DEFER_RELOAD` is a module-level global. When the "Apply Changes" route is hit, it temporarily sets `DEFER_RELOAD = False`.
**Why it is a problem:** In a multi-threaded web application, toggling a global boolean affects all concurrent request threads.
**How a user can encounter it:** Admin A clicks "Apply Changes". Concurrently, Admin B is running a bulk import of 200 extensions. Because `DEFER_RELOAD` is globally False, Admin B's request fires 200 synchronous dialplan reloads, freezing the PBX and timing out the request.
**Expected behavior:** Reload defers should be managed per-request or explicitly passed down the function chain.
**Current behavior:** Module-level state mutation breaks thread safety.
**Technical root cause:** Mutating global configuration state within a threaded web handler.
**Possible consequences:** PBX CPU spikes, dropped sip endpoints due to excessive simultaneous reloads, HTTP timeouts.
**Recommended solution:** Pass `defer_reload=True` as a keyword argument to `run_asterisk_cmd` or store the state in Flask's `g` context object.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** Yes (Excessive reloads)
**Whether it affects GUI/UI/UX:** Yes (Timeouts)
**Whether it affects security:** No
**Whether it affects performance:** Yes
**Whether it requires tests:** Yes

---

## 8. Duplicate AMI Headers Lost During Parsing
**Severity:** P2 - Medium
**Category:** Asterisk Integration
**Exact file(s):** `rcm_queue_collector.py`
**Exact function/class/route/component:** `parse_block`
**What is happening:** When parsing AMI event blocks, `headers[k] = v` overwrites previous keys with the same name.
**Why it is a problem:** Asterisk routinely sends multiple `Variable: name=value` headers in a single event. Only the last one survives.
**How a user can encounter it:** Advanced call routing relying on Asterisk channel variables will fail to reflect correctly in external webhooks or CRM popups because the variables are silently dropped.
**Expected behavior:** Duplicate keys should be aggregated into a list.
**Current behavior:** The dictionary clobbers prior keys.
**Technical root cause:** Simple `dict` assignment without checking if the key already exists.
**Possible consequences:** Missing metadata for integrations.
**Recommended solution:** If `k` in `headers`, convert the value to a list and append.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** No
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 9. Race Condition Overwrites queue_live TALKING state with RINGING
**Severity:** P3 - Low
**Category:** Queue / UI
**Exact file(s):** `rcm_queue_db.py`
**Exact function/class/route/component:** `db_call_ring`
**What is happening:** `db_call_ring` unconditionally updates the `queue_live` state to `RINGING`.
**Why it is a problem:** If AMI dispatches out of order and `AgentConnect` is processed before `AgentCalled`, the call upgrades to `TALKING`, and then immediately downgrades to `RINGING`.
**How a user can encounter it:** A supervisor monitors the live queue wallboard and sees an agent flip from "Talking" to "Ringing" while actively on a call.
**Expected behavior:** The state machine should not downgrade from TALKING to RINGING.
**Current behavior:** Unconditional SQL update.
**Technical root cause:** Missing `WHERE state != 'TALKING'` in the SQL statement.
**Possible consequences:** Wallboard confusion.
**Recommended solution:** Add state verification to the `UPDATE` query.
**Whether it requires database changes:** No
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** No
**Whether it affects performance:** No
**Whether it requires tests:** Yes

---

## 10. Unbanning IP leaves Blacklist Entry Active
**Severity:** P3 - Low
**Category:** Security / State Consistency
**Exact file(s):** `sip_security_manager.py`
**Exact function/class/route/component:** `unban_ip`
**What is happening:** `unban_ip` successfully runs the Fail2Ban unban command and logs an event, but it skips updating the `sip_security_blacklist` table.
**Why it is a problem:** The IP remains visually "active" in the blacklist UI. The background reconciliation loop will eventually spot it and falsely log an `Automatic Expiry`.
**How a user can encounter it:** Admin unbans an IP manually. The IP works, but the GUI still shows it as permanently banned.
**Expected behavior:** `unban_ip` should update the DB status to `removed` and `removal_method = 'manual'`.
**Current behavior:** The DB state diverges from the Fail2Ban state.
**Technical root cause:** Missing SQL `UPDATE` statement in the `unban_ip` function compared to the `remove_blacklist` function.
**Possible consequences:** UI inconsistency and misleading security logs.
**Recommended solution:** Refactor `unban_ip` to call `remove_blacklist` or duplicate the `UPDATE` logic.
**Whether it requires database changes:** Yes (Data state only)
**Whether it affects Asterisk:** No
**Whether it affects GUI/UI/UX:** Yes
**Whether it affects security:** Yes
**Whether it affects performance:** No
**Whether it requires tests:** Yes
