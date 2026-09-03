"""User-facing reconstruction of a complete PBX call journey.

This module deliberately knows nothing about HTML.  It produces the existing
timeline payload (cards, details and agent-attempt rows) while combining all
available CDR legs and queue events into one business-level story.
"""

from datetime import datetime
import re


ATTEMPT_STATUSES = {
    "Answered",
    "Cancelled",
    "No Answer",
    "Caller Hangup",
    "Queue Timeout",
}


def _value(row, key, default=""):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = row.get(key, default) if hasattr(row, "get") else default
    return default if value is None else value


def _text(value):
    return str(value or "").strip()


def _time(value):
    return _text(value)


def _time_key(value):
    value = _time(value)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.max


def _format_duration(seconds):
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _format_duration_hms(seconds):
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _parse_duration_time(value):
    """Parse the timestamp formats emitted by Asterisk and SQLite."""
    value = _text(value)
    if not value or value.startswith("0000-00-00"):
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def _duration_event_type(event):
    value = _text(_value(event, "event_type") or _value(event, "event"))
    return re.sub(r"[^A-Z]", "", value.upper())


def _duration_event_time(event):
    return _parse_duration_time(_value(event, "timestamp") or _value(event, "time"))


def _duration_flag(event, *keys):
    """Return an explicitly supplied boolean without guessing from MOH."""
    for key in keys:
        value = _value(event, key, None)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return value
        return _text(value).lower() not in {"0", "false", "no", "none", "internal"}
    return None


def _merge_duration_intervals(intervals):
    """Normalize intervals into a sorted, non-overlapping union."""
    normalized = []
    for start, end in intervals or []:
        if not start or not end or end <= start:
            continue
        normalized.append((start, end))
    normalized.sort(key=lambda item: item[0])
    merged = []
    for start, end in normalized:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _subtract_duration_intervals(base, exclusions):
    """Subtract normalized exclusions from one interval."""
    remaining = [base]
    for cut_start, cut_end in _merge_duration_intervals(exclusions):
        next_remaining = []
        for start, end in remaining:
            if cut_end <= start or cut_start >= end:
                next_remaining.append((start, end))
                continue
            if start < cut_start:
                next_remaining.append((start, min(cut_start, end)))
            if cut_end < end:
                next_remaining.append((max(cut_end, start), end))
        remaining = next_remaining
    return remaining


def _duration_seconds(intervals):
    return sum(max(0, int((end - start).total_seconds())) for start, end in intervals or [])


def calculate_call_durations(cdr_records, queue_call=None, queue_events=None, *, legacy_fallback=False, now=None):
    """Calculate the three Call Details durations from a complete linked journey.

    ``Call Time`` is one wall-clock range.  ``Talk Time`` is built from real
    caller bridge intervals (QueueLog CONNECT, AMI/CEL BridgeEnter, etc.) and
    ``Hold Time`` is built only from explicit caller HOLD/UNHOLD events.  CDR
    billsec is used only as a conservative legacy fallback when no event
    evidence exists; it is never summed across channels.
    """
    rows = [dict(row) for row in (cdr_records or []) if row]
    queue_call = dict(queue_call or {})
    related_calls = [dict(item) for item in (queue_call.get("_related_queue_calls") or [queue_call]) if item]
    events = [dict(event) for event in (queue_events or []) if event]

    start_candidates = []
    end_candidates = []
    for row in rows:
        start = _parse_duration_time(_value(row, "start_time"))
        end = _parse_duration_time(_value(row, "end_time"))
        if start:
            start_candidates.append(start)
        if end:
            end_candidates.append(end)
    for item in related_calls:
        start = _parse_duration_time(_value(item, "entry_time") or _value(item, "start_time"))
        end = _parse_duration_time(_value(item, "hangup_time") or _value(item, "end_time"))
        if start:
            start_candidates.append(start)
        if end:
            end_candidates.append(end)
    for event in events:
        event_type = _duration_event_type(event)
        event_time = _duration_event_time(event)
        if event_time and event_type in {"HANGUP", "COMPLETE", "ABANDON", "EXITWITHTIMEOUT", "EXITWITHKEY", "EXITEMPTY"}:
            end_candidates.append(event_time)

    start_dt = min(start_candidates) if start_candidates else None
    end_dt = max(end_candidates) if end_candidates else None
    if start_dt and not end_dt:
        # Active calls are rendered using a moving wall-clock end; this value
        # is not persisted as a final duration until a real end is present.
        end_dt = now or datetime.now()
    if start_dt and end_dt and end_dt < start_dt:
        end_dt = start_dt
    call_time = max(0, int((end_dt - start_dt).total_seconds())) if start_dt and end_dt else 0

    ordered_events = sorted(
        ((event, _duration_event_time(event), _duration_event_type(event)) for event in events),
        key=lambda item: item[1] or datetime.max,
    )
    answer_times = []
    for row in rows:
        if _normal_status(_value(row, "status")) == "ANSWERED":
            answer = _parse_duration_time(_value(row, "answer_time"))
            if answer:
                answer_times.append(answer)
    for item in related_calls:
        answer = _parse_duration_time(_value(item, "answer_time"))
        if answer and _normal_status(_value(item, "status")) == "ANSWERED":
            answer_times.append(answer)
    for event, event_time, event_type in ordered_events:
        if event_time and event_type in {"ANSWER", "CONNECT"}:
            answer_times.append(event_time)
    first_answer = min(answer_times) if answer_times else None

    # Asterisk may mark the inbound channel as ANSWERED when the IVR starts.
    # That is not the caller's meaningful answer for reporting purposes: the
    # CDR wait time should continue through the IVR until an agent/callee
    # answers.  Queue ANSWER/CONNECT events are the strongest evidence; for a
    # non-queue call, use an answered CDR destination leg while excluding
    # technical Playback/IVR helper applications.
    human_answer_times = []
    for event, event_time, event_type in ordered_events:
        if not event_time:
            continue
        if event_type == "CONNECT":
            human_answer_times.append(event_time)
        elif event_type == "ANSWER" and _text(_value(event, "agent")):
            human_answer_times.append(event_time)
    for item in related_calls:
        answer = _parse_duration_time(_value(item, "answer_time"))
        if not answer or _normal_status(_value(item, "status")) != "ANSWERED":
            continue
        if _text(_value(item, "agent")):
            human_answer_times.append(answer)
    for row in rows:
        if not _is_meaningful_answer_row(row):
            continue
        answer = _parse_duration_time(_value(row, "answer_time"))
        if answer:
            human_answer_times.append(answer)
    human_answer = min(human_answer_times) if human_answer_times else None
    wait_end = human_answer or end_dt
    wait_time = max(0, int((wait_end - start_dt).total_seconds())) if start_dt and wait_end else 0

    # CONNECT is QueueLog's caller-to-agent bridge evidence.  BridgeEnter and
    # BridgeLeave are the equivalent low-level AMI/CEL evidence.  ANSWER by
    # itself intentionally does not open a talk interval.
    bridge_start = None
    bridge_intervals = []
    explicit_bridge_evidence = False
    hold_start = None
    hold_intervals = []
    bridge_was_active_before_hold = False
    for event, event_time, event_type in ordered_events:
        if not event_time or (start_dt and event_time < start_dt):
            continue
        if end_dt and event_time > end_dt:
            continue
        caller_flag = _duration_flag(event, "caller_in_bridge", "original_caller", "affects_caller")
        if caller_flag is False:
            continue

        if event_type in {"BRIDGE", "BRIDGEENTER", "CONNECT"}:
            explicit_bridge_evidence = True
            if bridge_start is None:
                bridge_start = event_time
            if hold_start is not None:
                hold_intervals.append((hold_start, event_time))
                hold_start = None
            continue

        if event_type in {"UNBRIDGE", "BRIDGELEAVE", "BRIDGEEXIT", "BRIDGEEND", "HANGUP", "COMPLETE", "ABANDON", "EXITWITHTIMEOUT", "EXITWITHKEY", "EXITEMPTY"}:
            if bridge_start is not None:
                bridge_intervals.append((bridge_start, event_time))
                bridge_start = None
            if hold_start is not None and event_type in {"HANGUP", "COMPLETE", "ABANDON", "EXITWITHTIMEOUT", "EXITWITHKEY", "EXITEMPTY"}:
                hold_intervals.append((hold_start, event_time))
                hold_start = None
            continue

        # A transfer, queue re-entry, or a new ring ends the caller-facing
        # bridge. It does not imply Hold; only a real HOLD event does that.
        if event_type in {"TRANSFER", "ENTERQUEUE", "RING", "RINGNOANSWER", "RINGCANCELED"}:
            if bridge_start is not None:
                bridge_intervals.append((bridge_start, event_time))
                bridge_start = None
            continue

        if event_type in {"HOLD", "MUSICONHOLDSTART"}:
            # Queue/Asterisk can persist ANSWER and HOLD/UNHOLD on different
            # event streams.  Hold requires a real HOLD event after answer;
            # it must not additionally depend on CONNECT being present in the
            # same queue-leg stream.  Talk still requires explicit bridge
            # evidence below, so an ANSWER-only channel cannot create Talk.
            if first_answer and event_time >= first_answer and hold_start is None:
                bridge_was_active_before_hold = bridge_start is not None
                if bridge_start is not None:
                    bridge_intervals.append((bridge_start, event_time))
                    bridge_start = None
                hold_start = event_time
            continue

        if event_type in {"UNHOLD", "MUSICONHOLDSTOP"}:
            if hold_start is not None:
                hold_intervals.append((hold_start, event_time))
                hold_start = None
                if bridge_was_active_before_hold:
                    bridge_start = event_time
                bridge_was_active_before_hold = False
            continue

    if bridge_start is not None and end_dt:
        bridge_intervals.append((bridge_start, end_dt))
    if hold_start is not None and end_dt:
        hold_intervals.append((hold_start, end_dt))

    bridge_intervals = _merge_duration_intervals(bridge_intervals)
    hold_intervals = _merge_duration_intervals(hold_intervals)
    hold_seconds = _duration_seconds(hold_intervals)
    if not hold_intervals and first_answer:
        # queue_calls.hold_time is written by db_call_hold_event only after a
        # persisted HOLD/UNHOLD pair. Use it only when the raw pair is absent
        # from the loaded event set, and never add it to interval evidence.
        persisted_hold = 0
        for item in related_calls:
            try:
                persisted_hold += max(0, int(float(_value(item, "hold_time") or 0)))
            except (TypeError, ValueError):
                continue
        hold_seconds = persisted_hold
    # A hold is authoritative over any technical bridge record.
    talk_intervals = []
    for interval in bridge_intervals:
        talk_intervals.extend(_subtract_duration_intervals(interval, hold_intervals))
    talk_intervals = _merge_duration_intervals(talk_intervals)

    # Legacy CDR/queue rows do not contain enough evidence for exact net talk.
    # Keep a safe, non-summed fallback for old records, but never use it when
    # the event stream explicitly says that an agent answered without a bridge.
    has_answer_event = any(event_type == "ANSWER" for _, _, event_type in ordered_events)
    if not talk_intervals and not explicit_bridge_evidence and legacy_fallback and not has_answer_event:
        fallback_values = []
        for row in rows:
            if _is_meaningful_answer_row(row):
                try:
                    fallback_values.append(max(0, int(float(_value(row, "billsec") or 0))))
                except (TypeError, ValueError):
                    pass
        for item in related_calls:
            if _normal_status(_value(item, "status")) == "ANSWERED":
                try:
                    fallback_values.append(max(0, int(float(_value(item, "talk_time") or 0))))
                except (TypeError, ValueError):
                    pass
        fallback_talk = max(fallback_values, default=0)
    else:
        fallback_talk = 0

    return {
        "call_time": call_time,
        "wait_time": wait_time,
        "talk_time": _duration_seconds(talk_intervals) if talk_intervals else fallback_talk,
        "hold_time": hold_seconds,
        "call_time_display": _format_duration_hms(call_time),
        "wait_time_display": _format_duration_hms(wait_time),
        "talk_time_display": _format_duration_hms(_duration_seconds(talk_intervals) if talk_intervals else fallback_talk),
        "hold_time_display": _format_duration_hms(hold_seconds),
        "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "",
        "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else "",
    }


def _normal_status(value):
    return _text(value).upper().replace("_", " ")


def _is_meaningful_answer_row(row):
    """Identify a real destination answer, excluding helper applications."""
    if _normal_status(_value(row, "status")) != "ANSWERED":
        return False
    context = _text(_value(row, "dcontext")).lower()
    app = _text(_value(row, "lastapp")).lower()
    # A real Dial leg is commonly written in the ``recording`` context after
    # MixMonitor starts.  Context alone must not turn an answered extension
    # call into No Answer; helper applications are filtered explicitly below.
    if context.startswith("ivr-") and app not in {"dial", "appdial", "local", "bridge"}:
        return False
    if app in {"answer", "background", "back-ground", "wait", "playback", "queue", "hangup"}:
        return False
    destination_channel = _text(_value(row, "dstchannel"))
    if not app and not context and not destination_channel:
        # Legacy rows sometimes contain only dst/billsec. Preserve the old
        # conservative fallback for those rows while still rejecting known
        # technical applications above.
        return bool(_text(_value(row, "dst")))
    return bool(app in {"dial", "appdial", "local", "bridge"} or destination_channel)


def _display_party(number, extension_names):
    number = _text(number) or "Unknown"
    name = _text(extension_names.get(number))
    return f"{number} ({name})" if name and name != number else number


def _safe_name(value, fallback="Unknown"):
    value = _text(value)
    return value or fallback


def _endpoint(value):
    """Extract an Asterisk endpoint from PJSIP/endpoint-xxxx text."""
    value = _text(value)
    match = re.search(r"(?:^|[&/])PJSIP/([^,;&\s/-]+)", value, re.IGNORECASE)
    return match.group(1) if match else ""


def _endpoints(value):
    value = _text(value)
    return [item for item in re.findall(r"PJSIP/([^,;&\s/-]+)", value, re.IGNORECASE) if item]


def _is_number(value):
    return bool(re.fullmatch(r"[+*#0-9A-Za-z_.-]+", _text(value)))


def _parse_path(userfield):
    """Parse structured metadata written by the generated dialplan."""
    path = []
    for token in _text(userfield).replace("|", "~").split("~"):
        token = token.strip()
        if not token or ":" not in token:
            continue
        kind, payload = token.split(":", 1)
        kind = kind.strip().upper()
        parts = payload.split(":")
        if kind == "IVR" and len(parts) >= 2:
            path.append({"kind": "ivr", "number": parts[0], "name": ":".join(parts[1:]) or parts[0]})
        elif kind == "DIGIT" and parts:
            path.append({"kind": "digit", "digit": parts[0]})
        elif kind == "DEST" and len(parts) >= 2:
            path.append({"kind": "destination", "type": parts[0].lower(), "number": ":".join(parts[1:])})
        elif kind == "FORWARD" and len(parts) >= 3:
            path.append({"kind": "forward", "source": parts[0], "reason": parts[1].lower(), "target": ":".join(parts[2:])})
        elif kind in {"INBOUND", "TRUNK"} and len(parts) >= 2:
            path.append({"kind": "inbound", "trunk": parts[0], "did": ":".join(parts[1:])})
        elif kind in {"RINGGROUP", "RING_GROUP"} and len(parts) >= 2:
            path.append({"kind": "ring_group", "number": parts[0], "name": ":".join(parts[1:])})
        elif kind == "PAGING" and len(parts) >= 2:
            path.append({"kind": "paging", "number": parts[0], "name": ":".join(parts[1:])})
        elif kind == "INTERCOM" and len(parts) >= 2:
            if len(parts) >= 3:
                path.append({"kind": "intercom", "number": parts[0], "name": ":".join(parts[1:])})
            else:
                path.append({"kind": "intercom", "source": parts[0], "target": parts[1]})
        elif kind in {"SPEED", "SPEEDDIAL", "SPEED_DIAL"} and len(parts) >= 2:
            path.append({"kind": "speed_dial", "number": parts[0], "destination": ":".join(parts[1:])})
        elif kind in {"ANNOUNCEMENT", "ANN"} and len(parts) >= 2:
            path.append({"kind": "announcement", "number": parts[0], "name": ":".join(parts[1:])})
    return path


def _best_path(rows):
    candidates = []
    for row in rows:
        parsed = _parse_path(_value(row, "userfield"))
        if parsed:
            candidates.append(parsed)
    if not candidates:
        return []
    # CDR legs carry progressively richer copies of the inherited userfield;
    # the longest valid path is the complete one in normal Asterisk output.
    candidates.sort(key=lambda item: len(item), reverse=True)
    return candidates[0]


def _default_metadata(metadata=None):
    result = {
        "extensions": {},
        "queues": {},
        "ring_groups": {},
        "paging": {},
        "speed_dials": {},
        "announcements": {},
        "trunks": set(),
    }
    if metadata:
        for key, value in metadata.items():
            if key in result and value is not None:
                result[key] = value
        return result
    try:
        import db
        result["extensions"] = {
            _text(item.get("ext")): _text(item.get("name"))
            for item in db.get_all_extensions()
            if _text(item.get("ext"))
        }
        result["queues"] = {
            _text(item.get("queue_number")): item
            for item in db.get_queues()
            if _text(item.get("queue_number"))
        }
        result["ring_groups"] = {
            _text(item.get("id") or item.get("group_id")): item
            for item in db.get_ring_groups()
            if _text(item.get("id") or item.get("group_id"))
        }
        result["paging"] = {
            _text(item.get("id")): item
            for item in db.get_paging()
            if _text(item.get("id"))
        }
        result["speed_dials"] = {
            _text(item.get("speed_dial_num") or item.get("number")): item
            for item in db.get_speed_dials()
            if _text(item.get("speed_dial_num") or item.get("number"))
        }
        result["announcements"] = {
            _text(item.get("num")): item
            for item in db.get_announcements()
            if _text(item.get("num"))
        }
        result["trunks"] = {
            _text(item.get("name"))
            for item in db.get_all_trunks()
            if _text(item.get("name"))
        }
    except Exception:
        pass
    return result


def _event(kind, title, time_value="", subtitle="", details=None, **extra):
    item = {
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "time": _time(time_value),
        "details": details or [],
    }
    item.update(extra)
    return item


def _destination_event(item, metadata, time_value):
    dest_type = _text(item.get("type")).lower().replace("-", "_")
    number = _text(item.get("number"))
    if dest_type == "queue":
        queue = metadata["queues"].get(number, {})
        name = _safe_name(queue.get("name") or queue.get("queue_name"), f"Queue {number}")
        # Keep the normalized queue number on the card as well as in the
        # display details.  The timeline uses it to place a transferred-to
        # queue after the TRANSFER event when both records have the same
        # second (or when QueueLog writes them slightly out of order).
        return _event(
            "queue",
            f"Queue: {name}",
            time_value,
            details=[{"label": "Queue Number", "value": number}],
            queue_number=number,
        )
    if dest_type in {"ringgroup", "ring_group"}:
        group = metadata["ring_groups"].get(number, {})
        name = _safe_name(group.get("name"), f"Ring Group {number}")
        return _event("ring_group", f"Ring Group: {name}", time_value, details=[{"label": "Ring Group Number", "value": number}])
    if dest_type in {"paging", "page"}:
        group = metadata["paging"].get(number, {})
        name = _safe_name(group.get("name"), f"Paging Group {number}")
        return _event("paging", f"Paging Group: {name}", time_value, details=[{"label": "Paging Number", "value": number}])
    if dest_type in {"intercom", "paging_intercom"}:
        return _event("intercom", f"Intercom: {_safe_name(item.get('name'), number)}", time_value,
                      details=[{"label": "Intercom Number", "value": number}])
    if dest_type in {"speed", "speed_dial", "speeddial"}:
        speed = metadata["speed_dials"].get(number, {})
        destination = _text(speed.get("destination_num") or speed.get("destination") or item.get("destination"))
        return _event("speed_dial", "Speed Dial", time_value, details=[
            {"label": "Speed Dial", "value": number},
            {"label": "Resolved Destination", "value": destination or "Unknown"},
        ])
    if dest_type in {"announcement", "ann"}:
        announcement = metadata["announcements"].get(number, {})
        name = _safe_name(announcement.get("name"), f"Announcement {number}")
        return _event("announcement", f"Announcement: {name}", time_value, details=[{"label": "Announcement Number", "value": number}])
    return None


def _infer_destination_events(rows, metadata, time_value):
    events = []
    seen = set()
    for row in rows:
        context = _text(_value(row, "dcontext")).lower()
        dst = _text(_value(row, "dst"))
        app = _text(_value(row, "lastapp")).lower()
        if context.startswith("queue-") or (app == "queue" and dst in metadata.get("queues", {})):
            number = context.split("-", 1)[1] if context.startswith("queue-") else dst
            key = ("queue", number)
            if key not in seen:
                seen.add(key)
                events.append(_destination_event({"type": "queue", "number": number}, metadata, time_value))
        elif context == "rcm-ring-groups":
            key = ("ring_group", dst)
            if key not in seen:
                seen.add(key)
                events.append(_destination_event({"type": "ring_group", "number": dst}, metadata, time_value))
        elif context == "rcm-paging-intercom":
            group = metadata["paging"].get(dst, {})
            kind = "intercom" if bool(group.get("duplex")) else "paging"
            key = (kind, dst)
            if key not in seen:
                seen.add(key)
                events.append(_destination_event({"type": kind, "number": dst}, metadata, time_value))
        elif context.startswith("ann-"):
            number = context.split("-", 1)[1]
            key = ("announcement", number)
            if key not in seen:
                seen.add(key)
                events.append(_destination_event({"type": "announcement", "number": number}, metadata, time_value))
        elif context == "speed-dials":
            key = ("speed_dial", dst)
            if key not in seen:
                seen.add(key)
                events.append(_destination_event({"type": "speed_dial", "number": dst}, metadata, time_value))
    return [item for item in events if item]


def _trunk_info(rows, metadata):
    configured = {item.lower(): item for item in metadata.get("trunks", set())}
    found = []
    inbound = False
    outbound = False
    for row in rows:
        channel_ep = _endpoint(_value(row, "channel"))
        dst_ep = _endpoint(_value(row, "dstchannel"))
        lastdata = _text(_value(row, "lastdata"))
        context = _text(_value(row, "dcontext")).lower()
        channel_trunk = configured.get(channel_ep.lower()) if channel_ep else None
        dst_trunk = configured.get(dst_ep.lower()) if dst_ep else None
        data_trunk = None
        for candidate in configured.values():
            if re.search(r"@" + re.escape(candidate) + r"(?:[,/]|$)", lastdata, re.IGNORECASE):
                data_trunk = candidate
                break
        trunk = channel_trunk or dst_trunk or data_trunk
        if trunk and trunk not in found:
            found.append(trunk)
        if channel_trunk and not dst_trunk:
            inbound = True
        if dst_trunk or data_trunk:
            outbound = True
        if context in {"from-pri", "from-trunk", "inbound-route-eval"} and channel_trunk:
            inbound = True
        if context.startswith("rcm-out-") or context.startswith("out-"):
            outbound = True
    return found, inbound, outbound


def _call_type(rows, metadata):
    trunks, inbound, outbound = _trunk_info(rows, metadata)
    if inbound:
        return "inbound", trunks
    if outbound:
        return "outbound", trunks
    return "internal", trunks


def _attempt_status_key(status):
    return {
        "Answered": "answered",
        "No Answer": "no_answer",
        "Cancelled": "cancelled",
        "Caller Hangup": "caller_hangup",
        "Queue Timeout": "queue_timeout",
    }.get(status, "")


def _int_value(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _queue_rules(queue_number, queue_call, metadata):
    queue = metadata.get("queues", {}).get(_text(queue_number), {}) or {}
    ring_timeout = _int_value(
        queue.get("ring_time") or queue.get("timeout") or queue_call.get("mapped_ring_time")
    )
    max_wait = _int_value(
        queue.get("max_wait_time") or queue.get("max_wait") or queue.get("maximum_wait_time")
    )
    return ring_timeout, max_wait


def _event_time(event):
    return _time(_value(event, "timestamp"))


def _queue_number_for_event(event, queue_call):
    return _text(_value(event, "queue")) or _text(_value(queue_call, "queue_id"))


def _transfer_specs(queue_events, metadata):
    """Normalize transfer rows into source/target queue and agent metadata."""
    queue_numbers = set(metadata.get("queues", {}))
    ordered = sorted(
        queue_events or [],
        key=lambda item: (_time_key(_event_time(item)), _int_value(_value(item, "event_id"))),
    )
    specs = []
    active_agent = ""
    for index, event in enumerate(ordered):
        event_type = _normal_status(_value(event, "event_type"))
        event_agent = _text(_value(event, "agent"))
        event_queue = _text(_value(event, "queue"))
        if event_type == "ANSWER" and event_agent:
            active_agent = event_agent
        if event_type != "TRANSFER":
            continue

        timestamp = _event_time(event)
        source = _text(_value(event, "source")) or active_agent
        raw_target = event_agent
        source_queue = event_queue
        target_queue = raw_target if raw_target in queue_numbers else source_queue
        target_agent = "" if raw_target in queue_numbers else raw_target

        # QueueLog can encode a queue target, while a transfer to an agent can
        # expose the destination queue only on the following RING/ANSWER.
        future = ordered[index + 1:]
        target_events = [
            candidate for candidate in future
            if _normal_status(_value(candidate, "event_type")) in {"RING", "ANSWER"}
            and _event_time(candidate)
            and _time_key(_event_time(candidate)) >= _time_key(timestamp)
        ]
        if target_agent:
            matching = [candidate for candidate in target_events if _text(_value(candidate, "agent")) == target_agent]
            if matching:
                target_queue = _text(_value(matching[0], "queue")) or target_queue
        elif target_queue:
            matching = [candidate for candidate in target_events if _text(_value(candidate, "queue")) == target_queue]
            if matching:
                target_agent = _text(_value(matching[0], "agent"))

        normalized = dict(event)
        normalized.update({
            "source": source,
            "source_queue": source_queue,
            "target": raw_target,
            "target_agent": target_agent,
            "target_queue": target_queue,
        })
        specs.append(normalized)
    return specs


def _events_by_queue(queue_events, queue_call, transfer_specs):
    """Assign duplicate collector events to one queue context only."""
    groups = {}
    for event in queue_events or []:
        queue_number = _queue_number_for_event(event, queue_call)
        key = (
            _normal_status(_value(event, "event_type")),
            _text(_value(event, "agent")),
            _event_time(event),
        )
        groups.setdefault(key, []).append((queue_number, event))

    owned = {}
    for key, entries in groups.items():
        queue_set = {queue for queue, _ in entries if queue}
        preferred = ""
        event_time = _time_key(key[2])
        for transfer in transfer_specs:
            target_queue = _text(transfer.get("target_queue"))
            source_queue = _text(transfer.get("source_queue"))
            if (
                target_queue
                and target_queue != source_queue
                and target_queue in queue_set
                and event_time >= _time_key(_event_time(transfer))
            ):
                preferred = target_queue
                break
        if not preferred:
            preferred = sorted(queue_set)[0] if queue_set else ""
        # Keep one copy when Asterisk/collector emits the same event twice.
        selected = next((event for queue, event in entries if queue == preferred), entries[0][1])
        owned.setdefault(preferred, []).append(selected)

    for queue_number in owned:
        owned[queue_number].sort(
            key=lambda item: (_time_key(_event_time(item)), _int_value(_value(item, "event_id")))
        )
    return owned


def _queue_contexts(queue_call, queue_events, rows, metadata):
    """Build one queue context per queue touched by the call/transfer path."""
    existing = queue_call.get("_related_queue_calls") or [queue_call]
    existing_by_queue = {
        _text(item.get("queue_id")): dict(item)
        for item in existing
        if _text(item.get("queue_id"))
    }
    queue_numbers = list(existing_by_queue)
    for row in rows or []:
        context = _text(_value(row, "dcontext"))
        if context.lower().startswith("queue-"):
            number = context.split("-", 1)[1]
            if number and number not in queue_numbers:
                queue_numbers.append(number)
    for event in queue_events or []:
        number = _text(_value(event, "queue"))
        if number and number not in queue_numbers:
            queue_numbers.append(number)
    for transfer in _transfer_specs(queue_events, metadata):
        number = _text(transfer.get("target_queue"))
        if number and number not in queue_numbers:
            queue_numbers.append(number)

    contexts = []
    for queue_number in queue_numbers:
        context = dict(existing_by_queue.get(queue_number) or queue_call or {})
        context["queue_id"] = queue_number
        queue_meta = metadata.get("queues", {}).get(queue_number, {}) or {}
        context["queue_name"] = (
            queue_meta.get("name") or queue_meta.get("queue_name")
            or context.get("queue_name") or queue_number
        )
        queue_events_for_context = [
            event for event in (queue_events or [])
            if _queue_number_for_event(event, context) == queue_number
        ]
        enter_times = [
            _event_time(event) for event in queue_events_for_context
            if _normal_status(_value(event, "event_type")) == "ENTERQUEUE"
            and _event_time(event)
        ]
        answer_events = [
            event for event in queue_events_for_context
            if _normal_status(_value(event, "event_type")) == "ANSWER"
            and _text(_value(event, "agent"))
        ]
        answer_events.sort(key=lambda event: _time_key(_event_time(event)))
        terminal_times = [
            _event_time(event) for event in queue_events_for_context
            if _normal_status(_value(event, "event_type")) in {
                "HANGUP", "COMPLETE", "COMPLETEAGENT", "COMPLETECALLER",
                "ABANDON", "EXITWITHTIMEOUT", "RINGCANCELED",
            }
            and _event_time(event)
        ]
        cdr_rows = [
            row for row in rows or []
            if _text(_value(row, "dcontext")).lower() == f"queue-{queue_number}".lower()
        ]
        cdr_rows.sort(key=lambda row: _time_key(_value(row, "start_time")))
        first_cdr = cdr_rows[0] if cdr_rows else {}
        context["entry_time"] = min(
            enter_times + [_time(_value(first_cdr, "start_time")), _time(context.get("entry_time"))],
            key=_time_key,
        ) if any(enter_times + [_time(_value(first_cdr, "start_time")), _time(context.get("entry_time"))]) else ""
        if answer_events:
            context["answer_time"] = _event_time(answer_events[0])
            context["agent"] = _text(_value(answer_events[0], "agent"))
            context["status"] = "ANSWERED"
        elif first_cdr:
            context["answer_time"] = _time(_value(first_cdr, "answer_time"))
            context["status"] = _text(_value(first_cdr, "status")) or context.get("status")
        if terminal_times:
            context["hangup_time"] = max(terminal_times, key=_time_key)
        elif first_cdr:
            context["hangup_time"] = _time(_value(first_cdr, "end_time")) or context.get("hangup_time")
        if not context.get("agent") and first_cdr:
            context["agent"] = _endpoint(_value(first_cdr, "dstchannel")) or _text(_value(first_cdr, "dst"))
        contexts.append(context)

    contexts.sort(key=lambda item: _time_key(item.get("entry_time")))
    return contexts or [dict(queue_call)]


def _queue_sessions(queue_call, queue_events, rows, metadata):
    """Build one context for every visit to a queue.

    Queue number is not a session identifier: a caller can leave and later
    re-enter the same queue.  Keep the collector's queue_calls rows as the
    primary session records and only synthesize a context for queue visits
    that exist in CDR/QueueLog but have no persisted queue_calls row.
    """
    related = [dict(item) for item in (queue_call.get("_related_queue_calls") or [queue_call]) if item]
    known_numbers = []
    for item in related:
        number = _text(item.get("queue_id"))
        if number and number not in known_numbers:
            known_numbers.append(number)
    for row in rows or []:
        context = _text(_value(row, "dcontext"))
        if context.lower().startswith("queue-"):
            number = context.split("-", 1)[1]
            if number and number not in known_numbers:
                known_numbers.append(number)
    for event in queue_events or []:
        number = _text(_value(event, "queue"))
        if number and number not in known_numbers:
            known_numbers.append(number)

    def events_for_number(number):
        exact = [event for event in queue_events or [] if _text(_value(event, "queue")) == number]
        if exact:
            return exact
        if len(known_numbers) == 1:
            return list(queue_events or [])
        return []

    def cdr_rows_for_number(number):
        return [
            row for row in rows or []
            if _text(_value(row, "dcontext")).lower() == f"queue-{number}".lower()
        ]

    contexts = []
    for source in related:
        context = dict(source)
        number = _text(context.get("queue_id"))
        if not number:
            continue
        context["queue_id"] = number
        context["_session_explicit_end"] = bool(_time(source.get("hangup_time")))
        queue_meta = metadata.get("queues", {}).get(number, {}) or {}
        context["queue_name"] = (
            queue_meta.get("name") or queue_meta.get("queue_name")
            or context.get("queue_name") or number
        )
        all_queue_events = events_for_number(number)
        all_queue_rows = cdr_rows_for_number(number)
        source_id = _text(source.get("uniqueid"))
        source_rows = [
            row for row in all_queue_rows
            if source_id and source_id in {
                _text(_value(row, "uniqueid")), _text(_value(row, "linkedid"))
            }
        ]
        if source_rows:
            all_queue_rows = source_rows
        entry_hint = _time(context.get("entry_time"))
        if not entry_hint:
            entry_candidates = [
                _event_time(event) for event in all_queue_events
                if _normal_status(_value(event, "event_type")) == "ENTERQUEUE" and _event_time(event)
            ]
            entry_hint = min(entry_candidates, key=_time_key) if entry_candidates else (
                _time(_value(all_queue_rows[0], "start_time")) if all_queue_rows else ""
            )
        entry_dt = _parse_duration_time(entry_hint)
        next_entry_times = [
            _parse_duration_time(_time(item.get("entry_time")))
            for item in related
            if item is not source
            and _text(item.get("queue_id")) == number
            and _parse_duration_time(_time(item.get("entry_time")))
            and _parse_duration_time(_time(item.get("entry_time"))) > (entry_dt or datetime.min)
        ]
        next_entry = min(next_entry_times) if next_entry_times else None
        explicit_end = _parse_duration_time(_time(source.get("hangup_time")))
        session_end = explicit_end or next_entry

        def in_session(value):
            timestamp = _parse_duration_time(value)
            return bool(
                timestamp
                and (not entry_dt or timestamp >= entry_dt)
                and (not session_end or timestamp <= session_end)
            )

        scoped_events = [event for event in all_queue_events if in_session(_event_time(event))]
        scoped_rows = [
            row for row in all_queue_rows
            if in_session(_value(row, "start_time"))
        ] or all_queue_rows[:1]
        enter_times = [
            _event_time(event) for event in scoped_events
            if _normal_status(_value(event, "event_type")) == "ENTERQUEUE" and _event_time(event)
        ]
        start_values = enter_times + [
            _time(context.get("entry_time")),
            _time(_value(scoped_rows[0], "start_time")) if scoped_rows else "",
        ]
        start_values = [value for value in start_values if value]
        if start_values:
            context["entry_time"] = min(start_values, key=_time_key)

        answer_events = [
            event for event in scoped_events
            if _normal_status(_value(event, "event_type")) in {"ANSWER", "CONNECT"}
            and _event_time(event)
            and (_normal_status(_value(event, "event_type")) == "CONNECT" or _text(_value(event, "agent")))
        ]
        answer_values = [_event_time(event) for event in answer_events]
        if not answer_values and _time(context.get("answer_time")):
            answer_values.append(_time(context.get("answer_time")))
        if not answer_values:
            for row in scoped_rows:
                if _normal_status(_value(row, "status")) == "ANSWERED" and _time(_value(row, "answer_time")):
                    answer_values.append(_time(_value(row, "answer_time")))
        if answer_values:
            context["answer_time"] = min(answer_values, key=_time_key)
            context["status"] = "ANSWERED"
        elif not _text(context.get("status")):
            context["status"] = _text(_value(scoped_rows[0], "status")) if scoped_rows else ""

        terminal_values = [
            _event_time(event) for event in scoped_events
            if _normal_status(_value(event, "event_type")) in {
                "HANGUP", "COMPLETE", "COMPLETEAGENT", "COMPLETECALLER",
                "ABANDON", "EXITWITHTIMEOUT", "EXITWITHKEY", "EXITEMPTY",
                "RINGCANCELED",
            }
            and _event_time(event)
        ]
        terminal_values += [_time(context.get("hangup_time"))]
        terminal_values += [_time(_value(row, "end_time")) for row in scoped_rows]
        terminal_values = [value for value in terminal_values if value]
        if terminal_values:
            context["hangup_time"] = max(terminal_values, key=_time_key)

        if not _text(context.get("agent")):
            answered_agents = [
                _text(_value(event, "agent")) for event in answer_events
                if _text(_value(event, "agent"))
            ]
            if answered_agents:
                context["agent"] = answered_agents[0]
            elif scoped_rows:
                context["agent"] = _endpoint(_value(scoped_rows[0], "dstchannel")) or _text(_value(scoped_rows[0], "dst"))
        context["_session_source_id"] = _text(context.get("uniqueid"))
        contexts.append(context)

    represented_numbers = {_text(item.get("queue_id")) for item in contexts}
    for number in known_numbers:
        if number in represented_numbers:
            continue
        context = {"queue_id": number, "queue_name": number}
        queue_meta = metadata.get("queues", {}).get(number, {}) or {}
        context["queue_name"] = queue_meta.get("name") or queue_meta.get("queue_name") or number
        scoped_events = events_for_number(number)
        scoped_rows = cdr_rows_for_number(number)
        enter_times = [_event_time(event) for event in scoped_events if _normal_status(_value(event, "event_type")) == "ENTERQUEUE" and _event_time(event)]
        context["entry_time"] = min(enter_times + [_time(_value(scoped_rows[0], "start_time")) if scoped_rows else ""], key=_time_key) if enter_times or scoped_rows else ""
        context["hangup_time"] = max(
            [_time(_value(row, "end_time")) for row in scoped_rows if _time(_value(row, "end_time"))]
            + [_event_time(event) for event in scoped_events if _event_time(event)],
            key=_time_key,
            default="",
        )
        contexts.append(context)

    contexts.sort(key=lambda item: (_time_key(item.get("entry_time")), _text(item.get("_session_source_id"))))
    for index, context in enumerate(contexts):
        context["queue_session_index"] = index
        if not context.get("_session_explicit_end"):
            later_starts = [
                _parse_duration_time(item.get("entry_time"))
                for item in contexts[index + 1:]
                if _text(item.get("queue_id")) == _text(context.get("queue_id"))
                and _parse_duration_time(item.get("entry_time"))
            ]
            context["_session_boundary_time"] = min(later_starts).strftime("%Y-%m-%d %H:%M:%S") if later_starts else ""
    return contexts or [dict(queue_call)]


def _events_for_queue_session(queue_events, session, all_sessions):
    """Return only events belonging to one visit, including repeated queues."""
    number = _text(session.get("queue_id"))
    same_queue = [item for item in all_sessions if _text(item.get("queue_id")) == number]
    start = _time_key(session.get("entry_time"))
    end = _time_key(session.get("hangup_time"))
    if not session.get("_session_explicit_end"):
        boundary = _parse_duration_time(session.get("_session_boundary_time"))
        end = boundary or datetime.max
    selected = []
    for event in queue_events or []:
        event_queue = _text(_value(event, "queue"))
        if event_queue and event_queue != number:
            continue
        timestamp = _event_time(event)
        timestamp_dt = _parse_duration_time(timestamp)
        if not timestamp_dt:
            continue
        if event_queue:
            # Queue-tagged events still need a time boundary for repeated
            # visits to the same queue.
            if timestamp_dt < start or (end != datetime.max and timestamp_dt > end):
                continue
        elif len(same_queue) > 1 and (timestamp_dt < start or (end != datetime.max and timestamp_dt > end)):
            continue
        selected.append(event)
    selected.sort(key=lambda item: (_time_key(_event_time(item)), _int_value(_value(item, "event_id"))))
    return selected


def _queue_session_metrics(session, session_events, rows, now=None):
    """Calculate wait/talk/hold for one queue visit."""
    all_scoped_rows = [
        row for row in rows or []
        if _text(_value(row, "dcontext")).lower() == f"queue-{_text(session.get('queue_id'))}".lower()
    ]
    entry_dt = _parse_duration_time(session.get("entry_time"))
    end_dt = _parse_duration_time(session.get("hangup_time"))
    if not session.get("_session_explicit_end"):
        end_dt = _parse_duration_time(session.get("_session_boundary_time"))
    scoped_rows = [
        row for row in all_scoped_rows
        if (
            not entry_dt or (_parse_duration_time(_value(row, "start_time")) or datetime.max) >= entry_dt
        )
        and (
            not end_dt or (_parse_duration_time(_value(row, "start_time")) or datetime.min) <= end_dt
        )
    ] or all_scoped_rows[:1]
    summary = calculate_call_durations(
        scoped_rows,
        session,
        session_events,
        legacy_fallback=True,
        now=now,
    )
    entry = _parse_duration_time(session.get("entry_time"))
    answer = _parse_duration_time(session.get("answer_time"))
    end = _parse_duration_time(session.get("hangup_time"))
    if not entry:
        entry = _parse_duration_time(summary.get("start_time"))
    if not end:
        end = _parse_duration_time(summary.get("end_time"))
    if not end:
        end = now or datetime.now()
    if entry and end < entry:
        end = entry
    if entry and answer and answer < entry:
        answer = None
    wait_end = answer or end
    wait_seconds = max(0, int((wait_end - entry).total_seconds())) if entry and wait_end else 0

    # queue_calls.talk_time is the authoritative persisted value when the
    # event stream is from an older collector version with no bridge events.
    try:
        persisted_talk = max(0, int(float(session.get("talk_time") or 0)))
    except (TypeError, ValueError):
        persisted_talk = 0
    has_bridge_evidence = any(
        _duration_event_type(event) in {"CONNECT", "BRIDGE", "BRIDGEENTER"}
        for event in session_events
    )
    if persisted_talk and not has_bridge_evidence:
        summary["talk_time"] = persisted_talk
        summary["talk_time_display"] = _format_duration_hms(persisted_talk)

    return {
        "wait_time": wait_seconds,
        "talk_time": summary.get("talk_time", 0),
        "hold_time": summary.get("hold_time", 0),
        "wait_time_display": _format_duration_hms(wait_seconds),
        "talk_time_display": summary.get("talk_time_display", "00:00:00"),
        "hold_time_display": summary.get("hold_time_display", "00:00:00"),
        "entry_time": session.get("entry_time") or "",
        "answer_time": session.get("answer_time") or "",
        "end_time": session.get("hangup_time") or "",
    }


def _build_attempts(rows, queue_events, queue_call, metadata):
    extension_names = metadata.get("extensions", {})
    attempts = []
    answered_events = [
        event for event in queue_events or []
        if _normal_status(_value(event, "event_type")) == "ANSWER"
    ]
    caller_hangup = _normal_status(_value(queue_call, "hangup_by")) in {"CALLER", "ORIGINATOR"}
    caller_hangup_time = _time(_value(queue_call, "hangup_time")) if caller_hangup else ""
    queue_timeout_events = [
        event for event in queue_events or []
        if _normal_status(_value(event, "event_type")).replace(" ", "") in {
            "EXITWITHTIMEOUT", "QUEUETIMEOUT", "TIMEOUT"
        }
    ]

    def ensure(agent, timestamp, queue_number):
        agent = _text(agent)
        if not agent:
            return None
        attempt = {
            "extension": agent,
            "agent_name": extension_names.get(agent) or agent,
            "status": "",
            "status_key": "",
            "ring_time_display": "00:00",
            "ring_duration_seconds": 0,
            "attempt_started_at": _time(timestamp),
            "attempt_ended_at": "",
            "queue_number": _text(queue_number),
            "_ring_started": _time(timestamp),
            "_resolved": False,
        }
        attempts.append(attempt)
        return attempt

    def open_attempt(agent, queue_number):
        agent = _text(agent)
        queue_number = _text(queue_number)
        for attempt in reversed(attempts):
            if (
                attempt.get("extension") == agent
                and attempt.get("queue_number") == queue_number
                and not attempt.get("_resolved")
            ):
                return attempt
        return None

    def has_answer_near(queue_number, timestamp, agent):
        for event in answered_events:
            if _queue_number_for_event(event, queue_call) != queue_number:
                continue
            if _text(_value(event, "agent")) == _text(agent):
                continue
            answer_time = _event_time(event)
            if answer_time and abs((_time_key(answer_time) - _time_key(timestamp)).total_seconds()) <= 1:
                return True
        return False

    def terminating_status(attempt, event_time, event_type):
        queue_number = attempt.get("queue_number")
        timeout_time = next(
            (
                _event_time(event) for event in queue_timeout_events
                if _queue_number_for_event(event, queue_call) == queue_number
                and _time_key(_event_time(event)) <= _time_key(event_time)
            ),
            "",
        )
        if timeout_time:
            return "Queue Timeout"
        if caller_hangup and caller_hangup_time and _time_key(caller_hangup_time) <= _time_key(event_time):
            return "Caller Hangup"
        if event_type == "RINGCANCELED":
            # RINGCANCELED is also emitted when another simultaneous agent
            # answers. That is not evidence that this agent rejected the call.
            if has_answer_near(queue_number, event_time, attempt.get("extension")):
                return ""
            return "Cancelled"
        if event_type == "RINGNOANSWER":
            ring_timeout, _ = _queue_rules(queue_number, queue_call, metadata)
            elapsed = (
                _time_key(event_time) - _time_key(attempt.get("_ring_started"))
            ).total_seconds()
            # In this PBX, an early RINGNOANSWER is the queue's evidence that
            # the member leg ended before the configured member timeout.  At
            # the timeout boundary it is a genuine No Answer instead.
            if ring_timeout <= 0:
                return ""
            if elapsed < max(0, ring_timeout - 1):
                return "Cancelled"
            return "No Answer"
        if event_type in {"HANGUP", "COMPLETE", "CANCEL", "REJECT"}:
            return "Cancelled"
        return ""

    def finish(attempt, status, timestamp):
        if not attempt or not status or status not in ATTEMPT_STATUSES:
            return
        attempt["status"] = status
        attempt["status_key"] = _attempt_status_key(status)
        attempt["attempt_ended_at"] = _time(timestamp)
        attempt["_resolved"] = True
        started = _time_key(attempt.get("_ring_started"))
        ended = _time_key(timestamp)
        if started != datetime.max and ended != datetime.max:
            duration = max(0, int((ended - started).total_seconds()))
            attempt["ring_duration_seconds"] = duration
            attempt["ring_time_display"] = _format_duration(duration)

    ordered_events = sorted(
        queue_events or [],
        key=lambda item: (_time_key(_event_time(item)), _int_value(_value(item, "event_id"))),
    )
    seen_rings = set()
    for event in ordered_events:
        agent = _text(_value(event, "agent"))
        event_type = _normal_status(_value(event, "event_type"))
        timestamp = _event_time(event)
        queue_number = _queue_number_for_event(event, queue_call)
        compact_type = event_type.replace(" ", "")
        if event_type in {"HOLD", "UNHOLD", "BRIDGE", "UNBRIDGE", "ENTERQUEUE", "TRANSFER"}:
            continue
        if event_type == "RING":
            ring_key = (queue_number, agent, timestamp)
            if ring_key not in seen_rings:
                seen_rings.add(ring_key)
                ring_timeout, _ = _queue_rules(queue_number, queue_call, metadata)
                existing = open_attempt(agent, queue_number)
                if existing and not existing.get("_resolved"):
                    elapsed = (
                        _time_key(timestamp) - _time_key(existing.get("_ring_started"))
                    ).total_seconds()
                    # Asterisk/collector can write two RING records for the
                    # same leg a second apart. Keep one attempt while it is
                    # still inside the same member ring window. A genuinely
                    # new cycle is opened only after that window expires.
                    if ring_timeout <= 0 or elapsed < ring_timeout:
                        continue
                for previous in attempts:
                    if previous.get("_resolved") or previous.get("queue_number") != queue_number:
                        continue
                    elapsed = (_time_key(timestamp) - _time_key(previous.get("_ring_started"))).total_seconds()
                    # A later RING can be a new queue cycle for the same
                    # member.  Once the configured member timeout has elapsed,
                    # close the previous cycle before opening the new one.
                    if ring_timeout > 0 and elapsed >= ring_timeout:
                        finish(previous, "No Answer", timestamp)
                ensure(agent, timestamp, queue_number)
            continue
        if event_type == "ANSWER":
            finish(open_attempt(agent, queue_number), "Answered", timestamp)
            continue
        if compact_type in {"RINGNOANSWER", "RINGCANCELED"}:
            attempt = open_attempt(agent, queue_number)
            if attempt:
                finish(attempt, terminating_status(attempt, timestamp, compact_type), timestamp)
            continue
        if compact_type in {"EXITWITHTIMEOUT", "QUEUETIMEOUT", "TIMEOUT"}:
            for attempt in attempts:
                if not attempt.get("_resolved") and attempt.get("queue_number") == queue_number:
                    finish(attempt, "Queue Timeout", timestamp)
            continue
        if compact_type in {"HANGUP", "COMPLETE", "CANCEL", "REJECT"}:
            attempt = open_attempt(agent, queue_number)
            if attempt:
                finish(attempt, terminating_status(attempt, timestamp, compact_type), timestamp)
            continue
        if compact_type in {"ABANDON", "EXITWITHKEY"}:
            for attempt in attempts:
                if not attempt.get("_resolved") and attempt.get("queue_number") == queue_number:
                    finish(attempt, "Caller Hangup", timestamp)

    final_agent = _text(_value(queue_call, "agent"))
    final_status = _normal_status(_value(queue_call, "status"))
    if final_agent and final_status == "ANSWERED":
        queue_number = _text(_value(queue_call, "queue_id"))
        attempt = open_attempt(final_agent, queue_number)
        # Queue integrations can write ANSWER more than once.  Do not create
        # a second synthetic attempt when a real ANSWER already resolved one.
        if attempt is None:
            attempt = next(
                (
                    item for item in reversed(attempts)
                    if item.get("extension") == final_agent
                    and item.get("queue_number") == queue_number
                    and item.get("status") == "Answered"
                ),
                None,
            )
        if attempt is None:
            attempt = ensure(final_agent, _value(queue_call, "answer_time"), queue_number)
        if attempt is not None and attempt.get("status") != "Answered":
            finish(attempt, "Answered", _value(queue_call, "answer_time"))

    if final_status in {"TIMEOUT", "QUEUE TIMEOUT"}:
        timeout_time = _time(_value(queue_call, "hangup_time")) or _time(_value(queue_call, "answer_time"))
        for attempt in attempts:
            if not attempt.get("_resolved"):
                finish(attempt, "Queue Timeout", timeout_time)
    elif caller_hangup and caller_hangup_time:
        for attempt in attempts:
            if not attempt.get("_resolved"):
                finish(attempt, "Caller Hangup", caller_hangup_time)

    # The list is a call-order list: preserve the first ring time for each
    # agent, regardless of which attempt eventually answered.
    attempts.sort(key=lambda item: _time_key(item.get("_ring_started")))
    result = []
    for attempt in attempts:
        attempt.pop("_ring_started", None)
        attempt.pop("_resolved", None)
        # An unresolved simultaneous ring is intentionally omitted: assigning
        # Cancelled/No Answer without evidence would fabricate an agent action.
        if attempt.get("status") in ATTEMPT_STATUSES:
            result.append(attempt)
    return result


def _answer_targets(rows, queue_call, attempts, metadata, transfers=None):
    answers = []
    for attempt in attempts:
        if attempt.get("status") == "Answered":
            answers.append((attempt.get("extension"), _time(attempt.get("attempt_ended_at")) or _time(_value(queue_call, "answer_time"))))
    for row in rows:
        if not _is_meaningful_answer_row(row):
            continue
        # Asterisk may emit two ANSWERED legs at the same instant: the
        # business Queue/Dial leg and a MixMonitor recording leg.  The latter
        # is valid evidence for a direct call when it is the only leg, but it
        # must not create a second answered card when a real destination leg
        # already exists.
        row_context = _text(_value(row, "dcontext")).lower()
        if row_context in {"recording", "mixmonitor"}:
            row_dst = _text(_value(row, "dst"))
            row_answer = _parse_duration_time(_value(row, "answer_time"))
            duplicate_destination = False
            for other in rows:
                if other is row or _normal_status(_value(other, "status")) != "ANSWERED":
                    continue
                other_context = _text(_value(other, "dcontext")).lower()
                if other_context in {"recording", "mixmonitor"}:
                    continue
                if row_dst and _text(_value(other, "dst")) != row_dst:
                    continue
                other_answer = _parse_duration_time(_value(other, "answer_time"))
                if row_answer and other_answer and abs((row_answer - other_answer).total_seconds()) <= 1:
                    duplicate_destination = True
                    break
            if duplicate_destination:
                continue
        candidates = [_text(_value(row, "dst"))] + _endpoints(_value(row, "dstchannel"))
        for candidate in candidates:
            if candidate and candidate not in metadata.get("queues", {}) and candidate not in metadata.get("ring_groups", {}) and candidate not in metadata.get("paging", {}) and candidate not in metadata.get("announcements", {}) and candidate not in {"i", "s", "t"}:
                answers.append((candidate, _time(_value(row, "answer_time")) or _time(_value(row, "end_time"))))
                break
    # Asterisk can write the transferred destination on the Queue leg, while
    # the recording leg carries a misleading early ANSWERED disposition. Use
    # the actual transfer event as the boundary and only add the destination
    # when a related target leg is also ANSWERED.
    for transfer in transfers or []:
        target = _text(transfer.get("target_agent")) or _text(_value(transfer, "agent"))
        # A queue target is a destination, not an answered callee. The real
        # target agent is represented by the destination queue's attempt.
        if target in metadata.get("queues", {}):
            continue
        if not target or _normal_status(_value(transfer, "result")) == "FAILED":
            continue
        target_rows = [
            row for row in rows
            if _text(_value(row, "dst")) == target
            and _text(_value(row, "dcontext")).lower() not in {"recording", "mixmonitor"}
            and _normal_status(_value(row, "status")) == "ANSWERED"
        ]
        if target_rows:
            answers.append((target, _time(_value(transfer, "timestamp")) or _time(_value(target_rows[-1], "answer_time"))))
    unique = []
    for item in sorted(answers, key=lambda value: _time_key(value[1])):
        if item[0] and item[0] not in [existing[0] for existing in unique]:
            unique.append(item)
    return unique


def _infer_cdr_transfers(rows):
    """Infer direct transfer legs when CEL/queue_log is unavailable.

    A direct transfer normally creates a new leg from the original caller in
    ``from-internal-<transferring-extension>``. This is deliberately narrow:
    it only links an answered leg to the immediately following related leg
    and never exposes the underlying channel event.
    """
    transfers = []
    ordered = sorted(rows, key=lambda item: _time_key(_value(item, "start_time")))
    for current in ordered:
        if _normal_status(_value(current, "status")) != "ANSWERED":
            continue
        source = _text(_value(current, "dst"))
        caller = _text(_value(current, "src"))
        if not source or not caller:
            continue
        context = _text(_value(current, "dcontext"))
        for following in ordered:
            if following is current or _text(_value(following, "src")) != caller:
                continue
            following_context = _text(_value(following, "dcontext"))
            if following_context.lower() != f"from-internal-{source}".lower():
                continue
            current_end = _time(_value(current, "end_time")) or _time(_value(current, "start_time"))
            next_start = _time(_value(following, "start_time"))
            if _time_key(next_start) < _time_key(current_end):
                continue
            if (_time_key(next_start) - _time_key(current_end)).total_seconds() > 300:
                continue
            target = _text(_value(following, "dst"))
            if not target or target == source:
                continue
            transfers.append({
                "source": source,
                "agent": target,
                "timestamp": next_start,
                "transfer_type": "Blind Transfer",
                "result": "" if _normal_status(_value(following, "status")) == "ANSWERED" else "FAILED",
            })
            break
    return transfers


def _final_result(rows, queue_call):
    queue_status = _normal_status(_value(queue_call, "status"))
    if queue_status:
        status = queue_status
    else:
        statuses = [_normal_status(_value(row, "status")) for row in rows if _value(row, "status")]
        if any(_is_meaningful_answer_row(row) for row in rows):
            status = "ANSWERED"
        else:
            # Playback/IVR can generate a technical ANSWERED leg after a
            # BUSY/NO ANSWER destination. Keep the real disposition instead.
            non_answered = next(
                (candidate for candidate in reversed(statuses) if candidate != "ANSWERED"),
                None,
            )
            # If every available CDR leg is a technical ANSWERED leg, it is
            # not a business answer.  Keep the same reporting semantics as
            # the CDR list and classify it as NO ANSWER.
            status = non_answered or ("NO ANSWER" if statuses else "UNKNOWN")
    return {
        "ANSWERED": "Answered",
        "NO ANSWER": "No Answer",
        "BUSY": "Busy",
        "FAILED": "Failed",
        "CONGESTION": "Failed",
        "CHANUNAVAIL": "Unavailable",
        "UNAVAILABLE": "Unavailable",
        "CANCELLED": "Cancelled",
        "ABANDONED": "Caller Abandoned",
        "TIMEOUT": "Queue Timeout",
    }.get(status, status.title() if status else "Unknown")


def build_call_journey(cdr_records, queue_call=None, queue_events=None, metadata=None):
    """Build the complete business journey from all related call records."""
    rows = [dict(row) for row in (cdr_records or []) if row]
    rows.sort(key=lambda item: (_time_key(_value(item, "start_time")), _text(_value(item, "uniqueid"))))
    metadata = _default_metadata(metadata)
    queue_call = dict(queue_call or {})
    if not rows and not queue_call:
        return None

    related_queue_calls = queue_call.get("_related_queue_calls") or [queue_call]
    # The first queue row is the entry point, but the final queue row is the
    # authoritative summary when the caller moved through multiple queues.
    summary_queue_call = next(
        (
            item for item in reversed(related_queue_calls)
            if _normal_status(_value(item, "status")) == "ANSWERED"
        ),
        related_queue_calls[-1] if related_queue_calls else queue_call,
    )
    start_row = rows[0] if rows else queue_call
    # A complete event stream uses exact bridge/hold intervals.  Older direct
    # CDRs may have no QueueLog/bridge events at all, so keep their existing
    # billsec value as a conservative compatibility fallback (never summed).
    duration_summary = calculate_call_durations(rows, queue_call, queue_events, legacy_fallback=True)
    start_time = duration_summary["start_time"] or _time(_value(start_row, "start_time") or _value(queue_call, "entry_time"))
    end_time = duration_summary["end_time"] or start_time
    caller = _text(_value(start_row, "src") or _value(summary_queue_call, "caller_number")) or "Unknown"
    path = _best_path(rows)
    call_type, trunks = _call_type(rows, metadata)

    inbound_path = next((item for item in path if item["kind"] == "inbound"), None)
    did = _text(inbound_path.get("did")) if inbound_path else ""
    if not did:
        for row in rows:
            context = _text(_value(row, "dcontext")).lower()
            if context in {"from-trunk", "from-pri", "inbound-route-eval"} and _text(_value(row, "dst")):
                did = _text(_value(row, "dst"))
                break

    journey = []
    start_details = [{"label": "Caller", "value": _display_party(caller, metadata["extensions"])}]
    if call_type == "inbound":
        start_details.extend([
            {"label": "Trunk", "value": trunks[0] if trunks else "Unknown"},
            {"label": "DID", "value": did or "Unknown"},
        ])
    elif call_type == "outbound":
        destination = _text(_value(rows[-1], "dst")) if rows else "Unknown"
        start_details.extend([
            {"label": "Destination", "value": destination or "Unknown"},
            {"label": "Trunk", "value": trunks[0] if trunks else "Unknown"},
        ])
    journey.append(_event("start", "Call Started", start_time, details=start_details))

    for item in path:
        kind = item["kind"]
        if kind == "inbound":
            continue
        if kind == "ivr":
            journey.append(_event("ivr", f"IVR: {_safe_name(item.get('name'), item.get('number'))}", start_time,
                                  details=[{"label": "IVR Number", "value": _text(item.get("number"))}]))
        elif kind == "digit":
            journey.append(_event("digit", "Pressed Digit", start_time,
                                  details=[{"label": "Caller Pressed", "value": _text(item.get("digit"))}]))
        elif kind == "destination":
            destination_event = _destination_event(item, metadata, start_time)
            if destination_event:
                journey.append(destination_event)
        elif kind in {"ring_group", "paging", "intercom", "speed_dial", "announcement"}:
            destination_event = _destination_event(
                {"type": kind, "number": item.get("number"), "name": item.get("name"), "destination": item.get("destination")},
                metadata,
                start_time,
            )
            if destination_event:
                journey.append(destination_event)

    if not any(item["kind"] in {"queue", "ring_group", "paging", "intercom", "announcement", "speed_dial"} for item in journey):
        journey.extend(_infer_destination_events(rows, metadata, start_time))

    transfer_specs = _transfer_specs(queue_events, metadata)
    related_queue_calls = _queue_sessions(queue_call, queue_events, rows, metadata)
    attempts = []
    session_metrics = []
    for session_index, related_call in enumerate(related_queue_calls):
        related_call["queue_session_index"] = session_index
        related_events = _events_for_queue_session(queue_events, related_call, related_queue_calls)
        session_metrics.append(_queue_session_metrics(related_call, related_events, rows))
        session_attempts = _build_attempts(rows, related_events, related_call, metadata)
        for attempt in session_attempts:
            attempt["queue_session_index"] = session_index
        attempts.extend(session_attempts)

    queue_present = any(item["kind"] == "queue" for item in journey) or bool(related_queue_calls)
    if queue_present:
        queue_cards = [item for item in journey if item["kind"] == "queue"]
        # Cards inferred from the path normally describe the first visit.
        # Assign them by occurrence, not only by queue number, so a repeated
        # visit to the same queue remains a separate card.
        used_session_indexes = set()
        for queue_card in queue_cards:
            queue_number = _text(queue_card.get("queue_number"))
            if not queue_number:
                queue_number = next(
                    (
                        _text(detail.get("value"))
                        for detail in queue_card.get("details", [])
                        if detail.get("label") == "Queue Number"
                    ),
                    "",
                )
                queue_card["queue_number"] = queue_number
            if "queue_leg_index" not in queue_card:
                queue_card["queue_leg_index"] = next(
                    (
                        index for index, related_call in enumerate(related_queue_calls)
                        if index not in used_session_indexes
                        and _text(related_call.get("queue_id")) == queue_number
                    ),
                    0,
                )
            used_session_indexes.add(queue_card["queue_leg_index"])
        for session_index, related_call in enumerate(related_queue_calls):
            if session_index in used_session_indexes:
                continue
            queue_number = _text(related_call.get("queue_id"))
            if not queue_number:
                continue
            queue_card = _destination_event(
                {"type": "queue", "number": queue_number}, metadata,
                _time(related_call.get("entry_time")) or start_time,
            )
            if queue_card:
                queue_card["queue_leg_index"] = session_index
                journey.append(queue_card)
                queue_cards.append(queue_card)
                used_session_indexes.add(session_index)
        for queue_card in queue_cards:
            session_index = queue_card.get("queue_leg_index", 0)
            number_detail = _text(queue_card.get("queue_number"))
            card_attempts = [
                attempt for attempt in attempts
                if attempt.get("queue_session_index") == session_index
            ]
            if card_attempts:
                queue_card["agent_attempts"] = card_attempts
            if session_index < len(session_metrics):
                queue_card["queue_metrics"] = session_metrics[session_index]

    transfers = [dict(item) for item in transfer_specs]
    for transfer in transfers:
        target_agent = _text(transfer.get("target_agent"))
        target_rows = [
            row for row in rows
            if target_agent
            and _text(_value(row, "dst")) == target_agent
            and _text(_value(row, "dcontext")).lower() not in {"recording", "mixmonitor"}
        ]
        if not _text(_value(transfer, "result")) and target_agent and target_rows and not any(
            _normal_status(_value(row, "status")) == "ANSWERED" for row in target_rows
        ):
            transfer["result"] = "FAILED"
    if not transfers and not any(item["kind"] == "forward" for item in path):
        transfers.extend(_infer_cdr_transfers(rows))

    for transfer in transfers:
        source = _text(transfer.get("source"))
        source_queue = _text(transfer.get("source_queue"))
        timestamp = _event_time(transfer)
        target_agent = _text(transfer.get("target_agent"))
        target_queue = _text(transfer.get("target_queue"))
        target_display = _display_party(target_agent, metadata["extensions"]) if target_agent else target_queue
        if target_agent and target_queue and target_queue != source_queue:
            queue_meta = metadata.get("queues", {}).get(target_queue, {}) or {}
            queue_name = _safe_name(queue_meta.get("name") or queue_meta.get("queue_name"), f"Queue {target_queue}")
            target_display = f"{target_display} in Queue: {queue_name} ({target_queue})"
        for attempt in attempts:
            if (
                attempt.get("extension") == source
                and (not source_queue or attempt.get("queue_number") == source_queue)
                and attempt.get("status") == "Answered"
                and _time_key(attempt.get("attempt_ended_at")) <= _time_key(timestamp)
            ):
                attempt["termination_reason"] = "Transferred"
                attempt["transferred_to"] = target_display

    answers = _answer_targets(rows, queue_call, attempts, metadata, transfers)
    for target, answer_time in answers:
        # Queue agent answers are already represented in the agent-attempt
        # section; still expose the final meaningful answer as a card.
        journey.append(_event("answered", "Answered", answer_time or start_time,
                              subtitle=_display_party(target, metadata["extensions"])))

    forward_items = [item for item in path if item["kind"] == "forward"]
    for item in forward_items:
        source = _display_party(item.get("source"), metadata["extensions"])
        target = _display_party(item.get("target"), metadata["extensions"])
        reason = _text(item.get("reason")).replace("_", " ").title() or "Forward"
        reason_text = reason.lower()
        journey.append(_event("forward", "Forward", start_time,
                              subtitle=f"{_display_party(caller, metadata['extensions'])} called {source}; {source} was {reason_text} and the call was forwarded to {target}.",
                              details=[{"label": "Forward Type", "value": reason}, {"label": "Forwarded To", "value": target}]))

    for transfer in transfers:
        source = _text(transfer.get("source") or queue_call.get("agent"))
        target = _text(transfer.get("target_agent")) or _text(transfer.get("target_queue")) or _text(_value(transfer, "agent"))
        if not source or not target:
            continue
        source_display = _display_party(source, metadata["extensions"])
        target_agent = _text(transfer.get("target_agent"))
        target_queue = _text(transfer.get("target_queue"))
        target_queue_display = ""
        if target_queue:
            queue_meta = metadata.get("queues", {}).get(target_queue, {}) or {}
            queue_name = _safe_name(queue_meta.get("name") or queue_meta.get("queue_name"), f"Queue {target_queue}")
            target_queue_display = f"Queue: {queue_name} ({target_queue})"
        target_display = _display_party(target_agent, metadata["extensions"]) if target_agent else target_queue_display
        if target_agent and target_queue and target_queue != _text(transfer.get("source_queue")):
            target_display = f"{target_display} in {target_queue_display}"
        transfer_type = _text(_value(transfer, "transfer_type")) or "Blind Transfer"
        failed = _normal_status(_value(transfer, "result")) == "FAILED"
        if failed:
            subtitle = f"{source_display} attempted to transfer the call to {target_display}."
            details = [
                {"label": "Transfer Type", "value": transfer_type},
                {"label": "Result", "value": "Transfer Failed"},
                {"label": "Returned To", "value": source_display},
            ]
        else:
            subtitle = f"{source_display} transferred the call to {target_display}."
            details = [{"label": "Transfer Type", "value": transfer_type}]
        if transfer.get("source_queue"):
            details.append({"label": "Source Queue", "value": transfer.get("source_queue")})
        if target_queue:
            details.append({"label": "Target Queue", "value": target_queue_display})
        if target_agent:
            details.append({"label": "Target Agent", "value": _display_party(target_agent, metadata["extensions"])})
        journey.append(_event("transfer", "TRANSFERRED" if not failed else "TRANSFER FAILED", _value(transfer, "timestamp") or start_time,
                              subtitle=subtitle, details=details))

    # Keep cards chronological where timestamps are known, but retain the
    # logical path order for metadata-only IVR cards sharing the start time.
    #
    # QueueLog commonly gives TRANSFER and the target ENTERQUEUE the same
    # second.  A plain timestamp sort then lets the target queue card appear
    # before its own transfer.  For a valid transfer, the target queue leg is
    # always logically after TRANSFER, even if its recorded timestamp is equal
    # to (or a fraction before) the transfer timestamp.
    transfer_boundaries = [
        (
            _text(transfer.get("target_queue")),
            _time(_value(transfer, "timestamp")),
        )
        for transfer in transfers
        if (
            _text(transfer.get("target_queue"))
            and _text(transfer.get("target_queue")) != _text(transfer.get("source_queue"))
            and _time(_value(transfer, "timestamp"))
        )
    ]

    def timeline_sort_key(item):
        card = item[1]
        kind = card.get("kind")
        display_time = _time(card.get("time"))
        logical_time = _time_key(display_time)
        phase = 10
        if kind == "transfer":
            phase = 20
        elif kind == "queue":
            queue_number = _text(card.get("queue_number"))
            incoming = [
                transfer_time for target_queue, transfer_time in transfer_boundaries
                if target_queue == queue_number
                and logical_time <= _time_key(transfer_time)
            ]
            if incoming:
                # Move only the ordering boundary; the card keeps its raw
                # QueueLog timestamp for audit/display purposes.
                logical_time = max(logical_time, min(_time_key(value) for value in incoming))
                phase = 30
        elif kind == "answered":
            phase = 40
        elif kind == "end":
            phase = 90
        return logical_time, phase, item[0]

    journey = sorted(
        enumerate(journey),
        key=timeline_sort_key,
    )
    journey = [item for _, item in journey]

    final_result = _final_result(rows, summary_queue_call)
    final_callee = ""
    for target, _ in answers:
        final_callee = target
    if not final_callee:
        final_callee = _text(summary_queue_call.get("agent"))
    if not final_callee and rows:
        final_callee = _text(_value(rows[-1], "dst"))

    hangup_by = _normal_status(summary_queue_call.get("hangup_by"))
    if hangup_by in {"AGENT", "CALLEE", "DESTINATION"}:
        ended_by = "Callee"
    elif hangup_by in {"CALLER", "ORIGINATOR"}:
        ended_by = "Caller"
    else:
        ended_by = "Callee" if final_result == "Answered" else "Caller"
    journey.append(_event("end", "Call Ended", end_time, subtitle=final_result, details=[
        {"label": "Final Result", "value": final_result},
        {"label": "Caller", "value": _display_party(caller, metadata["extensions"])},
        {"label": "Callee", "value": _display_party(final_callee, metadata["extensions"])},
        {"label": "Ended By", "value": ended_by},
    ]))

    return {
        "id": _text(_value(start_row, "uniqueid") or queue_call.get("uniqueid")),
        "call_id": _text(_value(start_row, "uniqueid") or queue_call.get("uniqueid")),
        "uniqueid": _text(_value(start_row, "uniqueid") or queue_call.get("uniqueid")),
        "linkedid": _text(_value(start_row, "linkedid") or queue_call.get("linkedid") or _value(start_row, "uniqueid")),
        "caller": caller,
        "caller_number": caller,
        "caller_display": _display_party(caller, metadata["extensions"]),
        "call_type": call_type,
        "call_type_label": {"internal": "Internal Call", "inbound": "Inbound Call", "outbound": "Outbound Call"}[call_type],
        "status": final_result,
        "final_result": final_result,
        "final_callee": final_callee,
        "final_callee_display": _display_party(final_callee, metadata["extensions"]),
        "ended_by": ended_by,
        "trunk": trunks[0] if trunks else "",
        "did": did,
        "queue_id": _text(summary_queue_call.get("queue_id")),
        "queue_name": _text(summary_queue_call.get("queue_name")),
        "agent": _text(summary_queue_call.get("agent")),
        "has_transfer": bool(transfers),
        "call_time": duration_summary["call_time"],
        "wait_time": duration_summary["wait_time"],
        "talk_time": duration_summary["talk_time"],
        "hold_time": duration_summary["hold_time"],
        "call_time_display": duration_summary["call_time_display"],
        "wait_time_display": duration_summary["wait_time_display"],
        "talk_time_display": duration_summary["talk_time_display"],
        "hold_time_display": duration_summary["hold_time_display"],
        "journey": journey,
        "journey_recorded": bool(path),
        "timeline": [],
    }
