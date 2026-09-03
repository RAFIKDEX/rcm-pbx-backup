# RCM Asterisk Configuration Flow

This file documents how RCM turns database and JSON feature state into Asterisk/PJSIP configuration.

## Core Integration Files

Defined in `asterisk_helper.py` and `db.py`:

| Constant/File | Purpose |
| --- | --- |
| `/etc/asterisk/pjsip.gui.endpoint.conf` | PJSIP endpoints for extensions and trunks. |
| `/etc/asterisk/pjsip.gui.auth.conf` | PJSIP auth sections for extensions and trunks. |
| `/etc/asterisk/pjsip.gui.aor.conf` | PJSIP AOR sections for extensions and trunks. |
| `/etc/asterisk/pjsip.gui.identify.conf` | PJSIP identify sections for trunks. |
| `/etc/asterisk/pjsip.gui.reg.conf` | PJSIP outbound registration sections for client-registration trunks. |
| `/etc/asterisk/extensions_gui.conf` | Main GUI dialplan/global extension variables. |
| `/etc/asterisk/context_exten.conf` | Per-extension outbound permission contexts. |
| `/etc/asterisk/voicemail.conf` | Voicemail mailbox entries. |
| `/etc/asterisk/followme.conf` | Follow-me entries. |
| `/etc/asterisk/queues.conf` | Queue definitions. |
| `/etc/asterisk/musiconhold.conf` | MOH class definitions. |

## Extensions

Routes:

- `/extensions/add`
- `/extensions/edit/<ext>`
- `/extensions/delete/<ext>`
- bulk extension routes

Flow:

1. `app.py` validates form input.
2. `db.add_extension`, `db.update_extension`, or `db.delete_extension` updates `extensions`.
3. `asterisk_helper.write_extension_configs` writes:
   - endpoint section to `pjsip.gui.endpoint.conf`
   - auth section to `pjsip.gui.auth.conf`
   - AOR section to `pjsip.gui.aor.conf`
   - global variables and internal extension route to `extensions_gui.conf`
   - per-extension context through `rebuild_all_extensions_contexts` into `context_exten.conf`
   - voicemail mailbox to `voicemail.conf`
   - follow-me section to `followme.conf`
4. `add_pending_change` records the pending reload.

Delete flow removes extension sections from the same files.

## Trunks

Routes:

- `/trunks/add`
- `/trunks/edit/<name>`
- `/trunks/delete/<name>`

Flow:

1. `app.py` validates form input.
2. `db.add_trunk`, `db.update_trunk`, or `db.delete_trunk` updates `trunks`.
3. `asterisk_helper.write_trunk_configs` writes marker-based trunk blocks:
   - endpoint block to `pjsip.gui.endpoint.conf`
   - AOR block to `pjsip.gui.aor.conf`
   - auth block to `pjsip.gui.auth.conf` when needed
   - registration block to `pjsip.gui.reg.conf` for client-registration trunks
   - identify block to `pjsip.gui.identify.conf` when needed
4. `delete_trunk_configs` removes marker-based trunk blocks.

Supported trunk modes:

- Peer trunk
- Register/client trunk
- Register/server trunk

## Outbound Routes

Routes:

- `/call-routes/add`
- `/call-routes/edit/<name>`
- `/call-routes/delete/<name>`

Data:

- Stored through `db.get_outbound_routes` and `db.save_outbound_routes`.
- Current file path is `/etc/asterisk/rcm_outbound/routes.json`; legacy path is `/etc/asterisk/rcm_outbound_routes.json`.

Flow:

1. `app.py` validates route name, patterns, trunks, and permissions.
2. Route JSON is saved.
3. `asterisk_helper.sync_outbound_routes` calls `rebuild_all_extensions_contexts`.
4. `rebuild_all_extensions_contexts` writes per-extension includes to `/etc/asterisk/context_exten.conf`.
5. `sync_outbound_routes` runs `/usr/local/bin/rcm_gen_outbound_routes.sh`.
6. Dialplan reload is requested.

Needs verification: exact generated outbound dialplan file is produced by the external shell script, not by Python code in this repo.

## IVRs

Routes:

- `/ivr/add`
- `/ivr/edit/<num>`
- `/ivr/delete/<num>`

Data:

- `/etc/asterisk/rcm_ivrs.json`

Flow:

1. `db.save_ivrs` validates duplicate DTMF keys within each IVR.
2. `asterisk_helper.sync_ivr_dialplan` writes `/etc/asterisk/extensions.ivr.gui.conf`.
3. Prompts are resolved through `resolve_asterisk_prompt` from media-center metadata.
4. Destinations are rendered through `resolve_dest_to_dialplan`.

## Queues

Routes:

- `/queues/add`
- `/queues/edit/<num>`
- `/queues/delete/<num>`
- `/queues/<num>/agents/...`

Data:

- `/etc/asterisk/rcm_queues.json`
- synchronized to `rcm_queue.db.queues`

Flow:

1. `db.save_queues` saves JSON queue definitions.
2. `db.save_queues` calls `rcm_queue_db.db_sync_queue` for each queue and prunes deleted queues.
3. `asterisk_helper.sync_queue_dialplan` writes:
   - RCM queue block inside `/etc/asterisk/queues.conf`
   - queue routes, queue feature codes, and queue contexts to `/etc/asterisk/extensions.queue.gui.conf`
4. Static agents are rendered as `member => PJSIP/<agent>`.
5. Disabled agents are rendered with paused member state.
6. Queue feature-code prefixes come from `rcm_feature_codes`.

Queue live/reporting state is not generated from config; it is populated by AMI events in `rcm_queue_collector.py`.

## Ring Groups

Routes:

- `/ring-groups/add`
- `/ring-groups/edit/<id>`
- `/ring-groups/delete/<id>`

Data:

- `/etc/asterisk/rcm_ring_groups.json`

Flow:

1. Ring group JSON is saved through `db.save_ring_groups`.
2. `asterisk_helper.sync_ringgroup_dialplan` writes `/etc/asterisk/extensions.ringgroup.gui.conf`.
3. Members are rendered as PJSIP dial targets.
4. Failover destination is rendered through `resolve_dest_to_dialplan`.

## Paging And Intercom

Routes:

- `/paging/add`
- `/paging/edit/<id>`
- `/paging/delete/<id>`

Data:

- `/etc/asterisk/rcm_paging_intercom.json`

Flow:

1. Paging JSON is saved through `db.save_paging`.
2. `asterisk_helper.sync_paging_dialplan` writes `/etc/asterisk/extensions.paging.gui.conf`.
3. Members are rendered into Asterisk `Page(...)`.
4. Optional allowed callers, duplex mode, and welcome prompt are included.

## Speed Dials

Routes:

- `/speed-dials/add`
- `/speed-dials/edit/<num>`
- `/speed-dials/delete/<num>`

Data:

- `/etc/asterisk/rcm_speed_dials.json`

Flow:

1. Speed dial JSON is saved.
2. `asterisk_helper.sync_speed_dial_dialplan` writes `/etc/asterisk/extensions.speed_dial.gui.conf`.

## Feature Codes

Routes:

- `/feature-codes`
- `/feature-codes/update`

Data:

- Main DB table `rcm_feature_codes`
- Legacy JSON constant exists: `/etc/asterisk/rcm_feature_codes.json`

Flow:

1. Feature code rows are updated through `db.update_feature_code`.
2. `asterisk_helper.sync_feature_codes_dialplan` writes `/etc/asterisk/extensions.feature_codes.gui.conf`.
3. `asterisk_helper.sync_features_conf` writes transfer-related codes to `/etc/asterisk/features.conf`.
4. Queue feature-code prefixes are consumed by `sync_queue_dialplan`.

## Pickup Groups

Routes:

- `/pickup-groups/add`
- `/pickup-groups/edit/<num>`
- `/pickup-groups/delete/<num>`

Data:

- `/etc/asterisk/rcm_pickup_groups.json`

Flow:

1. Pickup group JSON is saved.
2. `asterisk_helper.sync_pickup_groups_dialplan` writes `/etc/asterisk/extensions.pickup_groups.gui.conf`.

## Announcements

Routes:

- `/announcements/add`
- `/announcements/edit/<num>`
- `/announcements/delete/<num>`

Data:

- `/etc/asterisk/rcm_announcements.json`

Flow:

1. Announcement JSON is saved.
2. `asterisk_helper.sync_announcement_dialplan` writes `/etc/asterisk/extensions.announcement.gui.conf`.
3. Prompt and post-announcement destination are resolved through existing helpers.

## Media Prompts And MOH

Routes:

- `/media-center`
- `/media/prompt/...`
- `/media/moh/...`

Data:

- `/etc/asterisk/rcm_media_center.json`
- audio files under Asterisk sounds/MOH paths
- `/etc/asterisk/musiconhold.conf`

Flow:

1. Prompt/MOH metadata is saved in media-center JSON.
2. Audio upload uses `asterisk_helper.save_and_convert_audio`.
3. MOH class create/edit/delete updates `musiconhold.conf`.
4. MOH reload is deferred through apply changes.

## Inbound Routes And Time Conditions

Routes:

- `/system/time-conditions/...`
- `/inbound-routes/...`

Data:

- `/etc/asterisk/rcm_office_times.json`
- `/etc/asterisk/rcm_holidays.json`
- `/etc/asterisk/rcm_inbound_routes.json`

Flow:

1. Office times, holidays, and inbound routes are saved through `db.py`.
2. `asterisk_helper.sync_inbound_routes_dialplan` writes `/etc/asterisk/extensions.inbound.gui.conf`.
3. `ensure_inbound_include` ensures `#include extensions.inbound.gui.conf` exists in `/etc/asterisk/extensions.context.conf`.
4. Generated dialplan includes:
   - office time subroutines
   - holiday subroutines
   - `from-trunk`
   - route evaluation contexts
   - matched route action contexts
   - inbound trunk-dial wrapper contexts

## Reload And Apply-Changes Flow

Most calls to `asterisk_helper.run_asterisk_cmd` suppress reload commands because `DEFER_RELOAD = True`.

When the user applies changes:

1. `/api/apply-changes` receives POST.
2. `asterisk_helper.DEFER_RELOAD` is set to `False`.
3. The app runs:
   - `pjsip reload`
   - `dialplan reload`
   - `queue reload all`
   - `moh reload`
4. `clear_pending_changes` clears `/root/RCM_7021/rcm_pending_changes.json`.
5. `DEFER_RELOAD` is restored to `True`.

## Needs Verification

- Some generated files must be included by the system Asterisk config. Include relationships outside this repo should be verified on the target server.
- Outbound route final dialplan generation depends on `/usr/local/bin/rcm_gen_outbound_routes.sh`, which is outside this project directory.
