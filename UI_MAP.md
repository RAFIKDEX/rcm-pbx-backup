# RCM UI Map

Most UI pages extend `templates/base.html` and use `static/css/style.css`. Several templates include inline JavaScript and inline styles for feature-specific interactions.

## Shared UI

| File | Purpose |
| --- | --- |
| `templates/base.html` | Main layout, sidebar navigation, flash/toast handling, common modals/tabs/helpers, global CSS includes. |
| `static/css/style.css` | Main dark dashboard visual system, sidebar, forms, tables, responsive styles. |

## Pages

| Page | Route | Template | Related JS/CSS |
| --- | --- | --- | --- |
| Login | `/` | `login.html` | Shared CSS, template-local styles if present. |
| Forgot password | `/forgot-password` | `forgot_password.html` | Shared CSS. |
| Verify OTP | `/forgot-password/verify` | `forgot_password_verify.html` | Shared CSS. |
| Reset password | `/forgot-password/reset` | `forgot_password_reset.html` | Shared CSS. |
| Dashboard | `/dashboard` | `dashboard.html` | Uses `/api/dashboard-status`; template JS likely handles refresh. |
| Active calls | `/active-calls` | `active_calls.html` | Uses `/api/live-calls`, `/api/hangup`, `/api/hangup-all`. |
| Extensions list | `/extensions` | `extensions.html` | Uses `/api/extensions-status`; bulk actions use AJAX endpoints. |
| Extension add/edit | `/extensions/add`, `/extensions/edit/<ext>` | `extension_form.html` | Shared form patterns; follow-me UI in template. |
| Bulk extensions | `/extensions/bulk-add` | `extensions_bulk_form.html` | Bulk form JS in template. |
| Bulk success | `/extensions/bulk-success` | `extensions_bulk_success.html` | CSV export route. |
| Trunks list | `/trunks` | `trunks.html` | Uses `/api/trunks-status`. |
| Trunk add/edit | `/trunks/add`, `/trunks/edit/<name>` | `trunk_form.html` | Dynamic fields based on trunk type/register mode. |
| Outbound routes list | `/call-routes` | `call_routes.html` | Shared table/actions. |
| Outbound route add/edit | `/call-routes/add`, `/call-routes/edit/<name>` | `outbound_route_form.html` | Route pattern/trunk/permission form JS. |
| PBX settings | `/pbx-settings` | `pbx_settings.html` | Minimal settings page. |
| Mail settings | `/system/mail-settings` | `mail_settings.html` | Test email endpoint. |
| Time settings | `/system/time` | `time_settings.html` | System timezone/date controls. |
| Network settings | `/system/network` | `network_settings.html` | Network form/status display. |
| Reports | `/reports` | `reports.html` | CDR summary table. |
| CDR | `/cdr`, `/cdr.php` | `cdr.html` | Uses `/api/cdr-list`; partial template reference `cdr_table_partial.html` appears in code but file was not found in project listing. Needs verification. |
| Call recordings | `/call-records` | `call_records.html` | Playback uses `/recordings/play/<filename>`. |
| Security | `/security` | `security.html` | Password/iptables controls. |
| System info | `/system-info` | `system_info.html` | Uses `/api/system-info-status`. |
| Configuration editor | `/configuration` | `configuration.html` | Edits selected Asterisk config file. |
| IVR list | `/ivr` | `ivr_list.html` | Shared list/actions. |
| IVR add/edit | `/ivr/add`, `/ivr/edit/<num>` | `ivr_form.html` | Dynamic DTMF mappings and destination selectors. |
| Ring groups list | `/ring-groups` | `ringgroup_list.html` | Shared list/actions. |
| Ring group add/edit | `/ring-groups/add`, `/ring-groups/edit/<id>` | `ringgroup_form.html` | Member selector and destination selector. |
| Paging list | `/paging` | `paging_list.html` | Shared list/actions. |
| Paging add/edit | `/paging/add`, `/paging/edit/<id>` | `paging_form.html` | Member selector. |
| Queue list | `/queues` | `queue_list.html` | Queue live status and agent actions. |
| Queue add/edit | `/queues/add`, `/queues/edit/<num>` | `queue_form.html` | Queue member/prompt/MOH/destination controls. |
| Speed dials list | `/speed-dials` | `speed_dial_list.html` | Shared list/actions. |
| Speed dial add/edit | `/speed-dials/add`, `/speed-dials/edit/<num>` | `speed_dial_form.html` | Destination selectors. |
| Feature codes | `/feature-codes` | `feature_codes.html` | Feature-code update form. |
| Pickup groups list | `/pickup-groups` | `pickup_groups_list.html` | Shared list/actions. |
| Pickup group add/edit | `/pickup-groups/add`, `/pickup-groups/edit/<num>` | `pickup_groups_form.html` | Extension selector. |
| Announcements list | `/announcements` | `announcement_list.html` | Shared list/actions. |
| Announcement add/edit | `/announcements/add`, `/announcements/edit/<num>` | `announcement_form.html` | Prompt and destination selector. |
| Media center | `/media-center` | `media_center.html` | Prompt/MOH upload and management controls. |
| MOH tracks | `/media/moh/tracks/<class_name>` | `moh_tracks.html` | Track upload/rename/delete controls. |
| Time conditions | `/system/time-conditions` | `time_conditions_list.html` | Office/holiday list actions. |
| Office time add/edit | `/system/time-conditions/office/add`, `/system/time-conditions/office/edit/<profile_id>` | `office_time_form.html` | Rule editor controls. |
| Holiday add/edit | `/system/time-conditions/holiday/add`, `/system/time-conditions/holiday/edit/<holiday_id>` | `holiday_form.html` | Date/recurrence form. |
| Inbound routes list | `/inbound-routes` | `inbound_routes_list.html` | Priority up/down actions. |
| Inbound route add/edit | `/inbound-routes/add`, `/inbound-routes/edit/<route_id>` | `inbound_route_form.html` | Time-condition/destination rule builder. |
| Queue stats | `/call-center/stats` | `queue_stats.html` | Uses `/call-center/stats/api`, `/api/queue-stats`, realtime endpoints. |
| Live call center | `/call-center/live` | `queue_live.html` | Uses `/call-center/live/api`, `/call-center/live/stream`, supervisor control API. |
| Queue detail | `/call-center/queues/<num>` | `queue_detail.html` | Uses `/call-center/queues/<num>/api` and call event APIs. |
| Network troubleshooting | `/system/maintenance/troubleshooting` | `network_troubleshooting.html` | Uses maintenance diagnose/capture endpoints. |

## Template Organization Notes

- `base.html` is the navigation authority for new top-level UI pages.
- UI uses dark PBX dashboard styling from `style.css`.
- Existing pages commonly use table/list pages plus add/edit form templates.
- JavaScript is mostly inline in templates and uses vanilla browser APIs.
- Font Awesome icons are loaded from CDN in `base.html`.

## Needs Verification

- `app.py` references `cdr_table_partial.html`, but this file was not present in the project file listing. Confirm whether this branch is still used.
