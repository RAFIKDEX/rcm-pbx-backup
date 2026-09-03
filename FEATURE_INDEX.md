# RCM Feature Index

This file maps existing product features to implementation files, storage, templates, and Asterisk config where applicable.

## Core Platform

| Feature | Implemented In | Storage | Templates | Asterisk/External Files |
| --- | --- | --- | --- | --- |
| Authentication | `app.py`, `db.py` | `users`, `otp_records` | `login.html`, forgot-password templates | None |
| Dashboard | `app.py`, `asterisk_helper.py`, `db.py` | main DB reads | `dashboard.html` | Asterisk CLI status |
| Pending changes | `app.py` | `rcm_pending_changes.json` | `base.html` | Apply reload commands |
| System info | `app.py`, `asterisk_helper.py` | None | `system_info.html` | `/proc`, Asterisk CLI |
| Security/admin password | `app.py`, `db.py` | `users` | `security.html` | iptables command output |
| Configuration editor | `app.py`, `asterisk_helper.py` | Direct file edits | `configuration.html` | selected `/etc/asterisk` files |

## PBX Objects

| Feature | Implemented In | Storage | Templates | Asterisk/External Files |
| --- | --- | --- | --- | --- |
| Extensions | `app.py`, `db.py`, `asterisk_helper.py` | `extensions` | `extensions.html`, `extension_form.html`, bulk templates | PJSIP endpoint/auth/AOR, `extensions_gui.conf`, `context_exten.conf`, `voicemail.conf`, `followme.conf` |
| Trunks | `app.py`, `db.py`, `asterisk_helper.py` | `trunks` | `trunks.html`, `trunk_form.html` | PJSIP endpoint/auth/AOR/identify/reg files |
| Outbound routes | `app.py`, `db.py`, `asterisk_helper.py` | `outbound_routes`, `/etc/asterisk/rcm_outbound/routes.json` | `call_routes.html`, `outbound_route_form.html` | `context_exten.conf`, external `/usr/local/bin/rcm_gen_outbound_routes.sh` |
| Inbound routes | `app.py`, `db.py`, `asterisk_helper.py` | `inbound_routes`, `/etc/asterisk/rcm_inbound_routes.json` | `inbound_routes_list.html`, `inbound_route_form.html` | `extensions.inbound.gui.conf`, `extensions.context.conf` include |
| IVRs | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_ivrs.json` | `ivr_list.html`, `ivr_form.html` | `extensions.ivr.gui.conf` |
| Ring groups | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_ring_groups.json` | `ringgroup_list.html`, `ringgroup_form.html` | `extensions.ringgroup.gui.conf` |
| Queues | `app.py`, `db.py`, `asterisk_helper.py`, `rcm_queue_db.py` | `/etc/asterisk/rcm_queues.json`, `rcm_queue.db.queues` | `queue_list.html`, `queue_form.html` | `queues.conf`, `extensions.queue.gui.conf` |
| Paging/intercom | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_paging_intercom.json` | `paging_list.html`, `paging_form.html` | `extensions.paging.gui.conf` |
| Speed dials | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_speed_dials.json` | `speed_dial_list.html`, `speed_dial_form.html` | `extensions.speed_dial.gui.conf` |
| Pickup groups | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_pickup_groups.json` | `pickup_groups_list.html`, `pickup_groups_form.html` | `extensions.pickup_groups.gui.conf` |
| Announcements | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_announcements.json` | `announcement_list.html`, `announcement_form.html` | `extensions.announcement.gui.conf` |
| Feature codes | `app.py`, `db.py`, `asterisk_helper.py` | `rcm_feature_codes` | `feature_codes.html` | `extensions.feature_codes.gui.conf`, `features.conf`, queue feature-code generation |

## Media And Audio

| Feature | Implemented In | Storage | Templates | Asterisk/External Files |
| --- | --- | --- | --- | --- |
| Prompt library | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_media_center.json` | `media_center.html` | Asterisk sounds directories; prompt paths resolved by ID |
| Music on hold classes | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_media_center.json` | `media_center.html`, `moh_tracks.html` | `musiconhold.conf`, MOH folders |
| Media proxy/playback | `app.py` | filesystem | media templates | sound/MOH files |

## Call Center And Reporting

| Feature | Implemented In | Storage | Templates | Asterisk/External Files |
| --- | --- | --- | --- | --- |
| Live active calls | `app.py`, `asterisk_helper.py` | None | `active_calls.html` | `core show channels concise` |
| Queue AMI collector | `rcm_queue_collector.py`, `rcm_queue_db.py` | `rcm_queue.db` | None | AMI `127.0.0.1:5038` |
| Queue live dashboard | `app.py`, `rcm_queue_db.py` | `rcm_queue.db` | `queue_live.html` | AMI-derived state |
| Queue stats | `app.py`, `rcm_queue_db.py` | `rcm_queue.db`, queue log offset | `queue_stats.html` | `/var/log/asterisk/queue_log` |
| Queue detail/call timeline | `app.py`, `rcm_queue_db.py` | `rcm_queue.db` | `queue_detail.html` | AMI/queue log data |
| CDR page/API | `app.py`, `db.py` | `cdr_records`, Asterisk CSV | `cdr.html` | `/var/log/asterisk/cdr-csv/Master.csv`, monitor recordings |
| Call recordings | `app.py` | filesystem | `call_records.html` | `/var/spool/asterisk/monitor` |
| Reports | `app.py`, `scheduler_service.py` | CDR CSV, `mail_logs` | `reports.html` | CDR CSV, XLSX in `/tmp` |

## System Settings And Maintenance

| Feature | Implemented In | Storage | Templates | Asterisk/External Files |
| --- | --- | --- | --- | --- |
| Mail settings | `app.py`, `db.py`, `mail_service.py` | `mail_settings`, `mail_logs`, `mail_queue` | `mail_settings.html` | SMTP server |
| Missed-call alerts | `scheduler_service.py`, `mail_service.py`, `db.py` | `mail_settings`, `mail_logs` | Mail settings UI | CDR CSV, queue log |
| Scheduled CDR reports | `scheduler_service.py`, `mail_service.py` | `mail_settings`, `mail_logs` | Mail settings UI | CDR CSV, recordings |
| Time settings | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_time_settings.json` | `time_settings.html` | System time/timezone commands |
| Network settings | `app.py`, `db.py`, `asterisk_helper.py` | `/etc/asterisk/rcm_network_settings.json` | `network_settings.html` | System network commands/files |
| Time conditions | `app.py`, `db.py`, `asterisk_helper.py` | office time/holiday JSON and tables | `time_conditions_list.html`, `office_time_form.html`, `holiday_form.html` | Inbound route dialplan |
| Network troubleshooting | `app.py` | temporary capture/status files | `network_troubleshooting.html` | ping/traceroute/nslookup/tcpdump-like commands. Needs verification for exact commands before changes. |

## Lookup APIs

| Feature | Implemented In | Storage | UI Consumers |
| --- | --- | --- | --- |
| Extensions list API | `app.py` | `extensions` | list/table UI |
| Trunks list API | `app.py` | `trunks` | list/table UI |
| Inbound routes list API | `app.py` | `inbound_routes`/JSON | list/table UI |
| Outbound routes list API | `app.py` | `outbound_routes`/JSON | list/table UI |
| Queues list API | `app.py`, `db.py` | queue JSON | list/table UI |
| CDR list API | `app.py`, `db.py` | `cdr_records` | `cdr.html` |

## Known Gaps

- Some feature boundaries are not isolated; many features share `app.py`, `db.py`, and `asterisk_helper.py`.
- Outbound route final config generation depends on an external shell script outside this repo.
- `cdr_table_partial.html` is referenced by code but was not found in the project listing. Needs verification.
