from functools import wraps
import http.client
import ipaddress
import math
import os
import ssl

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

import db

from .constants import DEX_DRIVER_NAME, GRANDSTREAM_DRIVER_NAME, DEVICE_STATUSES, SEMANTIC_KEY_TYPES, SUPPORTED_VENDORS
from .jobs import submit_discovery, submit_notify, submit_reprovision
from .network import local_interfaces, target_from_last_octet
from .repositories import DexRepository
from .services import ProvisioningService
from .secrets import DexSecretProvider
from .validators import normalize_mac, validate_common_filename, validate_config_text, validate_count, validate_host, validate_ip, validate_ldap_filter, validate_provisioning_path, validate_scan_cidr

DEX_VENDOR_LABELS = {"FIBERME": "FiberMe", "FANVIL": "Fanvil", "GRANDSTREAM": "Grandstream"}


def _repo():
    return current_app.extensions["dex"]["repo"]


def _provisioning():
    return current_app.extensions["dex"]["provisioning"]


def _allowed(module, action):
    checker = current_app.extensions["dex"]["has_permission"]
    return bool(checker(module, action))


def dex_permission(module, action):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not _allowed(module, action):
                if request.is_json or request.path.startswith("/dex/api/") or request.headers.get("X-Requested-With"):
                    return jsonify({"error": "Forbidden - Insufficient Permissions"}), 403
                return render_template("403.html", module=module, action=action), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def dex_csrf(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            expected = str(session.get("csrf_token") or "")
            supplied = str(request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or "")
            import secrets
            if not expected or not supplied or not secrets.compare_digest(expected, supplied):
                return jsonify({"error": "Invalid or missing CSRF token"}), 403 if request.is_json or request.path.startswith("/dex/api/") else 403
        return view(*args, **kwargs)
    return wrapped


def _audit(action, details="", result="Success", changes=None):
    try:
        current_app.extensions["dex"]["audit"]("DEX", action, details, result=result, changes=changes)
    except Exception:
        pass


def _pagination(total, default=20):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", default))
    except (TypeError, ValueError):
        per_page = default
    if per_page not in (10, 20, 30, 50, 100):
        per_page = default
    pages = max(1, math.ceil(total / per_page))
    return min(page, pages), per_page, pages


def _model_form(values=None):
    values = values or {}

    def checkbox_value(value):
        if isinstance(value, (list, tuple)):
            value = value[-1] if value else ""
        return int(str(value or "").strip().lower() in {"1", "true", "yes", "on", "checked"})

    return {
        "vendor_code": values.get("vendor_code", "FIBERME"),
        "model_name": values.get("model_name", ""),
        "sip_account_count": values.get("sip_account_count", ""),
        "blf_count": values.get("blf_count", ""),
        "common_config_filename": values.get("common_config_filename", ""),
        "driver_name": values.get("driver_name", GRANDSTREAM_DRIVER_NAME if values.get("vendor_code") == "GRANDSTREAM" else DEX_DRIVER_NAME),
        "enabled": checkbox_value(values.get("enabled", 0)),
        "provisionable": checkbox_value(values.get("provisionable", 0)),
        "tested": checkbox_value(values.get("tested", 0)),
        "blf_mapping_verified": checkbox_value(values.get("blf_mapping_verified", 0)),
        "notes": values.get("notes", ""),
    }


def _parse_model_form(form):
    sip = validate_count(form.get("sip_account_count"), 1, "SIP account count", allow_unknown=True)
    blf = validate_count(form.get("blf_count"), 0, "BLF count", allow_unknown=True)
    common = validate_common_filename(form.get("common_config_filename"))
    enabled = bool(form.get("enabled"))
    provisionable = bool(form.get("provisionable"))
    tested = bool(form.get("tested"))
    blf_mapping_verified = bool(form.get("blf_mapping_verified"))
    if provisionable and (sip is None or blf is None):
        raise ValueError("A provisionable model must define SIP and BLF counts. Enter 0 explicitly for a verified zero BLF count.")
    if blf_mapping_verified and blf is None:
        raise ValueError("BLF mapping cannot be verified while BLF count is unknown.")
    if blf is not None and blf > 0 and not blf_mapping_verified and provisionable:
        raise ValueError("Provisionable BLF models require a verified BLF mapping.")
    vendor_code = form.get("vendor_code", "").strip().upper()
    if vendor_code not in {"FIBERME", "FANVIL", "GRANDSTREAM"}:
        raise ValueError("Unsupported DEX vendor.")
    return {"vendor_code": vendor_code, "model_name": form.get("model_name", "").strip(), "sip_account_count": sip, "blf_count": blf, "common_config_filename": common, "driver_name": GRANDSTREAM_DRIVER_NAME if vendor_code == "GRANDSTREAM" else DEX_DRIVER_NAME, "enabled": enabled, "provisionable": provisionable, "tested": tested, "blf_mapping_verified": blf_mapping_verified, "notes": form.get("notes", "").strip()}


def _config_int(form, key, default, label, minimum=None, maximum=None):
    try:
        value = int(form.get(key) if form.get(key) not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        bounds = []
        if minimum is not None:
            bounds.append(f"at least {minimum}")
        if maximum is not None:
            bounds.append(f"at most {maximum}")
        raise ValueError(f"{label} must be {' and '.join(bounds)}.")
    return value


def _config_float(form, key, default, label, minimum=None, maximum=None):
    try:
        value = float(form.get(key) if form.get(key) not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{label} is outside the allowed range.")
    return value


def _parse_dex_config_form(form, current):
    """Parse the phone-facing settings exposed by the compact DEX Config page.

    Provisioning transport and other legacy defaults deliberately remain
    untouched here; they are required by the Notify/download path but are not
    administrator-facing settings on this page.
    """
    values = {
        "sntp_enabled": int(bool(form.get("sntp_enabled"))),
        "primary_ntp": validate_host(form.get("primary_ntp", current.get("primary_ntp", "")), allow_blank=True, label="NTP server"),
        "timezone": validate_config_text(form.get("timezone", current.get("timezone", "12")), "Time zone", 64),
        # The phone needs both the numeric zone and its display name.  The
        # compact page exposes the numeric Time Zone only; keep the name as a
        # hidden companion value so the generated syntax stays complete.
        "timezone_name": validate_config_text(form.get("timezone_name", current.get("timezone_name", "UTC+3")), "Time zone name", 64),
        "date_format": _config_int(form, "date_format", current.get("date_format") or 6, "Date format", 1, 10),
        "time_format": _config_int(form, "time_format", current.get("time_format") or 0, "Time format", 0, 9),
        # Date separator is intentionally not an administrator-facing field.
        "date_separator": _config_int(form, "date_separator", current.get("date_separator") or 1, "Date separator", 0, 9),
        "mmi_username": current.get("mmi_username", ""),
        "ldap_enabled": 1,
        "ldap_use_rcm_settings": int(bool(current.get("ldap_use_rcm_settings"))),
        "ldap_title": validate_config_text(form.get("ldap_title", current.get("ldap_title", "FCM")), "LDAP title", 128),
    }
    return values


def register_routes(app):
    repo = DexRepository(app.config["DEX_DB_PATH"])
    secrets_provider = DexSecretProvider()
    provisioning = ProvisioningService(repo, app.config["DEX_DB_PATH"], secret_provider=secrets_provider)
    app.extensions["dex"] = {"repo": repo, "provisioning": provisioning, "secrets": secrets_provider, "has_permission": app.config["DEX_HAS_PERMISSION"], "audit": app.config["DEX_AUDIT"]}

    @app.route("/dex/phones")
    @dex_permission("dex_phones", "view")
    def dex_phones():
        search = request.args.get("search", "").strip()
        _, total = repo.list_devices(search=search, page=1, per_page=1)
        page, per_page, pages = _pagination(total)
        rows, _ = repo.list_devices(search=search, page=page, per_page=per_page)
        return render_template("dex/phones.html", devices=rows, total=total, page=page, pages=pages, per_page=per_page, search=search, statuses=DEVICE_STATUSES, interfaces=local_interfaces(), discovery_jobs=repo.recent_discovery_jobs(), recent_operations=repo.recent_operations(), scan_job=request.args.get("scan_job", type=int))

    @app.route("/dex/phones/<int:device_id>")
    @dex_permission("dex_phones", "view")
    def dex_phone_view(device_id):
        device = repo.get_device(device_id)
        if not device:
            return render_template("404.html"), 404
        return render_template("dex/phone_view.html", device=device)

    @app.route("/dex/operations/<int:operation_id>")
    @dex_permission("dex_phones", "view")
    def dex_operation_view(operation_id):
        operation = repo.get_operation(operation_id)
        if not operation:
            return render_template("404.html"), 404
        return render_template("dex/operation_view.html", operation=operation)

    @app.route("/dex/phones/add", methods=["GET", "POST"])
    @dex_permission("dex_phones", "add")
    @dex_csrf
    def dex_phone_add():
        # Show every model definition here, including disabled definitions.
        # A disabled model is still useful for inventory creation, but it must
        # remain inventory-only until an administrator enables and completes it.
        models, _ = repo.list_models(page=1, per_page=10000)
        discovered_models = repo.discovered_undefined_models()
        if request.method == "POST":
            try:
                selected_model = request.form.get("model_id", "").strip()
                model = repo.get_model(selected_model) if selected_model.isdigit() else None
                inventory_only = selected_model == "discovered"
                if model:
                    if model["vendor_code"] not in {"FIBERME", "FANVIL", "GRANDSTREAM"}:
                        raise ValueError("Select a supported DEX model.")
                    vendor_name = model["vendor_name"]
                    model_name = model["model_name"]
                    model_id = model["id"]
                    status = "Model Defined"
                elif inventory_only:
                    vendor_code = request.form.get("discovered_vendor", "").strip().upper()
                    model_name = request.form.get("discovered_model", "").strip()
                    if vendor_code not in {"FIBERME", "FANVIL", "GRANDSTREAM"} or not model_name:
                        raise ValueError("Select a discovered vendor and model.")
                    if repo.get_model_by_name(vendor_code, model_name):
                        raise ValueError("This model is defined in DEX Model; select its defined entry.")
                    vendor_name = {"FIBERME": "FiberMe", "FANVIL": "Fanvil", "GRANDSTREAM": "Grandstream"}[vendor_code]
                    model_id = None
                    status = "Unknown Model"
                else:
                    raise ValueError("Select a defined model or an inventory-only discovered model.")
                mac = normalize_mac(request.form.get("mac"))
                if repo.get_device_by_mac(mac):
                    raise ValueError("A DEX device with this MAC address already exists.")
                ip = validate_ip(request.form.get("ip"), allow_blank=True)
                device_id = repo.upsert_device({"normalized_mac": mac, "ip_address": ip, "vendor": vendor_name, "detected_model": model_name, "model_id": model_id, "mac_source": "Manual", "provision_status": status}, source="Manual")
                changes = [
                    {"setting": "MAC Address", "old": "", "new": mac},
                    {"setting": "Model", "old": "", "new": model_name},
                    {"setting": "Vendor", "old": "", "new": vendor_name},
                    {"setting": "IP Address", "old": "", "new": ip or ""}
                ]
                _audit("Device Added", f"MAC={mac}; Model={model_name}; InventoryOnly={inventory_only}", changes=changes)
                return redirect(url_for("dex_phone_edit", device_id=device_id) if model_id else url_for("dex_phones"))
            except (ValueError, KeyError) as exc:
                flash(str(exc), "danger")
        return render_template("dex/phone_form.html", device=None, models=models, discovered_models=discovered_models, supported_vendors=DEX_VENDOR_LABELS, form_action=url_for("dex_phone_add"), title="Add DEX Phone")

    @app.route("/dex/phones/<int:device_id>/edit", methods=["GET", "POST"])
    @dex_permission("dex_phones", "edit")
    @dex_csrf
    def dex_phone_edit(device_id):
        device = repo.get_device(device_id)
        if not device:
            return render_template("404.html"), 404
        if not (device.get("vendor_code") in ("FIBERME", "FANVIL", "GRANDSTREAM") and device.get("model_id") and device.get("model_enabled") and device.get("provisionable") and device.get("sip_account_count") is not None and device.get("blf_count") is not None):
            flash("This phone's exact model is not provisionable yet. Define verified account and BLF capabilities first.", "warning")
            return redirect(url_for("dex_phones"))
        if request.method == "POST":
            try:
                accounts = []
                for index in range(1, int(device["sip_account_count"]) + 1):
                    accounts.append({"account_index": index, "enabled": request.form.get(f"account_{index}_enabled") == "on", "extension": request.form.get(f"account_{index}_extension", "").strip() or None})
                blf = []
                for index in range(1, int(device["blf_count"]) + 1):
                    blf.append({"key_index": index, "enabled": request.form.get(f"blf_{index}_enabled") == "on", "semantic_type": request.form.get(f"blf_{index}_type", "None"), "title": request.form.get(f"blf_{index}_title", "").strip(), "value": request.form.get(f"blf_{index}_value", "").strip(), "pickup": request.form.get(f"blf_{index}_pickup", "").strip(), "account_index": request.form.get(f"blf_{index}_account", "").strip() or None})
                conflicts = repo.find_extension_conflicts([item.get("extension") for item in accounts if item.get("enabled")], device_id)
                if conflicts and request.form.get("confirm_extension_conflict") != "on":
                    names = ", ".join(f"{item['extension']} ({item['display_mac']})" for item in conflicts)
                    raise ValueError(f"Extension already assigned to another DEX phone: {names}. Confirm shared assignment explicitly to continue.")
                repo.save_assignments(device_id, accounts, blf)
                changes = []
                old_accounts = {a.get("account_index"): a for a in device.get("accounts", [])}
                for new_acc in accounts:
                    idx = new_acc["account_index"]
                    old_acc = old_accounts.get(idx, {})
                    old_ext = str(old_acc.get("extension") or "")
                    new_ext = str(new_acc.get("extension") or "")
                    old_enabled = str(bool(old_acc.get("enabled", False)))
                    new_enabled = str(bool(new_acc.get("enabled", False)))
                    if old_ext != new_ext:
                        changes.append({"setting": f"Account {idx} Extension", "old": old_ext, "new": new_ext})
                    if old_enabled != new_enabled:
                        changes.append({"setting": f"Account {idx} Enabled", "old": old_enabled, "new": new_enabled})

                old_blf = {b.get("key_index"): b for b in device.get("blf", [])}
                for new_b in blf:
                    idx = new_b["key_index"]
                    old_b = old_blf.get(idx, {})
                    old_type = str(old_b.get("semantic_type") or "None")
                    new_type = str(new_b.get("semantic_type") or "None")
                    if old_type != new_type:
                        changes.append({"setting": f"BLF {idx} Type", "old": old_type, "new": new_type})
                    old_title = str(old_b.get("title") or "")
                    new_title = str(new_b.get("title") or "")
                    if old_title != new_title:
                        changes.append({"setting": f"BLF {idx} Title", "old": old_title, "new": new_title})
                    old_val = str(old_b.get("value") or "")
                    new_val = str(new_b.get("value") or "")
                    if old_val != new_val:
                        changes.append({"setting": f"BLF {idx} Value", "old": old_val, "new": new_val})

                if request.form.get("save_mode", "notify") == "notify":
                    submit_notify(current_app._get_current_object(), device_id, session.get("username", ""))
                    flash("Assignments saved. Provisioning was queued; you can continue working in DEXPhone and follow the result in Operation history.", "success")
                else:
                    flash("Assignments saved without sending a provisioning request.", "success")
                _audit("Device Edited", f"Device ID={device_id}", changes=changes)
                return redirect(url_for("dex_phones"))
            except Exception as exc:
                flash(str(exc), "danger")
        from .rcm_data import get_active_extensions
        extensions = get_active_extensions()
        conflicts = repo.find_extension_conflicts([item.get("extension") for item in device.get("accounts", []) if item.get("enabled")], device_id)
        return render_template("dex/phone_form.html", device=device, models=[device], extensions=extensions, extension_conflicts=conflicts, form_action=url_for("dex_phone_edit", device_id=device_id), title="Edit DEX Phone", key_types=SEMANTIC_KEY_TYPES)

    @app.route("/dex/phones/<int:device_id>/refresh", methods=["POST"])
    @dex_permission("dex_phones", "edit")
    @dex_csrf
    def dex_phone_refresh(device_id):
        result = _provisioning().refresh_device(device_id, session.get("username", ""))
        _audit("Device Refreshed", f"Device ID={device_id}; Result={result.get('status')}")
        flash("Device information refreshed." if result.get("status") == "Completed" else f"Refresh failed: {result.get('reason', 'Unknown error')}", "success" if result.get("status") == "Completed" else "danger")
        return redirect(url_for("dex_phone_view", device_id=device_id))

    @app.route("/dex/phones/<int:device_id>/delete", methods=["POST"])
    @dex_permission("dex_phones", "delete")
    @dex_csrf
    def dex_phone_delete(device_id):
        device = repo.get_device(device_id)
        try:
            normalized = provisioning.delete_device(device_id)
            _audit("Device Deleted", f"MAC={normalized}")
            flash("DEX phone deleted. PBX extensions were not changed.", "success")
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("dex_phones"))

    @app.route("/dex/phones/bulk-delete", methods=["POST"])
    @dex_permission("dex_phones", "delete")
    @dex_csrf
    def dex_phone_bulk_delete():
        results = []
        for raw_id in request.form.getlist("device_ids"):
            try:
                device_id = int(raw_id)
                normalized = provisioning.delete_device(device_id)
                results.append({"id": device_id, "status": "deleted"})
            except Exception as exc:
                results.append({"id": raw_id, "status": "failed", "reason": str(exc)})
        _audit("Bulk Device Delete", f"Count={len(results)}")
        deleted = sum(item["status"] == "deleted" for item in results)
        failed = sum(item["status"] == "failed" for item in results)
        flash(f"Bulk delete finished: {deleted} deleted, {failed} failed.", "success" if not failed else "warning")
        for item in results:
            if item["status"] == "failed":
                flash(f"Device {item['id']}: {item.get('reason', 'Delete failed')}", "warning")
        return redirect(url_for("dex_phones"))

    @app.route("/dex/phones/notify", methods=["POST"])
    @dex_permission("dex_phones", "notify")
    @dex_csrf
    def dex_phone_notify():
        device_ids = []
        for raw_id in request.form.getlist("device_ids"):
            try:
                device_ids.append(int(raw_id))
            except (TypeError, ValueError):
                flash(f"Invalid device ID: {raw_id}", "warning")
        if device_ids:
            submit_reprovision(current_app._get_current_object(), device_ids, session.get("username", ""))
        _audit("Bulk Notify", f"Count={len(device_ids)}")
        flash(f"Notify queued for {len(device_ids)} device(s). Track the results in Operation history.", "success")
        return redirect(url_for("dex_phones"))

    @app.route("/dex/phones/reboot", methods=["POST"])
    @dex_permission("dex_phones", "reboot")
    @dex_csrf
    def dex_phone_reboot():
        results = []
        for raw_id in request.form.getlist("device_ids"):
            try:
                results.append({"id": raw_id, **provisioning.reboot(int(raw_id), session.get("username", ""))})
            except Exception as exc:
                results.append({"id": raw_id, "status": "Failed", "reason": str(exc)})
        _audit("Bulk Reboot", f"Count={len(results)}")
        verified = sum(item.get("status") == "Reboot Verified" for item in results)
        unsupported = sum(item.get("status") == "Unsupported" for item in results)
        failed = sum(item.get("status") == "Failed" for item in results)
        warnings = len(results) - verified - unsupported - failed
        level = "success" if not failed and not warnings else "warning"
        flash(f"Reboot finished: {verified} verified, {warnings} incomplete, {unsupported} unsupported, {failed} failed.", level)
        for item in results:
            if item.get("status") != "Reboot Verified":
                flash(f"Device {item['id']}: {item.get('message') or item.get('reason') or item.get('status', 'Reboot failed')}", "warning")
        return redirect(url_for("dex_phones"))

    @app.route("/dex/phones/scan", methods=["POST"])
    @dex_permission("dex_phones", "autoscan")
    @dex_csrf
    def dex_phone_scan():
        try:
            network = validate_scan_cidr(request.form.get("cidr", ""), max_hosts=256)
            if not request.form.get("scan_all"):
                target = target_from_last_octet(str(network), request.form.get("scan_ip"))
                if not target:
                    raise ValueError("Enter the final IP octet or choose Scan All.")
                target_cidr = target
            else:
                target_cidr = str(network)
            job_id = repo.create_discovery_job(target_cidr, session.get("username", ""))
            submit_discovery(current_app._get_current_object(), job_id)
            _audit("Device Discovery Started", f"CIDR={network}")
            flash(f"Discovery job {job_id} started.", "success")
            return redirect(url_for("dex_phones", scan_job=job_id))
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("dex_phones"))

    @app.route("/dex/api/scan/<int:job_id>")
    @dex_permission("dex_phones", "view")
    def dex_scan_status(job_id):
        job = repo.discovery_job(job_id)
        if not job:
            return jsonify({"error": "Not found"}), 404
        job["results"] = repo.discovery_results(job_id)
        return jsonify(job)

    @app.route("/dex/api/scan/<int:job_id>/cancel", methods=["POST"])
    @dex_permission("dex_phones", "autoscan")
    @dex_csrf
    def dex_scan_cancel(job_id):
        cancelled = repo.cancel_discovery_job(job_id)
        if cancelled:
            _audit("Device Discovery Cancelled", f"Job ID={job_id}")
        return jsonify({"cancelled": cancelled, "job": repo.discovery_job(job_id)}), 200 if cancelled else 409

    @app.route("/dex/models")
    @dex_permission("dex_models", "view")
    def dex_models():
        search = request.args.get("search", "").strip()
        vendor = request.args.get("vendor", "").strip()
        enabled = request.args.get("enabled", "").strip()
        tested = request.args.get("tested", "").strip()
        provisionable = request.args.get("provisionable", "").strip()
        _, total = repo.list_models(search, vendor, enabled, tested, provisionable, page=1, per_page=1)
        page, per_page, pages = _pagination(total)
        rows, _ = repo.list_models(search, vendor, enabled, tested, provisionable, page=page, per_page=per_page)
        return render_template("dex/models.html", models=rows, total=total, page=page, pages=pages, per_page=per_page, search=search, vendor=vendor, enabled=enabled, tested=tested, provisionable=provisionable, supported_vendors=DEX_VENDOR_LABELS)

    @app.route("/dex/models/add", methods=["GET", "POST"])
    @dex_permission("dex_models", "add")
    @dex_csrf
    def dex_model_add():
        values = _model_form({"vendor_code": request.args.get("vendor_code", "FIBERME"), "model_name": request.args.get("model_name", "")})
        if request.method == "POST":
            try:
                values = _parse_model_form(request.form)
                model = repo.save_model(values)
                _audit("Model Added", f"Vendor={model['vendor_name']}; Model={model['model_name']}")
                return redirect(url_for("dex_models"))
            except Exception as exc:
                flash(str(exc), "danger")
                values = _model_form(request.form)
        return render_template("dex/model_form.html", model=values, title="Add DEX Model", supported_vendors=DEX_VENDOR_LABELS)

    @app.route("/dex/models/<int:model_id>")
    @dex_permission("dex_models", "view")
    def dex_model_view(model_id):
        model = repo.get_model(model_id)
        if not model:
            return render_template("404.html"), 404
        return render_template("dex/model_view.html", model=model)

    @app.route("/dex/models/<int:model_id>/edit", methods=["GET", "POST"])
    @dex_permission("dex_models", "edit")
    @dex_csrf
    def dex_model_edit(model_id):
        model = repo.get_model(model_id)
        if not model:
            return render_template("404.html"), 404
        values = _model_form(model)
        if request.method == "POST":
            try:
                values = _parse_model_form(request.form)
                repo.save_model(values, model_id=model_id)
                _audit("Model Edited", f"Model ID={model_id}")
                return redirect(url_for("dex_model_view", model_id=model_id))
            except Exception as exc:
                flash(str(exc), "danger")
                values = _model_form(request.form)
        return render_template("dex/model_form.html", model=values, title="Edit DEX Model", model_id=model_id, supported_vendors=DEX_VENDOR_LABELS)

    @app.route("/dex/models/<int:model_id>/delete", methods=["POST"])
    @dex_permission("dex_models", "delete")
    @dex_csrf
    def dex_model_delete(model_id):
        try:
            repo.delete_model(model_id)
            _audit("Model Deleted", f"Model ID={model_id}")
            flash("DEX model deleted.", "success")
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("dex_models"))

    @app.route("/dex/models/bulk", methods=["POST"])
    @dex_permission("dex_models", "edit")
    @dex_csrf
    def dex_model_bulk():
        model_ids = request.form.getlist("model_ids")
        action = request.form.get("bulk_action", "")
        try:
            if action not in {"enable", "disable"}:
                raise ValueError("Choose a model bulk action.")
            count = repo.bulk_set_model_enabled(model_ids, action == "enable")
            _audit("Bulk Model Status", f"Action={action}; Count={count}")
            flash(f"{count} model(s) updated.", "success")
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("dex_models"))

    @app.route("/dex/models/bulk-delete", methods=["POST"])
    @dex_permission("dex_models", "delete")
    @dex_csrf
    def dex_model_bulk_delete():
        try:
            count = repo.bulk_delete_models(request.form.getlist("model_ids"))
            _audit("Bulk Model Delete", f"Count={count}")
            flash(f"{count} model(s) deleted.", "success")
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("dex_models"))

    @app.route("/dex/models/<int:model_id>/toggle", methods=["POST"])
    @dex_permission("dex_models", "edit")
    @dex_csrf
    def dex_model_toggle(model_id):
        repo.toggle_model(model_id, bool(request.form.get("enabled")))
        return redirect(url_for("dex_models"))

    @app.route("/dex/models/<int:model_id>/tested", methods=["POST"])
    @dex_permission("dex_models", "edit")
    @dex_csrf
    def dex_model_tested(model_id):
        with repo._conn() as conn:
            conn.execute("UPDATE dex_models SET tested = 1, verification_status = 'Device Tested', updated_at = ? WHERE id = ?", (repo.now() if hasattr(repo, "now") else __import__("datetime").datetime.now().isoformat(), model_id))
            conn.commit()
        flash("Model marked Device Tested. Confirm its capability values before provisioning.", "warning")
        return redirect(url_for("dex_model_view", model_id=model_id))

    @app.route("/dex/config", methods=["GET", "POST"])
    @dex_permission("dex_config", "view")
    @dex_csrf
    def dex_config():
        config = repo.get_config()
        if request.method == "POST":
            if not _allowed("dex_config", "edit"):
                return render_template("403.html", module="dex_config", action="edit"), 403
            values = {}
            try:
                values = _parse_dex_config_form(request.form, config)
                mmi_password = request.form.get("mmi_password", "")
                ldap_password = request.form.get("ldap_password", "")
                if mmi_password and request.form.get("mmi_password_confirm") and mmi_password != request.form.get("mmi_password_confirm", ""):
                    raise ValueError("MMI password confirmation does not match.")
                validate_config_text(mmi_password, "MMI password", 256)
                validate_config_text(ldap_password, "LDAP password", 512)
                if ldap_password:
                    values["ldap_password_encrypted"] = secrets_provider.encrypt(ldap_password)
                if mmi_password:
                    values["mmi_password_encrypted"] = secrets_provider.encrypt(mmi_password)
                if request.form.get("save_mode") == "reprovision" and not values["provisioning_enabled"]:
                    raise ValueError("Enable provisioning before re-provisioning devices.")
                repo.save_config(values)
                _audit("Global DEX Config Edited", "Global provisioning and managed defaults updated")
                if request.form.get("save_mode") == "reprovision":
                    if not _allowed("dex_phones", "notify"):
                        raise PermissionError("DEX Phone Notify permission is required for bulk re-provisioning.")
                    device_ids = [device["id"] for device in repo.provisionable_devices()]
                    if not device_ids:
                        flash("DEX configuration saved. No provisionable devices are currently configured.", "success")
                    else:
                        submit_reprovision(current_app._get_current_object(), device_ids, session.get("username", ""))
                        flash(f"DEX configuration saved. Re-provisioning queued for {len(device_ids)} device(s). Track results in Operation history.", "success")
                else:
                    flash("DEX configuration saved. Existing device files were not regenerated automatically.", "success")
                config = repo.get_config()
            except Exception as exc:
                # Keep validated non-secret input visible after a validation
                # error; never copy either password field into the template.
                if values:
                    config = {**config, **values}
                flash(str(exc), "danger")
        # The phone administrator password remains encrypted at rest, but it
        # is intentionally shown on this restricted administrator page so it
        # can be used when logging into the phones.
        config_for_template = dict(config or {})
        try:
            config_for_template["mmi_password"] = secrets_provider.decrypt(config_for_template.get("mmi_password_encrypted"))
        except Exception:
            # Keep the page usable if the encryption key is temporarily
            # unavailable; provisioning will report the underlying secret
            # provider error when it needs the credential.
            config_for_template["mmi_password"] = ""
            flash("The saved phone administrator password could not be decrypted.", "danger")
        return render_template("dex/config.html", config=config_for_template)

    @app.route("/dex/config/verify", methods=["POST"])
    @dex_permission("dex_config", "edit")
    @dex_csrf
    def dex_config_verify():
        config = repo.get_config()
        host = config.get("provisioning_ip") or ""
        local_hosts = {str(item.get("ip")) for item in local_interfaces() if item.get("ip")}
        if not host or host not in local_hosts:
            flash("The saved provisioning IP is not a local PBX interface. Select a local interface before testing HTTPS.", "danger")
            return redirect(url_for("dex_config"))
        path = "/" + validate_provisioning_path(config.get("provisioning_path") or "DEXPhone") + "/"
        connection = None
        try:
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(host, int(config.get("provisioning_port") or 8090), timeout=3, context=context)
            connection.request("HEAD", path, headers={"User-Agent": "RCM7021-Dex-Verify"})
            response = connection.getresponse()
            status = int(response.status)
            if status in (401, 403):
                flash(f"HTTPS is reachable and access is restricted correctly (HTTP {status}).", "success")
            elif 200 <= status < 400:
                flash(f"HTTPS endpoint is reachable (HTTP {status}). Confirm directory listing remains disabled.", "warning")
            else:
                flash(f"HTTPS endpoint responded with HTTP {status}.", "danger")
        except (OSError, ValueError) as exc:
            flash(f"HTTPS verification failed: {exc}", "danger")
        finally:
            if connection:
                connection.close()
        return redirect(url_for("dex_config"))

    @app.route("/dex/api/models")
    @dex_permission("dex_phones", "view")
    def dex_api_models():
        vendor = request.args.get("vendor", "")
        return jsonify([{key: item.get(key) for key in ("id", "model_name", "vendor_code", "sip_account_count", "blf_count", "provisionable", "enabled")} for item in repo.enabled_models(vendor)])

    @app.route("/dex/api/extensions")
    @dex_permission("dex_phones", "view")
    def dex_api_extensions():
        from .rcm_data import get_active_extensions
        return jsonify([{"ext": item["ext"], "name": item.get("name", "")} for item in get_active_extensions()])
