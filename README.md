# RCM 7021 - Call Center & PBX Management System

Welcome to the **RCM 7021** project. This is a comprehensive, web-based Private Branch Exchange (PBX) and Call Center management dashboard built on top of Asterisk. It provides a modern interface for configuring extensions, trunks, inbound/outbound routes, queues, and provides deep analytics for call center operations.

## 📌 Project Overview
RCM 7021 bridges the gap between Asterisk's powerful (but complex) configuration files and a user-friendly graphical interface. It handles live monitoring of queues, agent performance metrics, call journey timelines, and system configuration generation.

## 🛠️ Tech Stack
*   **Backend:** Python 3, Flask (Web Framework)
*   **Database:** SQLite3 (Dual-database architecture)
*   **Frontend:** HTML5, CSS3, Vanilla JavaScript, Jinja2 Templates (No heavy frontend frameworks like React/Vue).
*   **Telephony Engine:** Asterisk (PJSIP channel driver)
*   **Background Services:** Systemd-managed Python daemons (e.g., `rcm-queue-collector`)

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

*   **`rcm-queue-collector` (`/root/RCM_7021/rcm-queue-collector.py`)**
    *   Tails the Asterisk `/var/log/asterisk/queue_log`.
    *   Translates events (ENTERQUEUE, RINGNOANSWER, COMPLETEAGENT, HOLD, UNHOLD) into SQLite records in `rcm_queue.db`.
    *   Implements "Smart Detection" for Agent Rejections vs. Missed Rings.
    *   Calculates precise `wait_time`, `hold_time`, and pure `talk_time` (Speaking Time).

---

## 📁 Directory Structure

```text
/root/RCM_7021/
├── app.py                     # Main Flask Application & API Routes
├── db.py                      # Core PBX Database Helper (rcm_7021.db)
├── rcm_queue_db.py            # Queue & Call Center Database Helper (rcm_queue.db)
├── asterisk_helper.py         # Utilities for writing to Asterisk .conf files
├── cdr_journey.py             # Logic for building the Call Details Timeline
├── FEATURE_INDEX.md           # Master index of where specific features are stored (JSON/DB)
├── static/
│   ├── css/style.css          # Main UI Styling (Dark PBX Dashboard Theme)
│   └── js/                    # Client-side logic
├── templates/                 # Jinja2 HTML Templates (e.g., queue_stats.html)
└── ...
```

---

## 🎨 Frontend & Design Philosophy
*   **Consistent UI:** Adheres strictly to the established Dark PBX Dashboard theme defined in `style.css`.
*   **No "AI-Template" feel:** Avoids excessive gradients, unnecessary emojis, or exaggerated shadows.
*   **Functional Animations:** CSS transitions (150-300ms) are used functionally (modals, active call highlights) rather than decoratively.

---

## 🚀 Key Features
*   **Live Queue Dashboard:** Real-time visibility into callers waiting, agent statuses, and live SLA tracking.
*   **Agent Performance Analytics:** Deep insights into Occupancy, Productivity, Total Answered, and "Speaking Time" (Hold time is explicitly decoupled from productive talk time).
*   **Call Journey Timelines:** A forensic step-by-step breakdown of every call's lifecycle from entering the PBX to the final hangup.
*   **PBX Configuration:** GUI management of Extensions, Trunks, Ring Groups, IVRs, Announcements, and Paging.
