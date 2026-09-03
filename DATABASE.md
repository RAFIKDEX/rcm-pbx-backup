# RCM Database Reference

RCM uses two SQLite databases in the project root plus several JSON-backed config files under `/etc/asterisk`.

## Main SQLite Database

Path: `/root/RCM_7021/rcm_7021.db`

Schema owner: `db.py`

| Table | Purpose |
| --- | --- |
| `users` | Web login users with username, SHA-256 password hash, role, and email. Seeded with admin/supervisor/agent users. |
| `extensions` | PBX extension configuration: enabled state, caller ID, PJSIP secret, max contacts, voicemail, recording mode, NAT/media flags, follow-me JSON, mobile, email, call-spy permission. |
| `trunks` | PJSIP trunk configuration: trunk type, registration mode, server/auth fields, context, codecs, allowed IP, caller ID, qualify behavior. |
| `office_time_classes` | Named office-time profiles used by inbound-route time conditions. |
| `office_time_rules` | Day/time windows for `office_time_classes`; references `office_time_classes.id`. |
| `rcm_queue_log` | Raw/processed call-center queue log table. Appears to be legacy or secondary to `rcm_queue.db`. |
| `rcm_queue_calls` | Main-database queue call analytics table. Appears to be legacy or secondary to `rcm_queue.db`. |
| `rcm_agent_sessions` | Agent session records for call-center analytics. Appears to be legacy or secondary to `rcm_queue.db`. |
| `rcm_agent_pauses` | Agent pause records. Appears to be legacy or secondary to `rcm_queue.db`. |
| `rcm_queue_alerts` | Queue alert log with resolved flag. |
| `rcm_callback_requests` | Callback requests for queues. |
| `rcm_caller_lists` | Caller blacklist/whitelist entries. |
| `rcm_feature_codes` | Editable feature-code registry with feature name/category/code/enabled/permissions/destination/timeout. |
| `mail_settings` | Singleton SMTP/mail settings row, including alert/report settings and encrypted password. |
| `mail_logs` | Sent/failed email delivery log. |
| `otp_records` | Password reset OTP records, hashed OTPs, expiry, attempts, verification state. |
| `mail_queue` | Retry queue for failed non-test emails. |
| `inbound_routes` | Inbound route records with `data` JSON payload. Sync helpers also use `/etc/asterisk/rcm_inbound_routes.json`. |
| `outbound_routes` | Outbound route records with `data` JSON payload. Sync helpers also use `/etc/asterisk/rcm_outbound/routes.json`. |
| `cdr_records` | Synced CDR data used by paginated CDR API/views. The `recording` field is resolved against valid MixMonitor WAV files during CDR sync, including direct, queue, IVR, ring-group, paging, and inbound filename formats. |

## Queue SQLite Database

Path: `/root/RCM_7021/rcm_queue.db`

Schema owner: `rcm_queue_db.py`

| Table | Purpose |
| --- | --- |
| `queues` | Queue metadata synchronized from `/etc/asterisk/rcm_queues.json`: number, name, strategy, limits, timeout, retry, service level. |
| `queue_calls` | Queue call lifecycle records: uniqueid, linkedid, caller, queue, agent, entry/answer/hangup times, status, wait/talk/hold time, source trunk, positions. |
| `queue_call_positions` | Position history for queue calls by uniqueid, queue, event, timestamp. |
| `queue_agents` | Queue agent membership/state: extension, name, queue, static/dynamic type, current status, login/logout times. |
| `queue_agent_events` | Event history for agents and calls: login/logout, pause/unpause, ring, answer, hangup, complete, abandon, hold events. |
| `queue_live` | Current waiting/ringing queue calls for live dashboard state. |

## Important Relationships

- `office_time_rules.class_id` references `office_time_classes.id`.
- `extensions.ext` is the central extension identifier used by PJSIP config, queue agents, ring groups, pickup groups, paging, feature-code permissions, and route permissions.
- `trunks.name` is used by inbound route trunk filters and outbound route trunk lists.
- `rcm_feature_codes.feature_name` maps named PBX features to editable dial codes.
- `queue_calls.queue_id` maps to `queues.queue_number`.
- `queue_agents.queue_id` maps to `queues.queue_number`.
- `queue_agent_events.queue` maps to `queues.queue_number`.
- `queue_agent_events.uniqueid` maps to `queue_calls.uniqueid`.
- `queue_call_positions.uniqueid` maps to `queue_calls.uniqueid`.
- `cdr_records.uniqueid` maps to Asterisk CDR unique IDs and may be matched to recording filenames.

## JSON-Backed Data Stores

| File | Helper | Purpose |
| --- | --- | --- |
| `/etc/asterisk/rcm_ivrs.json` | `get_ivrs`, `save_ivrs` | IVR definitions and DTMF mappings. |
| `/etc/asterisk/rcm_ring_groups.json` | `get_ring_groups`, `save_ring_groups` | Ring group definitions. |
| `/etc/asterisk/rcm_paging_intercom.json` | `get_paging`, `save_paging` | Paging/intercom groups. |
| `/etc/asterisk/rcm_queues.json` | `get_queues`, `save_queues` | Queue definitions. |
| `/etc/asterisk/rcm_speed_dials.json` | `get_speed_dials`, `save_speed_dials` | Speed dial entries. |
| `/etc/asterisk/rcm_pickup_groups.json` | `get_pickup_groups`, `save_pickup_groups` | Pickup group definitions. |
| `/etc/asterisk/rcm_announcements.json` | `get_announcements`, `save_announcements` | Announcement definitions. |
| `/etc/asterisk/rcm_media_center.json` | `get_media_center_db`, `save_media_center_db` | Prompts and MOH class metadata. |
| `/etc/asterisk/rcm_time_settings.json` | `get_time_settings`, `save_time_settings` | Time settings form data. |
| `/etc/asterisk/rcm_network_settings.json` | `get_network_settings`, `save_network_settings` | Network settings form data. |
| `/etc/asterisk/rcm_outbound/routes.json` | `get_outbound_routes`, `save_outbound_routes` | Outbound routes. |
| `/etc/asterisk/rcm_office_times.json` | office time helpers | Office-time profile data. |
| `/etc/asterisk/rcm_holidays.json` | holiday helpers | Holiday profile data. |
| `/etc/asterisk/rcm_inbound_routes.json` | inbound route helpers | Inbound routes and conditions. |

## Notes And Risks

- The main DB has queue-related tables that overlap with `rcm_queue.db`. Current live/stat views primarily use `rcm_queue_db.py`.
- Migrations are implemented through guarded `ALTER TABLE` statements rather than a formal migration tool.
- Some JSON files and SQLite tables represent similar route data; use existing helpers for the specific feature before adding new storage.
