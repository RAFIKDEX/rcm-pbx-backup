import os
import csv
import calendar
import datetime
import socket
import time
import re
import threading
import json
from email.utils import parseaddr
from html import escape
import db
import mail_service
import openpyxl


def parse_caller_identity(clid, fallback_number=""):
    """Return a safe (number, display name) pair from an Asterisk Caller ID."""
    fallback = str(fallback_number or "").strip()
    raw_clid = str(clid or "").strip()
    display_name, address = parseaddr(raw_clid)
    number = str(address or fallback).strip()
    display_name = str(display_name or "").strip().strip('"').strip()

    # A bare number is not a useful display name.
    if display_name == number:
        display_name = ""
    return number or fallback or "Unknown", display_name


def normalize_missed_call_status(disposition):
    """Map Asterisk CDR dispositions to the statuses shown to users."""
    raw = str(disposition or "").strip().upper().replace("_", " ")
    status_map = {
        "NO ANSWER": "No Answer",
        "NOANSWER": "No Answer",
        "BUSY": "Busy",
        "UNAVAILABLE": "Unavailable",
        "CHANUNAVAIL": "Unavailable",
        "CONGESTION": "Unavailable",
        "FAILED": "Failed",
        "CANCEL": "Canceled",
        "CANCELED": "Canceled",
        "CANCELLED": "Canceled",
    }
    return status_map.get(raw, raw.title() if raw else "Missed")


def scheduled_report_occurrence(now, schedule, report_time="09:00", weekday=0, month_day=1):
    """Return the most recent scheduled occurrence at or before ``now``."""
    try:
        parsed_time = datetime.datetime.strptime(str(report_time or "09:00"), "%H:%M").time()
    except ValueError:
        parsed_time = datetime.time(9, 0)

    if schedule == "daily":
        occurrence = datetime.datetime.combine(now.date(), parsed_time)
        return occurrence if occurrence <= now else occurrence - datetime.timedelta(days=1)

    if schedule == "weekly":
        try:
            target_weekday = max(0, min(6, int(weekday)))
        except (TypeError, ValueError):
            target_weekday = 0
        days_since = (now.weekday() - target_weekday) % 7
        target_date = now.date() - datetime.timedelta(days=days_since)
        occurrence = datetime.datetime.combine(target_date, parsed_time)
        return occurrence if occurrence <= now else occurrence - datetime.timedelta(days=7)

    # Monthly schedules use the last calendar day when the requested day does
    # not exist (for example, day 31 in February).
    try:
        requested_day = max(1, min(31, int(month_day)))
    except (TypeError, ValueError):
        requested_day = 1
    current_day = min(requested_day, calendar.monthrange(now.year, now.month)[1])
    occurrence = datetime.datetime.combine(now.date().replace(day=current_day), parsed_time)
    if occurrence > now:
        previous_month = now.month - 1 or 12
        previous_year = now.year - 1 if now.month == 1 else now.year
        previous_day = min(requested_day, calendar.monthrange(previous_year, previous_month)[1])
        occurrence = datetime.datetime(
            previous_year, previous_month, previous_day,
            parsed_time.hour, parsed_time.minute
        )
    return occurrence


def is_cdr_report_due(now, last_sent, schedule, report_time="09:00", weekday=0, month_day=1):
    occurrence = scheduled_report_occurrence(now, schedule, report_time, weekday, month_day)
    if last_sent is None:
        # A newly enabled report waits for its next configured occurrence;
        # it must not send immediately just because the scheduler started.
        return occurrence.date() == now.date() and occurrence <= now
    return last_sent < occurrence


def cdr_direction_for_extension(src, dst, extension):
    src = str(src or "")
    dst = str(dst or "")
    extension = str(extension or "")
    if src == extension and dst == extension:
        return "Internal"
    if src == extension:
        return "Outbound"
    if dst == extension:
        return "Inbound"
    return "Other"


def write_cdr_workbook(records, title, report_path, include_direction=False):
    """Write a CDR workbook without exposing recording links."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    if include_direction:
        headers = ["Date", "Time", "Caller", "Destination", "Direction", "Duration (s)", "Status"]
    else:
        headers = ["Date", "Time", "Caller", "Destination", "Extension", "Queue", "Duration (s)", "Status"]
    ws.append(headers)

    for record in records:
        if include_direction:
            ws.append([
                record.get("Date", ""), record.get("Time", ""),
                record.get("Caller", ""), record.get("Destination", ""),
                record.get("Direction", ""), record.get("Duration (s)", 0),
                record.get("Status", "")
            ])
        else:
            ws.append([
                record.get("Date", ""), record.get("Time", ""),
                record.get("Caller", ""), record.get("Destination", ""),
                record.get("Extension", ""), record.get("Queue", ""),
                record.get("Duration (s)", 0), record.get("Status", "")
            ])

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = openpyxl.styles.Font(bold=True, color="FFFFFF")
        cell.fill = openpyxl.styles.PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        cell.alignment = openpyxl.styles.Alignment(horizontal="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)

    wb.save(report_path)


def missed_status_from_cdr(row):
    """Return a user-facing missed status, or None for a real answered call.

    The dialplan answers unavailable/busy/no-answer calls in order to play a
    prompt. Asterisk therefore writes ANSWERED for those CDR rows even though
    the extension owner did not answer.
    """
    disposition = str(row[14] if len(row) > 14 else "").strip().upper()
    if disposition != "ANSWERED":
        return normalize_missed_call_status(disposition)

    last_app = str(row[7] if len(row) > 7 else "").strip().upper()
    last_data = str(row[8] if len(row) > 8 else "").strip().lower().split(",", 1)[0]
    prompt_statuses = {
        "this_extension_is_unavailable": "Unavailable",
        "this_extension_is_busy": "Busy",
        "this_extension_is_not_answering": "No Answer",
        "this_extension_is_on_dnd": "Busy",
    }
    if last_app == "PLAYBACK":
        return prompt_statuses.get(last_data)
    return None

def get_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

def get_caller_for_callid(callid):
    conn = db.get_db()
    c = conn.cursor()
    c.execute("SELECT caller FROM rcm_queue_calls WHERE callid = ?", (callid,))
    row = c.fetchone()
    conn.close()
    if row:
        return row["caller"]
    return "Unknown"

def monitor_missed_calls():
    settings = db.get_mail_settings()
    if not settings or not settings.get("missed_calls_alert_enabled"):
        return

    threshold = settings.get("missed_calls_threshold", 5)
    
    # Get all extensions
    conn = db.get_db()
    c = conn.cursor()
    c.execute("SELECT ext, email FROM extensions")
    extensions = [dict(r) for r in c.fetchall()]
    conn.close()
    
    ext_emails = {e["ext"]: e["email"] for e in extensions if e.get("email")}
    if not ext_emails:
        return

    filepath = "/var/log/asterisk/cdr-csv/Master.csv"
    cdr_rows = []
    if os.path.exists(filepath):
        # Parse Master.csv
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                cdr_rows = list(reader)
        except Exception as e:
            print(f"[SCHEDULER] Error reading Master.csv: {e}")

    # Build uniqueid -> caller identity mapping from CDR rows. Asterisk stores
    # the name and number together in the CLID column (for example,
    # "Mostafa Alaa" <135>).
    callid_to_caller = {}
    for r in cdr_rows:
        if len(r) >= 17:
            uid = r[16].strip()
            caller_number, caller_name = parse_caller_identity(r[4], r[1])
            if uid and caller_number:
                callid_to_caller[uid] = {
                    "number": caller_number,
                    "name": caller_name,
                }

    # Get last alert timestamps for each extension
    conn = db.get_db()
    c = conn.cursor()
    last_alerts = {}
    now = datetime.datetime.now()
    for ext, email in ext_emails.items():
        c.execute("""
            SELECT timestamp FROM mail_logs 
            WHERE receiver_email = ? AND feature = 'Missed Call' AND status = 'Success'
            ORDER BY id DESC LIMIT 1
        """, (email,))
        row = c.fetchone()
        if row:
            try:
                last_alerts[ext] = datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                last_alerts[ext] = now - datetime.timedelta(hours=24)
        else:
            last_alerts[ext] = now - datetime.timedelta(hours=24)
    conn.close()

    # Track missed calls: ext -> list of dicts
    missed_calls_by_ext = {}

    # 1. Parse CDR Master.csv missed calls
    for row in cdr_rows:
        if len(row) < 15:
            continue
        dst = row[2]
        status = missed_status_from_cdr(row)
        if status and dst in ext_emails:
            start_str = row[9] # UTC start time in Asterisk CSV
            try:
                start_dt = datetime.datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue

            # Only count calls that occurred AFTER the last alert
            if start_dt > last_alerts[dst]:
                if dst not in missed_calls_by_ext:
                    missed_calls_by_ext[dst] = []
                caller_number, caller_name = parse_caller_identity(row[4], row[1])
                missed_calls_by_ext[dst].append({
                    "caller": caller_number,
                    "caller_name": caller_name,
                    "time": start_str,
                    "source": "Direct Call",
                    "status": status,
                })

    # 2. Parse Asterisk queue_log missed calls (RINGNOANSWER events)
    queue_log_path = "/var/log/asterisk/queue_log"
    if os.path.exists(queue_log_path):
        try:
            with open(queue_log_path, 'r') as f:
                for line in f:
                    parts = line.strip().split('|')
                    if len(parts) < 5:
                        continue
                    epoch_str, callid, qname, agent, event = parts[0], parts[1], parts[2], parts[3], parts[4]
                    if event == "RINGNOANSWER":
                        try:
                            ts = float(epoch_str)
                            dt = datetime.datetime.fromtimestamp(ts)
                        except Exception:
                            continue
                        
                        # Extract digits from agent interface
                        ext_match = re.search(r'\d+', agent)
                        if ext_match:
                            ext = ext_match.group(0)
                            if ext in ext_emails and dt > last_alerts[ext]:
                                if ext not in missed_calls_by_ext:
                                    missed_calls_by_ext[ext] = []
                                    
                                # Resolve caller identity from the CDR first;
                                # queue-only calls fall back to the queue table.
                                caller_info = callid_to_caller.get(callid)
                                if caller_info:
                                    caller = caller_info["number"]
                                    caller_name = caller_info["name"]
                                else:
                                    caller = get_caller_for_callid(callid)
                                    caller, caller_name = parse_caller_identity("", caller)

                                # Deduplicate queue RINGNOANSWER from direct CDR if already added
                                is_dup = False
                                for mc in missed_calls_by_ext[ext]:
                                    if mc["caller"] == caller and abs((dt - datetime.datetime.strptime(mc["time"], "%Y-%m-%d %H:%M:%S")).total_seconds()) < 60:
                                        is_dup = True
                                        break
                                        
                                if not is_dup:
                                    missed_calls_by_ext[ext].append({
                                        "caller": caller,
                                        "caller_name": caller_name,
                                        "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                        "source": f"Queue {qname}",
                                        "status": "No Answer",
                                    })
        except Exception as e:
            print(f"[SCHEDULER] Error parsing queue_log: {e}")

    # Check threshold and send emails
    for ext, calls in missed_calls_by_ext.items():
        if len(calls) >= threshold:
            email = ext_emails[ext]
            subject = f"Alert: {len(calls)} Missed Calls on Extension {ext}"
            
            call_rows_html = ""
            call_rows_text = []
            for call in calls:
                caller_number = str(call.get("caller") or "Unknown")
                caller_name = str(call.get("caller_name") or "").strip()
                caller_label = f"{caller_name} ({caller_number})" if caller_name else caller_number
                status = str(call.get("status") or "Missed")
                source = str(call.get("source") or "Call")
                call_time = str(call.get("time") or "Unknown time")
                call_rows_html += (
                    f"<li>Caller: <strong>{escape(caller_label)}</strong> "
                    f"at {escape(call_time)} &mdash; "
                    f"Status: <strong>{escape(status)}</strong> "
                    f"({escape(source)})</li>"
                )
                call_rows_text.append(
                    f"- Caller: {caller_label} | Time: {call_time} | "
                    f"Status: {status} | {source}"
                )

            safe_ext = escape(str(ext))
            
            body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background-color: #080c14; color: #fff; padding: 1.5rem;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
                    <h3 style="color: #ef4444; margin-top: 0; font-family: sans-serif;">Missed Calls Alert</h3>
                    <p style="color: #94a3b8; font-size: 0.95rem;">You have <strong>{len(calls)}</strong> missed calls on extension <strong>{safe_ext}</strong> and you did not answer them.</p>
                    <div style="background-color: #0b0f19; border: 1px solid #1e293b; padding: 1rem; border-radius: 8px; margin: 1.5rem 0;">
                        <ul style="color: #cbd5e1; margin: 0; padding-left: 1.25rem; font-size: 0.9rem; line-height: 1.6;">
                            {call_rows_html}
                        </ul>
                    </div>
                    <p style="color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; padding-top: 1rem; margin-top: 1.5rem; text-align: center;">RCM 7021 Notification System</p>
                </div>
            </body>
            </html>
            """
            body_text = (
                f"Extension {ext} has {len(calls)} missed calls.\n\n"
                + "\n".join(call_rows_text)
            )
            
            mail_service.send_email(
                receiver_email=email,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                feature="Missed Call"
            )

def check_and_send_cdr_reports():
    settings = db.get_mail_settings()
    if not settings or not settings.get("cdr_report_enabled") or not settings.get("cdr_report_email"):
        return

    email = settings.get("cdr_report_email")
    schedule = settings.get("cdr_report_schedule", "weekly")
    if schedule not in {"daily", "weekly", "monthly"}:
        schedule = "weekly"
    report_time = settings.get("cdr_report_time", "09:00")
    report_weekday = settings.get("cdr_report_weekday", 0)
    report_month_day = settings.get("cdr_report_month_day", 1)

    # Determine last send time
    conn = db.get_db()
    c = conn.cursor()
    c.execute("""
        SELECT timestamp FROM mail_logs 
        WHERE receiver_email = ? AND feature = 'CDR' AND status = 'Success'
        ORDER BY id DESC LIMIT 1
    """, (email,))
    row = c.fetchone()
    c.execute("""
        SELECT 1 FROM mail_queue
        WHERE receiver_email = ? AND feature = 'CDR' AND attempts < 3
        LIMIT 1
    """, (email,))
    pending_queue = c.fetchone() is not None
    conn.close()

    now = datetime.datetime.now()
    last_sent = None
    if row:
        try:
            last_sent = datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            last_sent = None

    if pending_queue or not is_cdr_report_due(
        now, last_sent, schedule, report_time, report_weekday, report_month_day
    ):
        return

    days_threshold = 7
    if schedule == "daily":
        days_threshold = 1
    elif schedule == "monthly":
        days_threshold = 30

    # Generate Report for the specified period
    period_name = "Daily" if schedule == "daily" else ("Monthly" if schedule == "monthly" else "Weekly")
    start_date = now - datetime.timedelta(days=days_threshold)
    start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
    
    db.sync_cdr_records()
    conn = db.get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM cdr_records WHERE start_time >= ? ORDER BY start_time DESC", (start_date_str,))
    rows = c.fetchall()
    
    c.execute("SELECT ext, name, email FROM extensions")
    extension_rows = [dict(r) for r in c.fetchall()]
    extensions = {r["ext"] for r in extension_rows}
    extension_recipients = {
        r["ext"]: r for r in extension_rows
        if str(r.get("email") or "").strip()
    }
    conn.close()

    report_records = []
    extension_report_records = {ext: [] for ext in extension_recipients}
    total_calls = 0
    answered_calls = 0
    missed_calls = 0

    for row in rows:
        total_calls += 1
        src = row["src"] or ""
        dst = row["dst"] or ""
        billsec = int(row["billsec"] or 0)
        disposition = row["status"] or ""
        start_time_str = row["start_time"] or ""
        
        try:
            start_dt = datetime.datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            dt_formatted = start_dt.strftime("%Y-%m-%d")
            tm_formatted = start_dt.strftime("%H:%M:%S")
        except Exception:
            dt_formatted = start_time_str
            tm_formatted = ""

        if disposition == "ANSWERED":
            answered_calls += 1
        else:
            missed_calls += 1

        call_ext = dst if dst in extensions else (src if src in extensions else "")
        call_queue = dst if (dst.startswith("650") or dst.startswith("659")) else ""

        report_record = {
            "Date": dt_formatted,
            "Time": tm_formatted,
            "Caller": src,
            "Destination": dst,
            "Extension": call_ext,
            "Queue": call_queue,
            "Duration (s)": billsec,
            "Status": disposition,
        }
        report_records.append(report_record)

        # An extension receives calls when it is either the source or the
        # destination. Internal calls are included once in each endpoint's
        # report and marked Internal.
        for ext in extension_recipients:
            if src == ext or dst == ext:
                extension_record = {
                    "Date": dt_formatted,
                    "Time": tm_formatted,
                    "Caller": src,
                    "Destination": dst,
                    "Direction": cdr_direction_for_extension(src, dst, ext),
                    "Duration (s)": billsec,
                    "Status": disposition,
                }
                extension_report_records[ext].append(extension_record)

    report_path = f"/tmp/{period_name}_CDR_Report.xlsx"
    try:
        write_cdr_workbook(report_records, f"{period_name} CDR Report", report_path)
    except Exception as e:
        print(f"[SCHEDULER] Error writing XLSX file: {e}")
        return

    # Send Email
    subject = f"{period_name} CDR Report - {start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"
    
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #080c14; color: #fff; padding: 1.5rem;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
            <h3 style="color: #3b82f6; margin-top: 0;">{period_name} Call Detail Records (CDR) Report</h3>
            <p style="color: #94a3b8; font-size: 0.95rem;">Please find attached the CDR report in Excel (.xlsx) format for the period from <strong>{start_date.strftime('%Y-%m-%d')}</strong> to <strong>{now.strftime('%Y-%m-%d')}</strong>.</p>
            
            <div style="background-color: #0b0f19; border: 1px solid #1e293b; padding: 1.25rem; border-radius: 8px; margin: 1.5rem 0;">
                <h4 style="margin: 0 0 0.75rem 0; color: #fff;">Summary Statistics</h4>
                <table style="width: 100%; border-collapse: collapse; color: #cbd5e1; font-size: 0.9rem;">
                    <tr>
                        <td style="padding: 0.35rem 0;">Total Calls:</td>
                        <td style="text-align: right; font-weight: bold; color: #fff;">{total_calls}</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.35rem 0;">Answered Calls:</td>
                        <td style="text-align: right; font-weight: bold; color: #10b981;">{answered_calls}</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.35rem 0;">Missed/Failed Calls:</td>
                        <td style="text-align: right; font-weight: bold; color: #ef4444;">{missed_calls}</td>
                    </tr>
                </table>
            </div>
            
            <p style="color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; padding-top: 1rem; margin-top: 1.5rem; text-align: center;">RCM 7021 Reporting Engine</p>
        </div>
    </body>
    </html>
    """
    body_text = f"Attached is the {period_name.lower()} CDR report from {start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}. Total calls: {total_calls}."
    
    attachments = [{"path": report_path, "filename": f"{period_name}_CDR_Report_{now.strftime('%Y%m%d')}.xlsx"}]
    
    success, mail_err = mail_service.send_email(
        receiver_email=email,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        attachments=attachments,
        feature="CDR"
    )

    if success:
        if os.path.exists(report_path):
            try:
                os.remove(report_path)
            except Exception:
                pass

    # Send one additional, private CDR workbook to every extension that has
    # an email address. It contains only calls where that extension was the
    # caller or destination, and has no recording link column.
    for ext, extension_data in extension_recipients.items():
        records = extension_report_records.get(ext) or []
        if not records:
            continue

        safe_ext = re.sub(r"[^A-Za-z0-9_-]", "_", str(ext))
        extension_name = str(extension_data.get("name") or "").strip()
        display_label = f"{ext} ({extension_name})" if extension_name else str(ext)
        extension_path = f"/tmp/{period_name}_CDR_Extension_{safe_ext}.xlsx"
        try:
            write_cdr_workbook(
                records,
                f"{period_name} Extension {ext}",
                extension_path,
                include_direction=True,
            )
        except Exception as e:
            print(f"[SCHEDULER] Error writing CDR workbook for extension {ext}: {e}")
            continue

        extension_subject = (
            f"{period_name} CDR Report - Extension {display_label} - "
            f"{start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"
        )
        extension_body_html = f"""
        <html><body style="font-family: Arial, sans-serif;">
            <h3>{escape(period_name)} CDR Report - Extension {escape(display_label)}</h3>
            <p>This report contains only inbound, outbound, and internal calls
               for extension <strong>{escape(str(ext))}</strong>.</p>
            <p>Period: <strong>{escape(start_date.strftime('%Y-%m-%d'))}</strong>
               to <strong>{escape(now.strftime('%Y-%m-%d'))}</strong>.</p>
        </body></html>
        """
        extension_body_text = (
            f"CDR report for extension {display_label}. "
            f"Period: {start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}. "
            f"Calls: {len(records)}."
        )
        extension_attachments = [{
            "path": extension_path,
            "filename": f"{period_name}_CDR_Extension_{safe_ext}_{now.strftime('%Y%m%d')}.xlsx",
        }]
        extension_success, _ = mail_service.send_email(
            receiver_email=extension_data["email"].strip(),
            subject=extension_subject,
            body_html=extension_body_html,
            body_text=extension_body_text,
            attachments=extension_attachments,
            feature="CDR Extension",
        )
        if extension_success and os.path.exists(extension_path):
            try:
                os.remove(extension_path)
            except Exception:
                pass

def process_mail_queue():
    pending = db.get_pending_mail_queue()
    if not pending:
        return

    print(f"[SCHEDULER] Processing mail queue. {len(pending)} pending emails found.")
    for item in pending:
        queue_id = item["id"]
        receiver = item["receiver_email"]
        subject = item["subject"]
        body_html = item["body_html"]
        body_text = item["body_text"] or ""
        feature = item["feature"]
        attempts = item["attempts"]
        
        attachments = []
        if item["attachments_json"]:
            try:
                attachments = json.loads(item["attachments_json"])
            except Exception as e:
                print(f"[SCHEDULER] Failed to parse attachments for queue item {queue_id}: {e}")

        success, err = mail_service.send_email(
            receiver_email=receiver,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=attachments,
            feature=feature,
            is_retry=True
        )

        new_attempts = attempts + 1
        if success or new_attempts >= 3:
            if success:
                print(f"[SCHEDULER] Queue item {queue_id} successfully sent to {receiver}.")
            else:
                print(f"[SCHEDULER] Queue item {queue_id} failed 3 times to {receiver}. Removing from queue. Last error: {err}")
                db.log_email(receiver, "", subject, "Failed (Permanent)", f"Max retries reached: {err}", feature)
            db.delete_from_mail_queue(queue_id)
            for att in attachments:
                att_path = att.get("path")
                if att_path and att_path.startswith("/tmp/") and os.path.exists(att_path):
                    try:
                        os.remove(att_path)
                    except Exception:
                        pass
        else:
            print(f"[SCHEDULER] Queue item {queue_id} failed to send to {receiver}. Attempt {new_attempts}/3. Error: {err}")
            backoff_minutes = new_attempts * 5
            db.update_mail_queue_attempt(queue_id, new_attempts, next_retry_minutes=backoff_minutes)

def start_background_scheduler():
    def run_scheduler():
        print("[SCHEDULER] Background email scheduler thread started.")
        time.sleep(15)
        while True:
            try:
                process_mail_queue()
            except Exception as e:
                print(f"[SCHEDULER] Error in process_mail_queue: {e}")

            try:
                monitor_missed_calls()
            except Exception as e:
                print(f"[SCHEDULER] Error in monitor_missed_calls: {e}")
                
            try:
                check_and_send_cdr_reports()
            except Exception as e:
                print(f"[SCHEDULER] Error in check_and_send_cdr_reports: {e}")
                
            time.sleep(60)

    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    try:
        from dex.jobs import start_dex_worker
        start_dex_worker()
    except Exception as exc:
        print(f"[SCHEDULER] DEX worker was not started: {exc}")
