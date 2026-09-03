# RCM API And Route Reference

All routes are defined in `app.py`. There are no Flask Blueprints.

Template names are listed for page routes. JSON/API routes list the main helper area instead.

## Global And Auth

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/LOGO.jpg` | GET | Serve global JPEG logo/favicon from `/var/www/html`. | `send_from_directory` |
| `/Logo.png`, `/logo.png` | GET | Serve PNG logo from `/var/www/html`. | `send_from_directory` |
| `/` | GET, POST | Login page and login submission. | `login.html`, `db.authenticate_user` |
| `/logout` | GET | Clear login session and redirect to login. | session |
| `/forgot-password` | GET, POST | Request password reset OTP. | `forgot_password.html`, `db.get_user_by_username`, `db.create_otp`, `mail_service` |
| `/forgot-password/verify` | GET, POST | Verify OTP. | `forgot_password_verify.html`, `db.verify_otp` |
| `/forgot-password/reset` | GET, POST | Reset password after OTP verification. | `forgot_password_reset.html`, `db.update_user_password` |

## Dashboard And Live Calls

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/dashboard` | GET | Main dashboard summary. | `dashboard.html`, `db`, `asterisk_helper` |
| `/api/dashboard-status` | GET | Dashboard status JSON. | `asterisk_helper`, `db` |
| `/active-calls` | GET | Active calls page. | `active_calls.html` |
| `/api/live-calls` | GET | Current live calls JSON. | `asterisk_helper.get_live_calls_list` |
| `/api/hangup` | POST | Hang up one channel. | `asterisk_helper.hangup_channel` |
| `/api/hangup-all` | POST | Hang up all channels. | `asterisk_helper.hangup_all` |
| `/api/apply-changes` | POST | Apply deferred PBX reloads and clear pending changes. | `asterisk_helper.run_asterisk_cmd`, pending changes helpers |

## Extensions

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/extensions` | GET | List extensions with live status. | `extensions.html`, `db.get_all_extensions`, `asterisk_helper` |
| `/api/extensions-status` | GET | Extension live status JSON. | `db.get_all_extensions`, `asterisk_helper` |
| `/extensions/add` | GET, POST | Create extension. | `extension_form.html`, `db.add_extension`, `asterisk_helper.write_extension_configs` |
| `/extensions/edit/<ext>` | GET, POST | Edit extension. | `extension_form.html`, `db.update_extension`, `asterisk_helper.write_extension_configs` |
| `/extensions/delete/<ext>` | POST | Delete extension after dependency checks. | `db.delete_extension`, `asterisk_helper.delete_extension_configs` |
| `/extensions/info/<ext>` | GET | Extension detail/status JSON or fragment data. | `db.get_extension`, `asterisk_helper.get_registered_contacts` |
| `/extensions/bulk-delete` | POST | Bulk delete selected extensions. | `db`, `asterisk_helper` |
| `/extensions/bulk-edit` | POST | Bulk update extension fields. | `db`, `asterisk_helper` |
| `/extensions/bulk-add` | GET, POST | Bulk extension creation form/workflow. | `extensions_bulk_form.html`, `db`, `asterisk_helper` |
| `/extensions/bulk-success` | GET | Bulk add result page. | `extensions_bulk_success.html` |
| `/extensions/bulk-export-csv` | GET | Export generated bulk credentials CSV. | session |

## Trunks And Outbound Routes

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/trunks` | GET | List trunks with registration/reachability status. | `trunks.html`, `db.get_all_trunks`, `asterisk_helper` |
| `/api/trunks-status` | GET | Trunk status JSON. | `db.get_all_trunks`, `asterisk_helper` |
| `/trunks/add` | GET, POST | Create trunk. | `trunk_form.html`, `db.add_trunk`, `asterisk_helper.write_trunk_configs` |
| `/trunks/edit/<name>` | GET, POST | Edit trunk. | `trunk_form.html`, `db.update_trunk`, `asterisk_helper.write_trunk_configs` |
| `/trunks/delete/<name>` | POST | Delete trunk after dependency checks. | `db.delete_trunk`, `asterisk_helper.delete_trunk_configs` |
| `/call-routes` | GET | List outbound routes. | `call_routes.html`, `db.get_outbound_routes` |
| `/call-routes/add` | GET, POST | Create outbound route. | `outbound_route_form.html`, `db.save_outbound_routes`, `asterisk_helper.sync_outbound_routes` |
| `/call-routes/edit/<name>` | GET, POST | Edit outbound route. | `outbound_route_form.html`, `db.save_outbound_routes`, `asterisk_helper.sync_outbound_routes` |
| `/call-routes/delete/<name>` | POST | Delete outbound route. | `db.save_outbound_routes`, `asterisk_helper.sync_outbound_routes` |

## System, Configuration, CDR, Reports

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/pbx-settings` | GET, POST | PBX settings placeholder/form. | `pbx_settings.html` |
| `/system/mail-settings` | GET, POST | View/update SMTP and alert/report settings. | `mail_settings.html`, `db`, `mail_service` |
| `/system/mail-settings/test` | POST | Send test email. | `mail_service.send_email` |
| `/system/time` | GET, POST | View/update time settings. | `time_settings.html`, `db`, `asterisk_helper.apply_time_settings` |
| `/system/network` | GET, POST | View/update network settings. | `network_settings.html`, `db`, `asterisk_helper.apply_network_settings` |
| `/reports` | GET | Basic reports page from Asterisk CDR CSV. | `reports.html` |
| `/cdr`, `/cdr.php` | GET | CDR table page with filters/export handling. | `cdr.html`, CDR CSV/recording matching |
| `/call-records` | GET | List recording files. | `call_records.html` |
| `/recordings/play/<filename>` | GET | Stream/download recording from monitor folder. | `send_from_directory` |
| `/security` | GET, POST | Security/iptables view and password update. | `security.html`, `db.update_admin_password` |
| `/system-info` | GET | System info page. | `system_info.html`, `asterisk_helper.get_system_hardware_info` |
| `/api/system-info-status` | GET | System info JSON. | `asterisk_helper.get_system_hardware_info` |
| `/configuration` | GET, POST | View/edit selected Asterisk config file. | `configuration.html`, `asterisk_helper` paths |

## PBX Feature Pages

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/ivr` | GET | List IVRs. | `ivr_list.html`, `db.get_ivrs` |
| `/ivr/add` | GET, POST | Create IVR. | `ivr_form.html`, `db.save_ivrs`, `asterisk_helper.sync_ivr_dialplan` |
| `/ivr/edit/<num>` | GET, POST | Edit IVR. | `ivr_form.html`, `db.save_ivrs`, `asterisk_helper.sync_ivr_dialplan` |
| `/ivr/delete/<num>` | POST | Delete IVR. | `db.save_ivrs`, `asterisk_helper.sync_ivr_dialplan` |
| `/ring-groups` | GET | List ring groups. | `ringgroup_list.html`, `db.get_ring_groups` |
| `/ring-groups/add` | GET, POST | Create ring group. | `ringgroup_form.html`, `db.save_ring_groups`, `asterisk_helper.sync_ringgroup_dialplan` |
| `/ring-groups/edit/<id>` | GET, POST | Edit ring group. | `ringgroup_form.html`, `db.save_ring_groups`, `asterisk_helper.sync_ringgroup_dialplan` |
| `/ring-groups/delete/<id>` | POST | Delete ring group. | `db.save_ring_groups`, `asterisk_helper.sync_ringgroup_dialplan` |
| `/paging` | GET | List paging/intercom groups. | `paging_list.html`, `db.get_paging` |
| `/paging/add` | GET, POST | Create paging group. | `paging_form.html`, `db.save_paging`, `asterisk_helper.sync_paging_dialplan` |
| `/paging/edit/<id>` | GET, POST | Edit paging group. | `paging_form.html`, `db.save_paging`, `asterisk_helper.sync_paging_dialplan` |
| `/paging/delete/<id>` | POST | Delete paging group. | `db.save_paging`, `asterisk_helper.sync_paging_dialplan` |
| `/queues` | GET | List queues with live status. | `queue_list.html`, `db.get_queues`, `asterisk_helper.get_live_queue_status` |
| `/queues/add` | GET, POST | Create queue. | `queue_form.html`, `db.save_queues`, `asterisk_helper.sync_queue_dialplan` |
| `/queues/edit/<num>` | GET, POST | Edit queue. | `queue_form.html`, `db.save_queues`, `asterisk_helper.sync_queue_dialplan` |
| `/queues/delete/<num>` | POST | Delete queue. | `db.save_queues`, `asterisk_helper.sync_queue_dialplan` |
| `/queues/<num>/agents/add` | POST | Add static queue agent. | `db.save_queues`, `rcm_queue_db` |
| `/queues/<num>/agents/remove` | POST | Remove queue agent. | `db.save_queues`, `rcm_queue_db`, Asterisk CLI |
| `/queues/<num>/agents/enable` | POST | Enable queue agent. | `db.save_queues`, Asterisk CLI |
| `/queues/<num>/agents/disable` | POST | Disable/pause queue agent. | `db.save_queues`, Asterisk CLI |
| `/queues/<num>/agents/join` | POST | Dynamic agent join queue. | Asterisk CLI, `rcm_queue_db` |
| `/queues/<num>/agents/leave` | POST | Dynamic agent leave queue. | Asterisk CLI, `rcm_queue_db` |
| `/speed-dials` | GET | List speed dials. | `speed_dial_list.html`, `db.get_speed_dials` |
| `/speed-dials/add` | GET, POST | Create speed dial. | `speed_dial_form.html`, `db.save_speed_dials`, `asterisk_helper.sync_speed_dial_dialplan` |
| `/speed-dials/edit/<num>` | GET, POST | Edit speed dial. | `speed_dial_form.html`, `db.save_speed_dials`, `asterisk_helper.sync_speed_dial_dialplan` |
| `/speed-dials/delete/<num>` | POST | Delete speed dial. | `db.save_speed_dials`, `asterisk_helper.sync_speed_dial_dialplan` |
| `/feature-codes` | GET | List feature codes. | `feature_codes.html`, `db.get_all_feature_codes` |
| `/feature-codes/update` | POST | Update feature codes. | `db.update_feature_code`, `asterisk_helper.sync_feature_codes_dialplan` |
| `/pickup-groups` | GET | List pickup groups. | `pickup_groups_list.html` |
| `/pickup-groups/add` | GET, POST | Create pickup group. | `pickup_groups_form.html`, `asterisk_helper.sync_pickup_groups_dialplan` |
| `/pickup-groups/edit/<num>` | GET, POST | Edit pickup group. | `pickup_groups_form.html`, `asterisk_helper.sync_pickup_groups_dialplan` |
| `/pickup-groups/delete/<num>` | POST | Delete pickup group. | `asterisk_helper.sync_pickup_groups_dialplan` |
| `/announcements` | GET | List announcements. | `announcement_list.html` |
| `/announcements/add` | GET, POST | Create announcement. | `announcement_form.html`, `asterisk_helper.sync_announcement_dialplan` |
| `/announcements/edit/<num>` | GET, POST | Edit announcement. | `announcement_form.html`, `asterisk_helper.sync_announcement_dialplan` |
| `/announcements/delete/<num>` | POST | Delete announcement. | `asterisk_helper.sync_announcement_dialplan` |

## Media Center

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/media-center` | GET | Manage prompts and MOH classes. | `media_center.html`, `db.get_media_center_db` |
| `/media/prompt/upload` | POST | Upload/convert prompt audio. | `asterisk_helper.save_and_convert_audio` |
| `/media/prompt/rename` | POST | Rename prompt metadata/file. | `db.save_media_center_db` |
| `/media/prompt/delete/<id>` | POST | Delete prompt after dependency checks. | `db.save_media_center_db` |
| `/media/moh/class/create` | POST | Create MOH class. | `asterisk_helper.write_moh_class_config` |
| `/media/moh/class/edit/<name>` | POST | Rename/update MOH class. | `asterisk_helper.write_moh_class_config` |
| `/media/moh/class/delete/<name>` | POST | Delete MOH class after dependency checks. | `asterisk_helper.delete_moh_class_config` |
| `/media/moh/tracks/<class_name>` | GET | List MOH tracks for class. | `moh_tracks.html` |
| `/media/moh/tracks/upload/<class_name>` | POST | Upload/convert MOH track. | `asterisk_helper.save_and_convert_audio` |
| `/media/moh/track/rename/<class_name>` | POST | Rename MOH track. | filesystem |
| `/media/moh/track/delete/<class_name>/<filename>` | POST | Delete MOH track. | filesystem |
| `/media_proxy` | GET | Proxy media playback. | filesystem/send response |

## Time Conditions And Inbound Routes

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/system/time-conditions` | GET | List office times and holidays. | `time_conditions_list.html` |
| `/system/time-conditions/office/add` | GET, POST | Create office time profile. | `office_time_form.html`, `db.save_office_time_class` |
| `/system/time-conditions/office/edit/<profile_id>` | GET, POST | Edit office time profile. | `office_time_form.html`, `db.save_office_time_class` |
| `/system/time-conditions/office/delete/<profile_id>` | POST | Delete office profile. | `db.delete_office_time_class` |
| `/system/time-conditions/office/clone/<profile_id>` | POST | Clone office profile. | `db.clone_office_time_class` |
| `/system/time-conditions/office/toggle/<profile_id>` | POST | Enable/disable office profile. | `db.toggle_office_time_class` |
| `/system/time-conditions/holiday/add` | GET, POST | Create holiday. | `holiday_form.html`, `db.save_holidays` |
| `/system/time-conditions/holiday/edit/<holiday_id>` | GET, POST | Edit holiday. | `holiday_form.html`, `db.save_holidays` |
| `/system/time-conditions/holiday/delete/<holiday_id>` | POST | Delete holiday. | `db.save_holidays` |
| `/inbound-routes` | GET | List inbound routes. | `inbound_routes_list.html`, `db.get_inbound_routes` |
| `/inbound-routes/add` | GET, POST | Create inbound route. | `inbound_route_form.html`, `db.save_inbound_routes`, `asterisk_helper.sync_inbound_routes_dialplan` |
| `/inbound-routes/edit/<route_id>` | GET, POST | Edit inbound route. | `inbound_route_form.html`, `db.save_inbound_routes`, `asterisk_helper.sync_inbound_routes_dialplan` |
| `/inbound-routes/delete/<route_id>` | POST | Delete inbound route. | `db.save_inbound_routes`, `asterisk_helper.sync_inbound_routes_dialplan` |
| `/call-routes/priority/<name>/<direction>` | POST | Move outbound route priority up/down. | `db.save_outbound_routes`, `asterisk_helper.sync_outbound_routes` |

## Call Center

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/call-center/stats` | GET | Queue statistics UI. | `queue_stats.html`, `db.get_queues`, `rcm_queue_db` |
| `/call-center/stats/api` | GET | Queue stats data API. | `rcm_queue_db.get_filtered_queue_stats`, `get_agent_analytics` |
| `/api/queue-stats` | GET | Alternate queue stats API. | `rcm_queue_db` |
| `/call-center/stats/export` | GET | Export queue stats. | `rcm_queue_db` |
| `/call-center/live` | GET | Live call-center dashboard. | `queue_live.html` |
| `/call-center/live/api` | GET | Live dashboard JSON. | `rcm_queue_db.get_live_dashboard_status` |
| `/call-center/stats/realtime-api` | GET | Realtime stats JSON. | `rcm_queue_db` |
| `/call-center/stats/realtime-stream` | GET | SSE realtime stats stream. | `Response`, `rcm_queue_db` |
| `/call-center/live/stream` | GET | SSE live dashboard stream. | `Response`, `rcm_queue_db` |
| `/call-center/supervisor/control` | POST | Supervisor queue/agent controls. | `asterisk_helper.send_ami_command`, `rcm_queue_db` |
| `/call-center/queues/<num>` | GET | Queue detail page. | `queue_detail.html` |
| `/call-center/queues/<num>/api` | GET | Queue detail JSON. | `rcm_queue_db` |
| `/api/calls/<callid>/events` | GET | Call event timeline JSON. | `rcm_queue_db.get_call_details_timeline` |
| `/call-center/call-details/<uid>` | GET | Call details JSON/page data. | `rcm_queue_db` |

## Maintenance And Lookup APIs

| Route | Methods | Purpose | Template/Helpers |
| --- | --- | --- | --- |
| `/system/maintenance/troubleshooting` | GET | Network troubleshooting page. | `network_troubleshooting.html` |
| `/system/maintenance/diagnose` | POST | Run diagnostic action. | subprocess/network helpers |
| `/system/maintenance/capture` | POST | Start packet capture. | subprocess |
| `/system/maintenance/capture/status` | GET | Packet capture status. | subprocess/session state |
| `/system/maintenance/download-capture` | GET | Download capture output. | send file/response |
| `/api/extensions-list` | GET | Paginated/searchable extension list. | `db.get_db` |
| `/api/trunks-list` | GET | Paginated/searchable trunk list. | `db.get_db` |
| `/api/inbound-routes-list` | GET | Paginated/searchable inbound routes list. | `db.get_db` |
| `/api/outbound-routes-list` | GET | Paginated/searchable outbound routes list. | `db.get_db` |
| `/api/queues-list` | GET | Paginated/searchable queue list. | `db.get_queues` |
| `/api/cdr-list` | GET | Paginated/searchable CDR list. | `db.get_db`, recording matching |

## Needs Verification

- Exact payload shape for several AJAX endpoints should be verified before clients are built against them.
- Some endpoints return redirects/flash messages rather than pure JSON despite being used by AJAX in templates.
