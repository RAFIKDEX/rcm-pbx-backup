# Asterisk GUI Project Review & Status Report

This report presents a thorough review of the current implementation of the Asterisk GUI project (RCM 7021). All backend code ([app.py](file:///root/RCM_7021/app.py), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [db.py](file:///root/RCM_7021/db.py)) and frontend templates have been analyzed for correct CRUD operations, Asterisk integration, and system functionality.

---

## 1. Completed & Functional Features

The following modules have been verified as fully functional (both UI and backend integrations work correctly):

### Extensions Management
* **Database Persistence**: Extension records are stored in SQLite `extensions` table.
* **CRUD Operations**: Add, edit, and delete actions are supported.
* **Asterisk PJSIP Configs**: Correctly generates blocks in [pjsip.gui.endpoint.conf](file:///etc/asterisk/pjsip.gui.endpoint.conf), [pjsip.gui.auth.conf](file:///etc/asterisk/pjsip.gui.auth.conf), and [pjsip.gui.aor.conf](file:///etc/asterisk/pjsip.gui.aor.conf).
* **Voicemail Integration**: Correctly updates [voicemail.conf](file:///etc/asterisk/voicemail.conf) dynamically.
* **Follow-Me Integration**: Generates lists in [followme.conf](file:///etc/asterisk/followme.conf) dynamically.
* **Registration Validation**: Retrieves registration status and contact information via Asterisk commands `pjsip show endpoints` and `pjsip show contacts`.

### Trunks Management
* **Database Persistence**: Trunk records are stored in SQLite `trunks` table.
* **CRUD Operations**: Creating, editing, and deleting trunks works.
* **Configuration Sync**: Autogenerates blocks for registration and endpoint config in [pjsip.gui.endpoint.conf](file:///etc/asterisk/pjsip.gui.endpoint.conf), [pjsip.gui.auth.conf](file:///etc/asterisk/pjsip.gui.auth.conf), [pjsip.gui.aor.conf](file:///etc/asterisk/pjsip.gui.aor.conf), [pjsip.gui.identify.conf](file:///etc/asterisk/pjsip.gui.identify.conf), and [pjsip.gui.reg.conf](file:///etc/asterisk/pjsip.gui.reg.conf).
* **Trunk Status**: Accurately queries registering and peer trunks status.

### PBX Dialplan Objects (JSON + Dialplan Sync)
* **Interactive Voice Response (IVR)**: Full CRUD is saved in `rcm_ivrs.json` and synced to [extensions.ivr.gui.conf](file:///etc/asterisk/extensions.ivr.gui.conf).
* **Ring Groups**: Full CRUD is saved in `rcm_ring_groups.json` and synced to [extensions.ringgroup.gui.conf](file:///etc/asterisk/extensions.ringgroup.gui.conf).
* **Paging & Intercom**: Full CRUD is saved in `rcm_paging_intercom.json` and synced to [extensions.paging.gui.conf](file:///etc/asterisk/extensions.paging.gui.conf).
* **Call Queues**: Full CRUD is saved in `rcm_queues.json` and synced to [extensions.queue.gui.conf](file:///etc/asterisk/extensions.queue.gui.conf).
* **Speed Dial**: Full CRUD is saved in `rcm_speed_dials.json` and synced to [extensions.speed_dial.gui.conf](file:///etc/asterisk/extensions.speed_dial.gui.conf).
* **Feature Codes**: Full CRUD is saved in `rcm_feature_codes.json` and synced to [extensions.feature_codes.gui.conf](file:///etc/asterisk/extensions.feature_codes.gui.conf).
* **Pickup Groups**: Full CRUD is saved in `rcm_pickup_groups.json` and synced to [extensions.pickup_groups.gui.conf](file:///etc/asterisk/extensions.pickup_groups.gui.conf).
* **Announcements**: Full CRUD is saved in `rcm_announcements.json` and synced to [extensions.announcement.gui.conf](file:///etc/asterisk/extensions.announcement.gui.conf).

### System Utilities
* **Active Calls Monitoring**: Correctly parses `core show channels concise` and merges multi-leg channels to show active caller, callee, state, and call duration. Supports hangup/hangup-all.
* **CDR Log Parsing**: Reads from `/var/log/asterisk/cdr-csv/Master.csv` and presents detailed call histories.
* **Call Recordings Player**: Links CDR/Call Record files to `/var/spool/asterisk/monitor/` and plays them on the frontend.
* **Security Credentials**: Resets admin credentials in SQLite and displays `iptables` active chains.
* **Deferred Reload Banner**: Stores pending changes in `rcm_pending_changes.json` and exposes a top banner with an **Apply Changes** button (`/api/apply-changes`) that runs reloads across Asterisk modules (`pjsip reload`, `dialplan reload`, `queue reload`, `moh reload`).

---

## 2. Broken Features & Operational Risks

> [!WARNING]
> The following issues represent defects or high-risk operational behaviors in the current system:

1. **Audio Conversion Utilities Missing (High Risk)**:
   * **Issue**: The system relies on `sox` or `ffmpeg` commands to convert uploaded audio files (prompts/music tracks) into Asterisk-compliant formats (8000Hz, 16-bit, mono WAV).
   * **Root Cause**: Neither `sox` nor `ffmpeg` is installed in the current environment. As a result, the `save_and_convert_audio` function in [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) falls back to `shutil.copy2` (plain file copy).
   * **Impact**: If a user uploads an MP3 or a non-compliant WAV file, Asterisk will fail to play it, rendering the Media Center and MOH features broken for non-conforming uploads.
2. **Mock Settings & Backup (Medium Risk)**:
   * **Issue**: The Regional Settings and Global SIP Defaults under the "PBX Settings" tab are disabled/locked in the UI, and the form submission redirects without updating any settings.
   * **Backup Action**: The "Create & Download Backup" button triggers a mock JavaScript `alert('Backup downloaded successfully.')` and does not perform any actual backup operations.
3. **Write Permissions in /etc/asterisk/**:
   * **Issue**: All RCM-specific files are written directly into `/etc/asterisk/`. While currently the permissions are set to group `www-data` with `rw` access, any future permissions reset or environment migration could lead to write-permission errors.

---

## 3. Missing Functionality (UI Mockups or Missing CRUD)

> [!IMPORTANT]
> The following sections are only partially implemented or exist as read-only/mock UI elements:

1. **No Routing Configuration (Inbound/Outbound Routes)**:
   * **Issue**: The "Call Routes" page ([call_routes.html](file:///root/RCM_7021/templates/call_routes.html)) is entirely **read-only**.
   * **Impact**: There are no buttons, forms, or APIs to add, edit, or delete Outbound Dial Patterns or Inbound trunk destinations. The GUI merely reads whatever is written in the static files `/etc/asterisk/rcm_outbound_routes.conf` and `/etc/asterisk/rcm_ring_groups.conf`.
2. **No Edit category settings in MOH**:
   * **Issue**: There is no endpoint or form to edit properties of an MOH category (such as switching play mode between `files` and `custom`) after creation. Users must delete and recreate the category.

---

## 4. Priority Fixes & Action Plan

Before initiating new features, we must perform the following fixes to stabilize the system:

| Priority | Issue / Task | Target Files | Solution Details |
| :--- | :--- | :--- | :--- |
| **High** | Install Audio Converters | System packages | Install `sox` and `ffmpeg` packages to enable audio conversion for IVRs, Announcements, and MOH. |
| **High** | Complete Routing CRUD | [app.py](file:///root/RCM_7021/app.py)<br>[templates/call_routes.html](file:///root/RCM_7021/templates/call_routes.html) | Implement backend routes and modal forms to allow creating, updating, and deleting outbound dial patterns. |
| **Medium** | Implement Real Backup | [app.py](file:///root/RCM_7021/app.py)<br>[asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Replace mock JS backup action with a zip download containing `/etc/asterisk/rcm_*.json`, `/root/RCM_7021/rcm_7021.db`, and custom configs. |
| **Medium** | Enable PBX Settings Save | [app.py](file:///root/RCM_7021/app.py)<br>[db.py](file:///root/RCM_7021/db.py) | Bind PBX settings form fields to SQLite config table (or JSON config) so settings can actually be customized. |

---

## 5. Files Requiring Modification

For the upcoming stabilization phase, modifications will be made to:
* **[app.py](file:///root/RCM_7021/app.py)**: Add outbound route CRUD endpoints, backup creation, and settings persistence.
* **[db.py](file:///root/RCM_7021/db.py)**: Add database helper to store and load global system settings.
* **[asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py)**: Add helper functions for backing up configurations and writing dynamic outbound route configurations.
* **[call_routes.html](file:///root/RCM_7021/templates/call_routes.html)**: Add "Add/Edit/Delete Outbound Route" modals and forms.
* **[pbx_settings.html](file:///root/RCM_7021/templates/pbx_settings.html)**: Enable form inputs and connect the backup action to the backend.
