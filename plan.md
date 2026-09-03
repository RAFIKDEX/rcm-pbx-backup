# CON Agent / Supervisor Implementation Plan

## Phase 1: Database & Configuration
1. Analyze how Queues are stored (JSON vs DB). They seem to be in `/etc/asterisk/rcm_queues.json`.
2. Analyze how Agent states and Breaks are currently tracked (`rcm_agent_sessions`, `rcm_agent_pauses`).
3. Add `Agent Settings` to Queue configuration:
   - `supervisors` (List of user IDs).
   - `breaks` (List of {id, name, duration_minutes}).
   - `script` (Text content).
4. Integrate this into the UI for Queue edit/add (`templates/queue_form.html`).

## Phase 2: Backend APIs (CON Agent)
1. Determine the logged-in user's extension.
2. List all queues this extension is an agent for.
3. Calculate current state (from AMI or `rcm_agent_sessions` / `rcm_queue_log`).
4. Endpoint to start/stop Break (Pause/Unpause across ALL queues).
5. PBX Control endpoints (Hangup, Hold, Mute, Transfer) using AMI (`asterisk_helper.py`).

## Phase 3: Backend APIs (CON Supervisor)
1. Determine which queues the logged-in user is a supervisor for.
2. Get all agents in those queues.
3. Get live states for these agents (Idle, Ringing, In Call, Break, Offline) + Caller Info.
4. PBX Control endpoints for Monitor (Listen, Whisper, Barge) if permissions allow.

## Phase 4: Frontend UI (CON Agent)
1. Add sidebar link if user is an agent.
2. Create `/con/agent` route and `templates/con_agent.html`.
3. Implement real-time updates (fetch/SSE) for state, caller, queue script.
4. Add Break selection modal.

## Phase 5: Frontend UI (CON Supervisor)
1. Add sidebar link if user is a supervisor.
2. Create `/con/supervisor` route and `templates/con_supervisor.html`.
3. Table with live updating agents, statuses, durations, and caller info.
4. Action buttons.

## Phase 6: Testing & Audit
1. End-to-end test.
2. Generate final report.