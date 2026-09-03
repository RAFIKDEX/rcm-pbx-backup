# Queue Dialplan Generation and Settings Fixes

We have resolved the issues in the Asterisk Queue dialplan generation, static/dynamic queue members configuration, and added complete configuration options to the user interface.

## 1. Summary of Changes

### A. Dialplan Generation Fix
- **Issue:** The queue call previously entered the queue with a hardcoded `0` timeout: `Queue(6500,tT,,,0)`. In Asterisk, passing `0` as the fifth argument (absolute timeout) often causes the application to immediately exit and hang up instead of waiting indefinitely.
- **Fix:** Modified [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py#L1408-L1420) to check `max_wait_time`. If the timeout is `0` or empty, the argument is completely omitted: `Queue(6500,tT)`. Otherwise, the value is correctly passed: `Queue(6500,tT,,,{max_wait})`.

### B. Static Queue Member Configuration (Pause Status)
- **Issue:** Static queue members were written as `member => PJSIP/{agent},,,,yes` when disabled (paused). With 4 commas, `yes` was assigned to the 5th parameter (`ringinuse`), rather than the 7th parameter (`paused`).
- **Fix:** Corrected the format to `member => PJSIP/{agent},,,,,,yes` (6 commas) in [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py#L1393-L1398) to properly map the `paused` status in `queues.conf`.

### C. Added Configurable Settings in UI & DB
We added fields for **Max Wait Time**, **Join Empty**, and **Leave When Empty** to the UI form and saved them to the backend:
- Modified [queue_form.html](file:///root/RCM_7021/templates/queue_form.html#L83-L113) to include:
  - **Max Wait Time (seconds):** Number input mapping to `max_wait_time` (0 for unlimited).
  - **Join Empty:** Dropdown mapping to `dial_in_empty_queue` with options `yes`, `no`, `strict`, `loose`.
  - **Leave When Empty:** Dropdown mapping to `leave_when_empty` with options `yes`, `no`, `strict`, `loose`.
- Modified [app.py](file:///root/RCM_7021/app.py#L2522-L2569) in both the `queue_add` and `queue_edit` routes to parse and persist these three new fields in `rcm_queues.json`.

---

## 2. Test Verification Matrix

We performed runtime Asterisk CLI originates to verify all scenarios:

| Test Case | Setup | Expected Behavior | Actual Behavior / CLI Output | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Extension -> Queue** | Dial `6500` from `PJSIP/5001` or `PJSIP/4321` | Call successfully enters the queue and plays MOH. | Call entered `Queue(6500,tT)` playing MOH. | **PASS** |
| **One Available Agent** | `5001` is `Not in use`; others `Unavailable`. | Rings `PJSIP/5001`, skips unavailable ones. | Rings `PJSIP/5001`. Status shows `5001 (Ringing)`, others skipped. | **PASS** |
| **All Agents Unavailable** | `5001` is `paused`, others `Unavailable`. `joinempty=strict`. | Call should not enter queue and immediately fail over. | Caller immediately exits Queue app and executes `Hangup()`. | **PASS** |
| **Queue Timeout** | `max_wait_time` set to `10`. All agents busy/unavailable. | Call waits for 10 seconds, then exits and hangs up. | Call entered `Queue(6500,tT,,,10)` and hung up after 10 seconds. | **PASS** |
| **Queue Failover** | Queue exits (timeout or empty). | Executes next dialplan priority (failover destination). | Call correctly executed the failover destination line `Hangup()`. | **PASS** |
| **Dynamic Agents** | Dial `*716500` to login, `*726500` to logout. | Dynamically adds/removes the agent from the queue. | `AddQueueMember` and `RemoveQueueMember` successfully updated membership. | **PASS** |
