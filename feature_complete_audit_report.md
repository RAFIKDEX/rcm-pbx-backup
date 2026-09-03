# PBX Feature Audit Report

This report presents the findings, fixes, and current status of all PBX feature chains (GUI → API → Backend Logic → Database → Asterisk Configuration → Dialplan Behavior).

---

## 1. Feature Code Matrix & Status

| Feature Name | Feature Code | Current Status | Issues Found | Files Changed | Verification Result |
| :--- | :---: | :---: | :--- | :--- | :--- |
| **Voicemail Access** | `*97` | **Working** | None (Inherited dialplan was sound). | None | Mailbox authentication, user access, and playback work. |
| **Forward Always (ON)** | `*64` | **Working** | Legacy dialplan lacked checking logic in the call routing stage; it was completely ignored. | [extensions.conf](file:///etc/asterisk/extensions.conf) | Call immediately routes to the configured forwarding destination. |
| **Forward Always (OFF)** | `*65` | **Working** | None. | [extensions.conf](file:///etc/asterisk/extensions.conf) | Cancels forwarding in AstDB, calls route normally to extension. |
| **Forward on Busy (ON)** | `*58` | **Working** | Used legacy MySQL commands referencing a non-existent database (`asteriskcdr`), preventing state storage and lookup. | [extensions.conf](file:///etc/asterisk/extensions.conf), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Updates AstDB. Busy calls route to the busy forwarding number. |
| **Forward on Busy (OFF)** | `*59` | **Working** | Used legacy MySQL queries referencing a non-existent database (`asteriskcdr`). | [extensions.conf](file:///etc/asterisk/extensions.conf), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Cancels forwarding in AstDB, busy calls return to busy tone. |
| **Forward No Answer (ON)** | `*60` | **Working** | Used legacy MySQL queries referencing a non-existent database (`asteriskcdr`). | [extensions.conf](file:///etc/asterisk/extensions.conf), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Updates AstDB. No-answer calls route to configured number. |
| **Forward No Answer (OFF)**| `*61` | **Working** | Used legacy MySQL queries referencing a non-existent database (`asteriskcdr`). | [extensions.conf](file:///etc/asterisk/extensions.conf), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Cancels forwarding in AstDB. |
| **Forward Unavail (ON)** | `*62` | **Working** | Used legacy MySQL queries; routing did not fallback to checking unavailable destinations. | [extensions.conf](file:///etc/asterisk/extensions.conf), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Updates AstDB. Unavailable calls route to configured destination. |
| **Forward Unavail (OFF)** | `*63` | **Working** | Used legacy MySQL queries. | [extensions.conf](file:///etc/asterisk/extensions.conf), [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py) | Cancels forwarding in AstDB. |
| **DND (Activate)** | `*37` | **Working** | None. | [extensions.conf](file:///etc/asterisk/extensions.conf) | DND state updates to `on` in AstDB, incoming calls receive busy/voicemail. |
| **DND (Deactivate)** | `*38` | **Working** | None. | [extensions.conf](file:///etc/asterisk/extensions.conf) | DND state updates to `off` in AstDB, incoming calls ring normally. |
| **Call Recording Toggle** | `*1` | **Working** | Commented out in `features.conf`; Dial options in `extensions.conf` lacked key hook flags (`XxWw`). | [features.conf](file:///etc/asterisk/features.conf), [extensions.conf](file:///etc/asterisk/extensions.conf) | Pressing `*1` dynamically toggles MixMonitor on-the-fly. |
| **General Call Pickup** | `*8` | **Working** | Conflicting definitions and pickup context errors in files included before context creation. | [extensions.conf](file:///etc/asterisk/extensions.conf), [extensions.feature_codes.gui.conf](file:///etc/asterisk/extensions.feature_codes.gui.conf) | Ringing call in same pickup group is grabbed immediately. |
| **Directed Call Pickup** | `**` | **Working** | Conflicting definitions in files included before context creation. | [extensions.conf](file:///etc/asterisk/extensions.conf), [extensions.feature_codes.gui.conf](file:///etc/asterisk/extensions.feature_codes.gui.conf) | Dialing `**<ext>` successfully picks up targeted ringing device. |
| **Blind Transfer** | `##` | **Working** | Disabled/commented out in `features.conf`. | [features.conf](file:///etc/asterisk/features.conf) | Pressing `##` prompts for destination, completes transfer. |
| **Attended Transfer** | `*2` | **Working** | Disabled/commented out in `features.conf`. | [features.conf](file:///etc/asterisk/features.conf) | Pressing `*2` initiates transfer with consultant step. |
| **Listen Spy** | `*55` | **Working** | Spy prefix configurations did not exist in the Asterisk dialplan. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py) | Dialing `*55<ext>` or clicking Listen in GUI launches quiet spy. |
| **Whisper Spy** | `*56` | **Working** | Whisper prefix configurations did not exist in the Asterisk dialplan. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py) | Dialing `*56<ext>` or Coach in GUI coaches target extension. |
| **Barge Spy** | `*57` | **Working** | Barge prefix did not exist in dialplan; Barge was missing in the GUI dropdown console. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py), [queue_live.html](file:///root/RCM_7021/templates/queue_live.html) | Dialing `*57<ext>` or selecting Barge In in GUI inserts supervisor. |
| **Queue Login** | `*71` | **Working** | Dialplan block was hardcoded and static without checking duplicate logins or queue existence. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py) | Checks status via API/dialplan; blocks duplicate agent joins. |
| **Queue Logout** | `*72` | **Working** | Dialplan block was static and did not validate agent membership before logging off. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py) | Validates membership; logs agent off queue. |
| **Queue Pause** | `*73` | **Working** | Code was static and hardcoded to the support queue. Duplicate check was missing. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py) | Checks if already paused; toggles pause state in Asterisk. |
| **Queue Unpause** | `*74` | **Working** | Code was static and hardcoded. | [asterisk_helper.py](file:///root/RCM_7021/asterisk_helper.py), [app.py](file:///root/RCM_7021/app.py) | Checks if not paused; toggles back to active state. |

---

## 2. Key Audit Rectifications

### A. Database Alignment (MySQL → AstDB)
- **Problem**: Feature codes related to Forward Busy, Forward No Answer, and Forward Unavailable queried a legacy MariaDB `asteriskcdr` database that did not exist on this SQLite-centric installation.
- **Solution**: Removed MySQL execution layers (`System(mysql ...)` and `SHELL(mysql ...)`) and migrated entirely to Asterisk's internal **AstDB** storage (`DB(FORWARD/...)`). AstDB is local, fast, and does not depend on a MariaDB database server schema.

### B. Dialplan Append Order Fix
- **Problem**: Context appends using the `(+)` operator (e.g. `[rcm-internal-destinations](+)` in `extensions.feature_codes.gui.conf`) were parsed before the base context was defined because dynamic includes were positioned at line 24 of `extensions.conf`.
- **Solution**: Moved all dynamic `#include` directives to the end of `extensions.conf`. This guarantees base contexts are parsed first, fixing the `Context 'rcm-internal-destinations' tries to include nonexistent context 'rcm-feature-codes'` warning.

### C. Enable DTMF Mappings (`features.conf`)
- **Problem**: Blind transfer, attended transfer, and call recording DTMF features were disabled because the `[featuremap]` section of `/etc/asterisk/features.conf` was empty.
- **Solution**: Mapped `blindxfer => ##`, `atxfer => *2`, and `automixmon => *1`. Added `XxWw` flags to the `Dial` statement in the `[dexter]` context to allow channels to trigger these features.

### D. GUI Extensions Live Badges
- **Problem**: DND and Call Forwarding configurations stored in AstDB were invisible on the GUI extensions list.
- **Solution**: 
  1. Implemented a Python helper `get_asterisk_db_features()` in `asterisk_helper.py` to parse `database show` output in a single fast command.
  2. Integrated these status maps into `/extensions` and `/api/extensions-status` in `app.py`.
  3. Added responsive CSS badges in [extensions.html](file:///root/RCM_7021/templates/extensions.html) to show red `DND` and blue `FWD: <num>` tags dynamically alongside registration status.

---

## 3. QA Call Flow Test Scenarios
- **DND Action**: Dialed `*37` from SIP endpoint. System played `do-not-disturb` and hung up. Verified AstDB key `DND/<num>` was set to `on`. Verified extensions GUI instantly showed red `DND` badge. Incoming calls automatically routed to busy/voicemail. Dialing `*38` deactivated DND, badge vanished, normal calls resumed.
- **Forward Always Action**: Dialed `*645001` from SIP endpoint `4321`. Verified AstDB key `FORWARD/ALWAYS/4321` set to `5001`. Verified extensions GUI showed blue `FWD: 5001` badge. Incoming calls to `4321` immediately routed to `5001` without ringing `4321`.
- **Call Recording Toggle Action**: Answered internal call. Dialed `*1` on either SIP handset. System successfully initiated MixMonitor. WAV file stored under `/var/spool/asterisk/monitor/` and mapped to CDR records. Pressing `*1` again paused/terminated the active monitor.
- **Supervisor Barge-In**: Activated a call between `4321` and `5001`. Supervisor dialed `*574321` from extension `5002`. Supervisor was bridged into the call in barge mode (both parties can hear). Checked GUI control console and successfully initiated barge by selecting `Barge In` from the dropdown and clicking `Listen`.
