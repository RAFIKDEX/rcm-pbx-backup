# RCM Project Context

This file is the first reference for future RCM work. Read it before making code changes, then consult the more specific documentation file for the area being modified.

## Overall Architecture

RCM is a Flask-based PBX and call-center management application for Asterisk/PJSIP. It is a server-rendered web app with Jinja templates, SQLite persistence, generated Asterisk configuration files, Asterisk CLI commands, and an AMI event collector for live queue/call-center state.

The project is compact and mostly organized by file rather than package:

- Web routes, form handling, JSON APIs, and page orchestration are centralized in `app.py`.
- Main persistence and JSON config helpers are centralized in `db.py`.
- Asterisk CLI, config writers, dialplan generators, and AMI helpers are centralized in `asterisk_helper.py`.
- Queue analytics and live call-center persistence are centralized in `rcm_queue_db.py`.
- The AMI queue event daemon is `rcm_queue_collector.py`.
- Email delivery is handled by `mail_service.py`.
- Background email/report tasks are handled by `scheduler_service.py`.
- UI is rendered from `templates/` and styled mainly by `static/css/style.css`.

## Main Modules

| File | Purpose |
| --- | --- |
| `app.py` | Flask app, route handlers, auth flow, UI pages, API endpoints, feature workflows. |
| `db.py` | Main SQLite schema, migrations, extension/trunk/user helpers, JSON-backed PBX config helpers, CDR sync helpers. |
| `asterisk_helper.py` | Asterisk CLI execution, config/dialplan generation, live channel/status parsing, AMI helper, system/time/network helpers. |
| `rcm_queue_db.py` | Queue database schema, queue call lifecycle, live dashboard, queue stats, agent analytics, queue log import. |
| `rcm_queue_collector.py` | AMI listener daemon for queue/call/agent events. |
| `mail_service.py` | SMTP delivery, encrypted SMTP password handling, email logging/queueing. |
| `scheduler_service.py` | Background mail retry, missed-call alert monitoring, scheduled CDR reports. |
| `rcm_wsgi.wsgi` | WSGI entry point for deployed app. |

## How The App Starts

Development entry point:

```bash
python app.py
```

This starts Flask on `0.0.0.0:5000` when run directly.

WSGI entry point:

```text
rcm_wsgi.wsgi
```

The WSGI file adds `/root/RCM_7021` to `sys.path`, sets the working directory, and imports `app` as `application`.

Import/startup side effects in `app.py`:

- Creates the Flask app and sets a hardcoded session secret.
- Calls `db.init_db()` to create/migrate the main SQLite database and seed default users/feature codes.
- Starts `scheduler_service.start_background_scheduler()` unless `unittest` or `pytest` is loaded.
- Calls `run_migrations()` to strip legacy generated dialplan sections from configured Asterisk extension files.

The queue collector is separate:

```bash
python rcm_queue_collector.py
```

It initializes `rcm_queue.db`, connects to Asterisk AMI, syncs current state, then processes AMI events continuously.

## Runtime Assumptions

- Project root is `/root/RCM_7021`.
- Main DB path is `/root/RCM_7021/rcm_7021.db`.
- Queue DB path is `/root/RCM_7021/rcm_queue.db`.
- Asterisk is installed and available through `asterisk -rx`.
- Asterisk config files are writable under `/etc/asterisk`.
- Asterisk CDR CSV exists at `/var/log/asterisk/cdr-csv/Master.csv`.
- Asterisk recordings are stored in `/var/spool/asterisk/monitor`.
- AMI listens on `127.0.0.1:5038`.
- AMI credentials are currently hardcoded as `guiuser/admin`.
- Logo files are expected under `/var/www/html`.
- Font Awesome and Google Fonts are loaded from public CDNs.

## Known Risks

- No Git repository was detected in the project root.
- No README, requirements file, Dockerfile, systemd unit, or environment example exists.
- Large modules mix routing, persistence, validation, business logic, and rendering orchestration.
- Secrets are hardcoded in source code.
- Many absolute production paths are hardcoded.
- App startup performs side effects at import time.
- Main DB and queue DB overlap conceptually in call-center data.
- Runtime depends on real Asterisk behavior; tests mock parts of this but not all.
- External CDN assets can break offline deployments.
- Authorization is basic and not consistently centralized.

## Future Work Rules

For every future task:

1. Read this file first, then check the specific documentation file for the affected area.
2. Search the whole project before assuming a feature does not exist.
3. Never rewrite large parts of the project unless explicitly requested.
4. Before changing code, identify affected files, explain why they need modification, and check side effects.
5. Preserve existing architecture, coding style, templates, helper functions, and generated config conventions.
6. Reuse existing helper functions whenever possible.
7. Do not duplicate logic if similar behavior already exists.
8. If multiple implementation approaches exist, briefly explain pros and cons before coding.
9. For new features, update UI/navigation, database, APIs, and Asterisk config generation when required.
10. After each task, summarize files changed, database changes, API changes, UI changes, Asterisk config changes, and risks.
11. Update these documentation files whenever architecture or flow changes.
