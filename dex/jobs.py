import os
import socket
import threading
import uuid
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .repositories import DexRepository
from .network import grandstream_http_identity, mac_for_ip
from .services import parse_options_response, sip_options
from .services import ProvisioningService
from .secrets import DexSecretProvider
from .validators import validate_scan_cidr

_executor = None
_executor_lock = threading.Lock()
DISCOVERY_VENDORS = {"FiberMe", "Fanvil", "Grandstream"}


def start_worker(app):
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dex-job")
    app.extensions["dex_executor"] = _executor


def submit_discovery(app, job_id):
    start_worker(app)
    _executor.submit(_run_discovery, app.config.get("DEX_DB_PATH"), job_id)


def submit_reprovision(app, device_ids, requested_by=""):
    """Queue a bounded sequential re-provision batch outside the web request."""
    start_worker(app)
    ids = [int(device_id) for device_id in device_ids]
    return _executor.submit(_run_reprovision, app.config.get("DEX_DB_PATH"), ids, requested_by)


def submit_notify(app, device_id, requested_by=""):
    """Queue one Notify so the phone edit page never waits on the handset."""
    start_worker(app)
    return _executor.submit(_run_reprovision, app.config.get("DEX_DB_PATH"), [int(device_id)], requested_by)


def _run_reprovision(db_path, device_ids, requested_by):
    repo = DexRepository(db_path)
    service = ProvisioningService(repo, db_path, secret_provider=DexSecretProvider())
    for device_id in device_ids:
        try:
            service.notify(device_id, requested_by)
        except Exception:
            # The individual provisioning operation records and device status
            # contain the sanitized failure. Continue with the remaining batch.
            continue


def _run_discovery(db_path, job_id):
    repo = DexRepository(db_path)
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
    if not repo.claim_discovery_job(job_id, owner):
        return
    job = repo.discovery_job(job_id)
    try:
        network = validate_scan_cidr(job["target_cidr"], max_hosts=256)
        targets = [str(host) for host in network.hosts()]
        known_contact_ports = {}
        try:
            import asterisk_helper
            for entries in asterisk_helper.get_pjsip_contacts().values():
                for entry in entries:
                    uri = str(entry.get("uri", ""))
                    match = re.search(r"@([0-9.]+):(\d+)", uri)
                    if match:
                        known_contact_ports.setdefault(match.group(1), set()).add(int(match.group(2)))
        except Exception:
            # Discovery remains useful with only its bounded default ports
            # when Asterisk is unavailable.
            known_contact_ports = {}
        total = max(1, len(targets))
        for index, ip in enumerate(targets, 1):
            current_job = repo.discovery_job(job_id) or {}
            if current_job.get("status") == "Cancelled":
                return
            repo.update_discovery_job(job_id, progress=int(index * 100 / total), current_target=ip)
            response = None
            # Grandstream phones commonly use 5060, while the observed
            # GXV3350 inventory phone is registered on 5062. Probe both
            # bounded SIP ports during discovery.
            ports = [5060, 5062]
            for sip_port in sorted(known_contact_ports.get(ip, ())):
                if sip_port not in ports:
                    ports.append(sip_port)
            for sip_port in ports:
                response = sip_options(ip, timeout=0.7, target_port=sip_port)
                if response:
                    response["sip_target_port"] = sip_port
                    break
            if not response:
                # A Grandstream can remain reachable through its web UI while
                # SIP is unregistered or listening on a dynamic contact port.
                # Use the HTTP Server header as a model-only fallback.
                http_identity = grandstream_http_identity(ip)
                if http_identity:
                    normalized_mac = mac_for_ip(ip)
                    response = {
                        "ip_address": ip,
                        "normalized_mac": normalized_mac,
                        "vendor": "Grandstream",
                        "model": http_identity["model"],
                        "firmware": "",
                        "raw_user_agent": f"Grandstream {http_identity['model']} (HTTP Server: {http_identity['server']})",
                        "confidence": "HTTP Model Only",
                        "response_code": http_identity["response_code"],
                        "headers": {"server": http_identity["server"]},
                        "discovery_source": "HTTP Server header",
                    }
            if not response:
                continue
            # A SIP response alone does not make a device a DEX phone.  The
            # inventory must contain only the three supported phone vendors;
            # PBXs, gateways, Yealink devices, and generic SIP responders are
            # deliberately excluded before results or devices are persisted.
            if response.get("vendor") not in DISCOVERY_VENDORS:
                continue
            current_job = repo.discovery_job(job_id) or {}
            repo.update_discovery_job(job_id, responses_received=int(current_job.get("responses_received", 0)) + 1)
            if not response.get("normalized_mac"):
                response["normalized_mac"] = mac_for_ip(response.get("ip_address"))
                if response.get("normalized_mac"):
                    response["mac_source"] = "ARP"
            repo.add_discovery_result(job_id, response)
            model = repo.get_model_by_name(response.get("vendor", ""), response.get("model", ""))
            if not model and response.get("vendor") in ("FiberMe", "Fanvil", "Grandstream"):
                # Discovery confirms identity independently of MAC exposure.
                # Create the DEX Model draft even when the SIP User-Agent did
                # not contain a MAC and ARP could not resolve one.
                model = repo.ensure_discovered_model(
                    response.get("vendor"), response.get("model"), response.get("raw_user_agent", "")
                )
            if not response.get("normalized_mac"):
                continue
            response["model_id"] = model["id"] if model else None
            response["detected_model"] = response.get("model", "")
            response["mac_source"] = "SIP User-Agent"
            before = repo.get_device_by_mac(response["normalized_mac"]) if hasattr(repo, "get_device_by_mac") else None
            repo.upsert_device(response, source="SIP OPTIONS")
            if model:
                current_device = repo.get_device_by_mac(response["normalized_mac"])
                if current_device and current_device.get("provision_status") in ("Unknown Model", ""):
                    repo.update_device_status(current_device["id"], provision_status="Model Defined")
            count_field = "new_devices" if before is None else "updated_devices"
            current_job = repo.discovery_job(job_id) or {}
            repo.update_discovery_job(job_id, **{count_field: int(current_job.get(count_field, 0)) + 1, "phones_found": int(current_job.get("phones_found", 0)) + (0 if before else 1)})
        current_job = repo.discovery_job(job_id) or {}
        if current_job.get("status") != "Cancelled":
            repo.update_discovery_job(job_id, status="Completed", progress=100, current_target="", finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except Exception as exc:
        current_job = repo.discovery_job(job_id) or {}
        if current_job.get("status") != "Cancelled":
            repo.update_discovery_job(job_id, status="Failed", finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), error_message=str(exc))
