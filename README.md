# RCM 7021 - Call Center & PBX Management System

Welcome to the **RCM 7021** project. This is a highly advanced, web-based Private Branch Exchange (PBX) and Call Center management dashboard built on top of Asterisk. It provides a modern interface for configuring everything from basic extensions to complex call center queues and post-call surveys, alongside deep, real-time analytics.

## 📌 Project Overview
RCM 7021 bridges the gap between Asterisk's powerful (but complex) configuration files and a user-friendly graphical interface. It handles live monitoring of queues, agent performance metrics, call journey timelines, and system configuration generation—all without requiring the user to touch a terminal.

## 🌟 Comprehensive Feature List
This system manages the entire lifecycle of a PBX. Every module includes its own UI, database/JSON storage, and Asterisk dialplan generator:

### Core PBX Features
*   **Extensions Management:** Create, edit, and delete SIP/PJSIP extensions. Supports dynamic/static assignments and voicemail.
*   **Trunks:** SIP trunk configurations for connecting to external VoIP providers or gateways.
*   **Inbound Routes:** Direct incoming calls (DIDs) to specific destinations (Extensions, Queues, IVRs, etc.).
*   **Outbound Routes:** Manage outbound dialing rules and patterns (powered by external generator script).
*   **Ring Groups:** Group multiple extensions to ring simultaneously or sequentially.
*   **IVR (Interactive Voice Response):** Build complex automated attendants with multi-level menus and digit timeouts.
*   **Time Conditions & Office Hours:** Route calls differently based on business hours, holidays, and custom schedules.
*   **Music on Hold (MoH):** Upload, convert, and manage hold music tracks.
*   **System Recordings (Media Center):** Manage custom voice prompts and announcements.
*   **Paging & Intercom:** Broadcast live audio to specific groups of desk phones.
*   **Pickup Groups:** Allow users to intercept ringing calls on other extensions.
*   **Speed Dials:** System-wide short codes for quick dialing.

### Call Center & Advanced Routing
*   **Queues:** Advanced call center queues with customizable strategies (ringall, rrmemory, leastrecent), SLAs, and timeouts.
*   **Live Queue Dashboard:** Real-time visibility into callers waiting, active agents, queue lengths, and SLA adherence.
*   **Agent Management:** Track agent logins, logouts, pauses, and breaks dynamically.
*   **Post-Call Surveys:** Automated surveys played to the caller after the agent hangs up to measure CSAT, integrated with its own reporting engine.

### Analytics & Reporting
*   **Queue Statistics:** Deep historical analytics for queue performance (Ans Rate, Abandon Rate, SLA %).
*   **Agent Performance (Occupancy):** Precise tracking of Agent Productivity, Total Answered, and true "Speaking Time" (where Hold time is correctly isolated).
*   **Call Flow Details (Timeline):** A forensic, second-by-second timeline of every call's journey from `ENTERQUEUE` to `COMPLETE`, including precise Wait, Talk, and Hold times.
*   **Advanced CDRs:** Detailed Call Detail Records for all PBX activity.

### Security & System Administration
*   **SIP Security & Firewall:** Integrated SIP attack detection, firewall rules management, and Fail2ban configurations.
*   **User & Privilege Management:** Role-based access control for the web interface.
*   **LDAP Integration:** Synchronize users/extensions with Active Directory.
*   **Network & PBX Settings:** Modify core system parameters and network interfaces.

---

## 🛠️ Tech Stack
*   **Backend:** Python 3, Flask (Web Framework)
*   **Database:** SQLite3 (Dual-database architecture)
*   **Frontend:** HTML5, CSS3, Vanilla JavaScript, Jinja2 Templates (No heavy frontend frameworks like React/Vue).
*   **Telephony Engine:** Asterisk (PJSIP channel driver)
*   **Background Services:** Systemd-managed Python daemons (e.g., `rcm-queue-collector.service`)

---

## 🗄️ Database Architecture
The project strictly enforces a dual-database design to separate legacy configuration from live queue metrics:

1.  **`rcm_7021.db` (Schema Owner: `db.py`)**
    *   Stores core PBX configuration (Extensions, Trunks, Ring Groups, IVRs, etc.).
    *   Contains legacy queue logging tables which are largely deprecated.

2.  **`rcm_queue.db` (Schema Owner: `rcm_queue_db.py`)**
    *   The single source of truth for **all Live Queue data and Call Analytics**.
    *   Tables include: `queues`, `queue_calls`, `queue_agents`, `queue_agent_events`, `queue_live`, `queue_call_positions`.
    *   *Note: Direct SQL JOINs between `rcm_7021.db` and `rcm_queue.db` are prohibited.*

---

## ⚙️ Asterisk Integration & Configuration Generation

### 1. Marker-Based Config Writing
The system modifies Asterisk configuration files (located in `/etc/asterisk/`, specifically files like `pjsip.gui.endpoint.conf`, `extensions_gui.conf`) using a **Marker-Based** system. 
*   Files are never overwritten from scratch.
*   Functions in `asterisk_helper.py` (e.g., `write_extension_configs`) use dynamic start/end markers (e.g., `; --- BEGIN EXTENSION 6001 ---`) to safely inject or delete specific blocks of configuration without breaking other manual configurations.

### 2. DEFER_RELOAD (Pending Changes System)
To prevent dropping active calls, RCM 7021 does **not** instantly reload Asterisk when a user changes a setting.
*   Instead, changes are written to the `.conf` files and logged as "Pending Changes" (using `DEFER_RELOAD`).
*   The user must explicitly click an "Apply Changes" button (`/api/apply-changes`) to trigger `pjsip reload` or `dialplan reload`.

### 3. Outbound Routes
The generation of dialplans for outbound routes is managed by an external shell script: `/usr/local/bin/rcm_gen_outbound_routes.sh`. Python code does not generate this directly.

---

## 🔄 Background Daemons
The system relies on background services to bridge real-time Asterisk events with the web UI:

*   **`rcm-queue-collector` (`/root/RCM_7021/rcm_queue_collector.py`)**
    *   Tails the Asterisk `/var/log/asterisk/queue_log`.
    *   Translates events (ENTERQUEUE, RINGNOANSWER, COMPLETEAGENT, HOLD, UNHOLD) into SQLite records in `rcm_queue.db`.
    *   Implements "Smart Detection" for Agent Rejections vs. Missed Rings.
    *   Calculates precise `wait_time`, `hold_time`, and pure `talk_time` (Speaking Time).

---

## 📁 Directory Structure Overview

```text
/root/RCM_7021/
├── app.py                     # Main Flask Application & API Routes
├── db.py                      # Core PBX Database Helper (rcm_7021.db)
├── rcm_queue_db.py            # Queue & Call Center Database Helper (rcm_queue.db)
├── asterisk_helper.py         # Utilities for writing to Asterisk .conf files
├── cdr_journey.py             # Logic for building the Call Details Timeline
├── survey_routes.py           # Logic for Post-Call Surveys
├── sip_security_manager.py    # SIP Intrusion detection and Fail2ban integration
├── static/
│   ├── css/style.css          # Main UI Styling (Dark PBX Dashboard Theme)
│   └── js/                    # Client-side logic
├── templates/                 # Jinja2 HTML Templates (e.g., queue_stats.html, ivr_form.html, etc.)
└── ...
```

---

## 🎨 Frontend & Design Philosophy
*   **Consistent UI:** Adheres strictly to the established Dark PBX Dashboard theme defined in `style.css`.
*   **No "AI-Template" feel:** Avoids excessive gradients, unnecessary emojis, or exaggerated shadows.
*   **Functional Animations:** CSS transitions (150-300ms) are used functionally (modals, active call highlights) rather than decoratively.
