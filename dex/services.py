import ipaddress
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime, timezone

from .config_generator import ConfigGenerationError, FanvilFiberMeConfigGenerator, GrandstreamXmlConfigGenerator
from .constants import DEFAULT_NOTIFY_USER_AGENT, GRANDSTREAM_PNP_SOURCE_PORT, PROVISION_ACCESS_LOG, PROVISION_HTTP_ACCESS_LOG, PROVISION_HTTP_PORT, PROVISION_PORT, PROVISION_URL_PATH
from .drivers import FanvilFiberMeProvisioningEngine, GrandstreamProvisioningEngine, UnsupportedOperation, identify_device_user_agent
from .repositories import DexRepository, now
from .network import mac_for_ip
from .validators import normalize_mac, validate_provisioning_path, validate_scan_cidr


def local_ip_for(target_ip="192.168.99.90"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((str(target_ip), 5060))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def _parse_sip_status(payload):
    first = payload.decode("utf-8", "replace").splitlines()[0] if payload else ""
    match = re.match(r"SIP/2\.0\s+(\d{3})", first)
    return int(match.group(1)) if match else None


def _safe_details(values):
    secret_words = ("password", "secret", "authorization", "cookie", "token")
    return {key: "******" if any(word in key.lower() for word in secret_words) else value for key, value in values.items()}


class ProvisioningService:
    def __init__(self, repo, db_path, root=None, secret_provider=None):
        self.repo = repo
        self.secret_provider = secret_provider
        self.engine = FanvilFiberMeProvisioningEngine()
        self.generator = FanvilFiberMeConfigGenerator(self.engine, repo, db_path, root=root) if root else FanvilFiberMeConfigGenerator(self.engine, repo, db_path)
        self._db_path = db_path
        self._root = root

    def _engine_for(self, device):
        vendor = str(device.get("vendor_code") or device.get("vendor") or "").upper()
        return GrandstreamProvisioningEngine() if vendor == "GRANDSTREAM" else FanvilFiberMeProvisioningEngine()

    def _generator_for(self, device):
        engine = self._engine_for(device)
        generator_type = GrandstreamXmlConfigGenerator if isinstance(engine, GrandstreamProvisioningEngine) else FanvilFiberMeConfigGenerator
        return generator_type(engine, self.repo, self._db_path, root=self._root) if self._root else generator_type(engine, self.repo, self._db_path)

    @staticmethod
    def _endpoint(config, engine):
        if engine.provisioning_scheme == "http":
            return "http", int(config.get("provisioning_http_port") or PROVISION_HTTP_PORT), PROVISION_HTTP_ACCESS_LOG
        return "https", int(config.get("provisioning_port") or PROVISION_PORT), PROVISION_ACCESS_LOG

    @staticmethod
    def _notify_source_port(config, engine):
        configured = int(config.get("notify_source_port") or 0)
        # Grandstream Zero Config uses the PBX's fixed 6060 source port in
        # the captured UCM exchange. Preserve an explicit DEX override, but
        # never fall back to an ephemeral port for the default Grandstream
        # path.
        if configured == 0 and isinstance(engine, GrandstreamProvisioningEngine):
            return GRANDSTREAM_PNP_SOURCE_PORT
        return configured

    def _fresh_pnp_contact_port(self, device_id, device, max_age=900):
        """Return a recent Grandstream Contact for assignment-time Notify.

        Bootstrap intentionally leaves SIP unregistered, so the PnP Contact
        is the only routable destination until DEX sends the assigned
        account.  Keep it for a bounded 15 minutes, while still rejecting a
        Contact that belongs to an older IP observation.
        """
        try:
            contact = self.repo.get_pnp_contact(device_id) or {}
        except Exception:
            return None
        if not isinstance(contact, dict):
            return None
        if contact.get("pnp_contact_ip") != device.get("ip_address"):
            return None
        try:
            port = int(contact.get("pnp_contact_port") or 0)
            seen_at = datetime.fromisoformat(str(contact.get("pnp_contact_seen_at", "")).replace("Z", "+00:00"))
            if seen_at.tzinfo is None:
                seen_at = seen_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - seen_at).total_seconds()
        except (TypeError, ValueError):
            return None
        return port if 1 <= port <= 65535 and 0 <= age <= max_age else None

    def prepare_config(self, device_id, baseline=False):
        device = self.repo.get_device(device_id)
        if not device:
            raise ConfigGenerationError("Device not found.")
        config = self.repo.get_config()
        if not config.get("provisioning_enabled"):
            raise ConfigGenerationError("DEX provisioning is disabled in DEX Config.")
        if self.secret_provider:
            if config.get("mmi_password_encrypted"):
                config["mmi_password"] = self.secret_provider.decrypt(config["mmi_password_encrypted"])
            if config.get("ldap_password_encrypted"):
                config["ldap_password"] = self.secret_provider.decrypt(config["ldap_password_encrypted"])
        is_grandstream = str(device.get("vendor_code") or device.get("vendor") or "").upper() == "GRANDSTREAM"
        if baseline and not is_grandstream:
            raise ConfigGenerationError("Bootstrap provisioning is supported only for Grandstream devices.")
        if not baseline and (not device.get("model_enabled") or not device.get("provisionable") or device.get("sip_account_count") is None or device.get("blf_count") is None):
            raise ConfigGenerationError("Model is disabled or not provisionable with verified capabilities.")
        if not config.get("provisioning_ip"):
            config["provisioning_ip"] = local_ip_for(device.get("ip_address"))
        generator = self._generator_for(device)
        if baseline:
            data = generator.render(device, config, include_assignments=False)
        else:
            data = generator.render(device, config)
        metadata = generator.validate(data, device["normalized_mac"])
        self.repo.update_device_status(device_id, provision_status="Config Generated", last_error="")
        published = generator.publish(device, data)
        self.repo.save_generated_config(device_id, published["filename"], metadata["sha256"], metadata["size"])
        self.repo.update_device_status(device_id, provision_status="Config Published", last_error="")
        return device, config, metadata, published

    def notify(self, device_id, requested_by="", contact_port=None, source_port_override=None, baseline=False):
        device = self.repo.get_device(device_id)
        if not device:
            raise ValueError("Device not found.")
        if not device.get("ip_address"):
            raise ValueError("No IP address is available for this device.")
        engine = self._engine_for(device)
        vendor = str(device.get("vendor_code") or device.get("vendor") or "").upper()
        if vendor not in engine.supported_vendors:
            raise ValueError("Vendor is not supported by the DEX provisioning engine.")
        if not baseline and (not device.get("model_enabled") or not device.get("provisionable") or device.get("sip_account_count") is None or device.get("blf_count") is None):
            raise ValueError("Model is disabled or not provisionable with verified capabilities.")
        if baseline and not isinstance(engine, GrandstreamProvisioningEngine):
            raise ValueError("Bootstrap provisioning is supported only for Grandstream devices.")
        config = self.repo.get_config()
        if not config.get("provisioning_enabled"):
            raise ValueError("DEX provisioning is disabled in DEX Config.")
        pbx_ip = config.get("provisioning_ip") or local_ip_for(device["ip_address"])
        if not pbx_ip:
            raise ValueError("Could not determine a local PBX address for the phone network.")
        path = validate_provisioning_path(config.get("provisioning_path") or "DEXPhone")
        scheme, port, access_log = self._endpoint(config, engine)
        url = f"{scheme}://{pbx_ip}:{port}/{path}/"
        filename = engine.expected_filename(device["normalized_mac"])
        expected_filenames = engine.expected_filenames(device["normalized_mac"])
        operation_id = self.repo.create_operation(device_id, "notify", requested_by, requested_url=url, expected_filename=filename)
        self.repo.update_operation(operation_id, status="Running", started_at=now())
        self.repo.add_operation_event(operation_id, "Config Generation Started")
        try:
            device, config, metadata, published = self.prepare_config(device_id, baseline=baseline)
            if baseline:
                self.repo.add_operation_event(operation_id, "Grandstream Bootstrap Mode", {"assignments": "omitted", "reason": "awaiting DEX extension/BLF assignment"})
            self.repo.add_operation_event(operation_id, "Config Published", _safe_details({"filename": filename, "sha256": metadata["sha256"], "size": metadata["size"]}))
            self.repo.update_operation(operation_id, expected_filename=filename, sent_at=now())
            # These fields describe the current provisioning attempt.  Clear
            # stale responses from an earlier attempt before sending a new one.
            self.repo.update_device_status(device_id, last_sip_status=None, last_http_status=None, last_error="", last_failure_stage="")
        except Exception as exc:
            self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="generation", error_message=str(exc))
            self.repo.update_device_status(device_id, provision_status="Failed", last_failure_stage="generation", last_error=str(exc))
            raise

        source_port = int(source_port_override if source_port_override is not None else self._notify_source_port(config, engine))
        timeout = min(max(float(config.get("notify_timeout") or 3.0), 0.5), 15.0)
        target_port = int(contact_port) if contact_port is not None else self._sip_target_port(device["ip_address"])
        if isinstance(engine, GrandstreamProvisioningEngine) and target_port is None:
            target_port = self._fresh_pnp_contact_port(device_id, device)
        if isinstance(engine, GrandstreamProvisioningEngine) and target_port is None:
            message = "Grandstream SIP registration is not observed; dynamic contact port is unknown. Config was published, but NOTIFY was not sent to port 5060."
            self.repo.update_operation(operation_id, status="CompletedWithWarnings", completed_at=now(), error_stage="preflight", error_message=message)
            self.repo.update_device_status(device_id, provision_status="Awaiting SIP Registration", last_error=message, last_failure_stage="")
            self.repo.add_operation_event(operation_id, "Awaiting SIP Registration", {"action": "Bootstrap the phone once, then retry Notify"})
            return {"operation_id": operation_id, "status": "Awaiting SIP Registration", "sip_status": None, "http": None, "warning": message}
        target_port = target_port or 5060
        access_log_offset = self._access_log_offset(access_log)
        sip_status = None
        notify_warning = ""
        max_attempts = 3 if isinstance(engine, GrandstreamProvisioningEngine) else 1
        for attempt in range(max_attempts):
            if attempt:
                time.sleep(min(float(attempt), 2.0))
                # A fresh PnP/SIP observation may have supplied a new dynamic
                # Contact while the previous attempt was timing out.
                refreshed_port = self._sip_target_port(device["ip_address"])
                if refreshed_port is None and isinstance(engine, GrandstreamProvisioningEngine):
                    refreshed_port = self._fresh_pnp_contact_port(device_id, device)
                if refreshed_port:
                    target_port = int(refreshed_port)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            try:
                sock.bind((pbx_ip, source_port))
                actual_port = sock.getsockname()[1]
                packet = engine.build_notify(pbx_ip, device["ip_address"], url, actual_port, config.get("notify_user_agent") or DEFAULT_NOTIFY_USER_AGENT, target_port=target_port)
                self.repo.update_device_status(device_id, provision_status="NOTIFY Sent", last_notify_at=now())
                sock.sendto(packet, (device["ip_address"], target_port))
                self.repo.add_operation_event(operation_id, "NOTIFY Sent", {"destination": f"{device['ip_address']}:{target_port}", "attempt": attempt + 1, "event": "ua-profile", "content_type": engine.notify_content_type})
                try:
                    response, address = sock.recvfrom(65535)
                    status = _parse_sip_status(response)
                    sip_status = status
                    self.repo.update_operation(operation_id, sip_response_at=now(), sip_status=status)
                    notify_warning = "" if status == 200 else f"Phone returned SIP {status or 'unknown'}"
                    self.repo.update_device_status(device_id, last_sip_status=status, provision_status="NOTIFY Accepted" if status == 200 else "NOTIFY Sent", last_failure_stage="notify" if notify_warning else "", last_error=notify_warning)
                    self.repo.add_operation_event(operation_id, "NOTIFY Response", {"status": status, "source": address[0], "attempt": attempt + 1})
                    break
                except socket.timeout:
                    notify_warning = "NOTIFY response was not observed before timeout"
                    self.repo.update_device_status(device_id, last_sip_status=None, provision_status="NOTIFY Sent", last_failure_stage="notify", last_error=notify_warning)
                    self.repo.add_operation_event(operation_id, "NOTIFY Timeout", {"timeout_seconds": timeout, "attempt": attempt + 1})
                    if attempt + 1 == max_attempts:
                        break
            except OSError as exc:
                message = f"SIP NOTIFY transport error: {exc}"
                self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="notify", error_message=message, sip_status=sip_status)
                self.repo.update_device_status(device_id, provision_status="Failed", last_sip_status=None, last_failure_stage="notify", last_error=message)
                return {"operation_id": operation_id, "status": "Failed", "sip_status": sip_status, "http": None}
            finally:
                sock.close()

        self.repo.update_device_status(device_id, provision_status="Config Requested", last_error=notify_warning, last_failure_stage="notify" if notify_warning else "")
        # Grandstream GRP phones may acknowledge the NOTIFY immediately but
        # delay the HTTP GET while applying the previous profile.  On the
        # GRP2601P/GRP2602P live test, a Full Config sent during Bootstrap was
        # fetched about 4-6 minutes later on the phone's next provisioning
        # cycle.  A short observer therefore creates a false Failed result.
        observe_timeout = 8.0
        if isinstance(engine, GrandstreamProvisioningEngine):
            observe_timeout = 360.0
        http_observed = self._observe_access_log(filename, device.get("ip_address"), access_log_offset, timeout=observe_timeout, filenames=expected_filenames, access_log_path=access_log)
        if http_observed:
            self.repo.update_operation(operation_id, http_request_at=http_observed.get("time"), http_path=http_observed.get("path", ""), http_status=http_observed.get("status"), http_bytes=http_observed.get("bytes"))
            self.repo.update_device_status(device_id, last_http_status=http_observed.get("status"))
            if http_observed.get("status") != 200 or not any(http_observed.get("path", "").endswith("/" + item) for item in expected_filenames):
                message = f"Expected MAC configuration was not downloaded (HTTP {http_observed.get('status')})."
                self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="config_request", error_message=message)
                self.repo.update_device_status(device_id, provision_status="Failed", last_failure_stage="config_request", last_error=message)
                return {"operation_id": operation_id, "status": "Failed", "sip_status": sip_status, "http": http_observed}
            if http_observed.get("status") == 200 and any(http_observed.get("path", "").endswith("/" + item) for item in expected_filenames):
                self.repo.update_device_status(device_id, provision_status="Config Downloaded", last_http_status=200)
                self.repo.add_operation_event(operation_id, "Config Downloaded", {"path": http_observed.get("path"), "status": 200, "bytes": http_observed.get("bytes")})
                self.repo.update_device_status(device_id, provision_status="Applying")
                if baseline:
                    message = "Grandstream bootstrap configuration downloaded; extension and BLF were intentionally omitted."
                    self.repo.update_operation(operation_id, status="Completed", completed_at=now(), error_stage="", error_message=message)
                    self.repo.update_device_status(device_id, provision_status="Config Downloaded", last_success_at=now(), last_error="", last_failure_stage="")
                    self.repo.add_operation_event(operation_id, "Bootstrap Completed", {"assignment_state": "awaiting DEX assignment"})
                    return {"operation_id": operation_id, "status": "Bootstrap Downloaded", "sip_status": sip_status, "http": http_observed, "warning": ""}
        else:
            message = "No request for the expected MAC configuration was observed."
            stage = "notify" if notify_warning and sip_status is None else "config_request"
            if notify_warning and sip_status is None:
                message = f"{notify_warning}; {message}"
            # Grandstream may acknowledge a repeated ua-profile NOTIFY without
            # downloading the XML again when the published file is unchanged.
            # If the phone is already registered, this is a successful
            # idempotent reprovision, not a failed configuration request.
            if sip_status == 200:
                registration_delay = min(max(float(config.get("registration_check_delay") or 3.0), 0.0), 15.0)
                if isinstance(engine, GrandstreamProvisioningEngine):
                    # GRP26xx acknowledges the HTTP request before it has
                    # finished applying the XML and opening its new SIP
                    # Contact.  Do not classify that normal settling window
                    # as a registration failure.
                    registration_delay = max(registration_delay, 8.0)
                registration = self.verify_registration(device, settle_delay=registration_delay)
                self.repo.update_operation(operation_id, registration_result=registration.get("result", ""))
                if registration.get("verified"):
                    warning = "NOTIFY accepted; the existing configuration was already active, so no new HTTP request was observed."
                    self.repo.update_operation(operation_id, status="CompletedWithWarnings", completed_at=now(), error_stage="config_request", error_message=warning, sip_status=sip_status)
                    self.repo.update_device_status(device_id, provision_status="Verified", last_sip_status=sip_status, last_registered_extension=registration.get("extension", ""), last_success_at=now(), last_error=warning, last_failure_stage="")
                    self.repo.add_operation_event(operation_id, "Existing Configuration Active", _safe_details(registration))
                    return {"operation_id": operation_id, "status": "Verified", "sip_status": sip_status, "registration": registration, "http": None, "warning": warning}
            self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage=stage, error_message=message, sip_status=sip_status)
            self.repo.update_device_status(device_id, provision_status="Failed", last_failure_stage=stage, last_error=message)
            return {"operation_id": operation_id, "status": "Failed", "sip_status": sip_status, "http": None}
        registration_delay = min(max(float(config.get("registration_check_delay") or 3.0), 0.0), 15.0)
        if isinstance(engine, GrandstreamProvisioningEngine):
            registration_delay = max(registration_delay, 8.0)
        registration = self.verify_registration(device, settle_delay=registration_delay)
        self.repo.update_operation(operation_id, registration_result=registration.get("result", ""))
        if registration.get("verified"):
            self.repo.update_device_status(device_id, provision_status="Registered", last_registered_extension=registration.get("extension", ""))
            final_operation_status = "Completed" if not notify_warning else "CompletedWithWarnings"
            self.repo.update_operation(operation_id, status=final_operation_status, completed_at=now(), error_stage="notify" if notify_warning else "", error_message=notify_warning)
            self.repo.update_device_status(device_id, provision_status="Verified", last_success_at=now(), last_registered_extension=registration.get("extension", ""), last_error=notify_warning, last_failure_stage="notify" if notify_warning else "")
            self.repo.add_operation_event(operation_id, "Registration Verified", _safe_details(registration))
            return {"operation_id": operation_id, "status": "Verified", "sip_status": sip_status, "registration": registration, "http": http_observed, "warning": notify_warning}
        message = "Configuration downloaded; SIP registration not verified."
        if notify_warning:
            message = f"{message} {notify_warning}."
        self.repo.update_operation(operation_id, status="CompletedWithWarnings", completed_at=now(), error_stage="registration", error_message=message)
        self.repo.update_device_status(device_id, provision_status="Config Downloaded", last_error=message, last_failure_stage="registration")
        return {"operation_id": operation_id, "status": "Config Downloaded", "sip_status": sip_status, "registration": registration, "http": http_observed, "warning": message}

    def refresh_device(self, device_id, requested_by=""):
        device = self.repo.get_device(device_id)
        if not device:
            raise ValueError("Device not found.")
        if not device.get("ip_address"):
            raise ValueError("No IP address is available for this device.")
        operation_id = self.repo.create_operation(device_id, "refresh", requested_by)
        self.repo.update_operation(operation_id, status="Running", started_at=now())
        try:
            parsed = sip_options(device["ip_address"], timeout=1.5, target_port=self._sip_target_port(device["ip_address"]))
            if not parsed:
                raise ValueError("The phone did not answer SIP OPTIONS.")
            model = self.repo.get_model_by_name(parsed.get("vendor", ""), parsed.get("model", ""))
            if not model and parsed.get("vendor") in ("FiberMe", "Fanvil", "Grandstream"):
                model = self.repo.ensure_discovered_model(
                    parsed.get("vendor"), parsed.get("model"), parsed.get("raw_user_agent", "")
                )
            parsed.update({"model_id": model["id"] if model else None, "detected_model": parsed.get("model", ""), "mac_source": "SIP User-Agent"})
            if not parsed.get("normalized_mac"):
                parsed["normalized_mac"] = mac_for_ip(parsed.get("ip_address"))
                if parsed.get("normalized_mac"):
                    parsed["mac_source"] = "ARP"
            if parsed.get("normalized_mac"):
                self.repo.upsert_device(parsed, source="SIP OPTIONS")
            else:
                # Some Grandstream SIP responses identify the model/firmware
                # but omit the MAC. Preserve the existing inventory identity
                # instead of attempting an invalid MAC-keyed upsert.
                self.repo.update_device_status(device_id, last_error="SIP OPTIONS identified the model but did not include a MAC address.")
            refreshed = self.repo.get_device(device_id)
            registration = self.verify_registration(refreshed, settle_delay=0.0)
            if registration.get("verified"):
                self.repo.update_device_status(device_id, provision_status="Verified", last_success_at=now(), last_registered_extension=registration.get("extension", ""), last_error="", last_failure_stage="")
                self.repo.add_operation_event(operation_id, "Registration Verified", _safe_details(registration))
            self.repo.update_operation(operation_id, status="Completed", completed_at=now(), sip_status=parsed.get("response_code"), registration_result="Device information refreshed")
            self.repo.add_operation_event(operation_id, "Device Refreshed", {"response_code": parsed.get("response_code"), "vendor": parsed.get("vendor"), "model": parsed.get("model"), "firmware": parsed.get("firmware")})
            return {"operation_id": operation_id, "status": "Completed", "device": self.repo.get_device(device_id)}
        except Exception as exc:
            self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="refresh", error_message=str(exc))
            self.repo.update_device_status(device_id, last_failure_stage="refresh", last_error=str(exc))
            return {"operation_id": operation_id, "status": "Failed", "reason": str(exc)}

    def _access_log_offset(self, path=PROVISION_ACCESS_LOG):
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def _observe_access_log(self, filename, device_ip, offset, timeout=8.0, filenames=None, access_log_path=PROVISION_ACCESS_LOG):
        # Correlation must use the dedicated DEX provisioning log.  Reading
        # the general Apache log would allow an older unrelated request to be
        # mistaken for this operation.
        # Only the dedicated DEX log is safe for correlation.  The legacy
        # Apache log may contain an older request for the same MAC and would
        # create a false success/failure for the current operation.
        candidates = (access_log_path,)
        filenames = tuple(filenames or (filename,))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for path in candidates:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        if path == access_log_path and offset is not None:
                            current_size = os.path.getsize(path)
                            if current_size >= offset:
                                handle.seek(offset)
                        lines = handle.readlines()
                except OSError:
                    continue
                for line in lines:
                    if device_ip not in line or not any(item in line for item in filenames):
                        continue
                    match = re.search(r'"(?:GET|HEAD)\s+(\S+)\s+HTTP/[^"]+"\s+(\d{3})\s+(\d+|-)', line)
                    if match:
                        return {"path": match.group(1), "status": int(match.group(2)), "bytes": 0 if match.group(3) == "-" else int(match.group(3)), "time": now()}
            time.sleep(0.25)
        return None

    @staticmethod
    def _sip_target_port(device_ip):
        try:
            import asterisk_helper
            contacts = asterisk_helper.get_pjsip_contacts()
            for entries in contacts.values():
                for entry in entries:
                    uri = str(entry.get("uri", ""))
                    match = re.search(rf"@{re.escape(str(device_ip))}:(\d+)", uri)
                    if match:
                        return int(match.group(1))
        except Exception:
            pass
        return None

    def verify_registration(self, device, timeout=8, settle_delay=0.0):
        """Wait once after download, then take one Asterisk registration snapshot."""
        try:
            import asterisk_helper
        except ImportError:
            return {"verified": False, "result": "Asterisk helper unavailable"}
        delay = min(max(float(settle_delay or 0.0), 0.0), 15.0)
        if delay:
            time.sleep(delay)
        contacts = asterisk_helper.get_pjsip_contacts()
        expected = {str(item.get("extension")) for item in device.get("accounts", []) if item.get("enabled")}
        for aor, entries in contacts.items():
            for entry in entries:
                uri = str(entry.get("uri", ""))
                if device.get("ip_address") in uri and str(aor).split("@")[0] in expected:
                    return {"verified": True, "extension": str(aor).split("@")[0], "contact": uri, "result": "Registered"}
        return {"verified": False, "result": "Registration not observed"}

    def reboot(self, device_id, requested_by=""):
        device = self.repo.get_device(device_id)
        if not device:
            raise ValueError("Device not found.")
        engine = self._engine_for(device)
        if str(device.get("vendor_code") or "").upper() not in engine.supported_vendors:
            raise ValueError("Vendor is not supported by the DEX provisioning engine.")
        if not device.get("ip_address"):
            raise ValueError("No IP address is available for this device.")

        config = self.repo.get_config()
        pbx_ip = config.get("provisioning_ip") or local_ip_for(device["ip_address"])
        if not pbx_ip:
            raise ValueError("Could not determine a local PBX address for the phone network.")
        path = validate_provisioning_path(config.get("provisioning_path") or "DEXPhone")
        scheme, port, _ = self._endpoint(config, engine)
        url = f"{scheme}://{pbx_ip}:{port}/{path}/"
        operation_id = self.repo.create_operation(device_id, "reboot", requested_by, requested_url=url)
        self.repo.update_operation(operation_id, status="Running", started_at=now())

        # Never deliberately reboot a phone while the PBX reports active
        # calls.  If Asterisk is unavailable, continue but record that the
        # preflight could not be completed; the final result still requires
        # the phone to disappear and return with a SIP registration.
        try:
            import asterisk_helper
            active_calls = asterisk_helper.get_active_call_count()
        except Exception:
            active_calls = None
        if active_calls and active_calls > 0:
            message = "Device Busy: active calls are present."
            self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="preflight", error_message=message)
            self.repo.add_operation_event(operation_id, "Reboot Rejected", {"reason": message, "active_calls": active_calls})
            return {"operation_id": operation_id, "status": "Failed", "message": message}
        self.repo.add_operation_event(operation_id, "Reboot Preflight", {"active_calls": active_calls if active_calls is not None else "unavailable"})

        baseline_online = self._is_reachable(device["ip_address"])
        target_port = self._sip_target_port(device["ip_address"])
        source_port = self._notify_source_port(config, engine)
        result = engine.request_reboot(
            device, pbx_ip, url, source_port,
            config.get("notify_user_agent") or DEFAULT_NOTIFY_USER_AGENT, target_port=target_port,
        )
        if isinstance(result, UnsupportedOperation):
            self.repo.update_operation(operation_id, status="Unsupported", completed_at=now(), error_stage="unsupported", error_message=result.reason)
            self.repo.add_operation_event(operation_id, "Unsupported Operation", {"operation": "reboot", "reason": result.reason})
            return {"operation_id": operation_id, "status": "Unsupported", "message": result.reason}

        timeout = min(max(float(config.get("notify_timeout") or 3.0), 0.5), 15.0)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.bind((pbx_ip, source_port))
            actual_port = sock.getsockname()[1]
            # Rebuild only when an explicitly ephemeral source port was
            # requested. Grandstream's default remains the captured 6060.
            if actual_port != source_port:
                result = engine.request_reboot(
                    device, pbx_ip, url, actual_port,
                    config.get("notify_user_agent") or DEFAULT_NOTIFY_USER_AGENT, target_port=target_port,
                )
            self.repo.update_device_status(device_id, provision_status="Reboot Request Sent", last_sip_status=None, last_error="", last_failure_stage="")
            self.repo.update_operation(operation_id, sent_at=now())
            self.repo.add_operation_event(operation_id, "Reboot Request Sent", {"destination": f"{device['ip_address']}:{target_port}", "event": "check-sync", "content_type": engine.notify_content_type})
            sock.sendto(result["packet"], (device["ip_address"], target_port))
            try:
                response, address = sock.recvfrom(65535)
                sip_status = _parse_sip_status(response)
                self.repo.update_operation(operation_id, sip_response_at=now(), sip_status=sip_status)
                if sip_status != 200:
                    message = f"Phone returned SIP {sip_status or 'unknown'}."
                    self.repo.update_device_status(device_id, provision_status="Failed", last_sip_status=sip_status, last_failure_stage="reboot_request", last_error=message)
                    self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="reboot_request", error_message=message)
                    self.repo.add_operation_event(operation_id, "Reboot Request Rejected", {"status": sip_status, "source": address[0]})
                    return {"operation_id": operation_id, "status": "Failed", "sip_status": sip_status, "message": message}
                self.repo.update_device_status(device_id, provision_status="Reboot Request Accepted", last_sip_status=200)
                self.repo.add_operation_event(operation_id, "Reboot Request Accepted", {"status": 200, "source": address[0]})
            except socket.timeout:
                message = "Reboot request response was not observed before timeout."
                self.repo.update_device_status(device_id, provision_status="Failed", last_failure_stage="reboot_request", last_error=message)
                self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="reboot_request", error_message=message)
                self.repo.add_operation_event(operation_id, "Reboot Request Timeout", {"timeout_seconds": timeout})
                return {"operation_id": operation_id, "status": "Failed", "message": message}
        except OSError as exc:
            message = f"SIP reboot request transport error: {exc}"
            self.repo.update_device_status(device_id, provision_status="Failed", last_failure_stage="reboot_request", last_error=message)
            self.repo.update_operation(operation_id, status="Failed", completed_at=now(), error_stage="reboot_request", error_message=message)
            return {"operation_id": operation_id, "status": "Failed", "message": message}
        finally:
            sock.close()

        # A 200 only acknowledges the SIP request.  Require a reachable
        # device -> offline -> online -> SIP registration sequence before
        # marking the reboot verified.  The bound prevents the Flask request
        # from waiting indefinitely if the phone is powered off.
        deadline = time.monotonic() + 30.0
        offline_at = None
        online_at = None
        registered = None
        while time.monotonic() < deadline:
            reachable = self._is_reachable(device["ip_address"])
            if baseline_online and not reachable and offline_at is None:
                offline_at = time.monotonic()
                self.repo.update_device_status(device_id, provision_status="Device Offline")
                self.repo.add_operation_event(operation_id, "Device Offline")
            elif offline_at is not None and reachable and online_at is None:
                online_at = time.monotonic()
                self.repo.update_device_status(device_id, provision_status="Device Online")
                self.repo.add_operation_event(operation_id, "Device Online")
            if online_at is not None:
                registered = self.verify_registration(device, settle_delay=0.0)
                if registered.get("verified"):
                    self.repo.update_device_status(device_id, provision_status="SIP Registered", last_registered_extension=registered.get("extension", ""))
                    self.repo.add_operation_event(operation_id, "SIP Registered", _safe_details(registered))
                    downtime = round(online_at - offline_at, 3) if offline_at is not None else None
                    self.repo.update_operation(operation_id, status="Completed", completed_at=now(), registration_result=registered.get("result", ""))
                    self.repo.update_device_status(device_id, provision_status="Reboot Verified", last_success_at=now(), last_registered_extension=registered.get("extension", ""), last_error="", last_failure_stage="")
                    self.repo.add_operation_event(operation_id, "Reboot Verified", {"downtime_seconds": downtime})
                    return {"operation_id": operation_id, "status": "Reboot Verified", "sip_status": 200, "registration": registered, "downtime_seconds": downtime}
            time.sleep(0.5)

        message = "Reboot request accepted, but the complete offline/online/SIP registration sequence was not verified."
        self.repo.update_operation(operation_id, status="CompletedWithWarnings", completed_at=now(), error_stage="reboot_verification", error_message=message, registration_result=(registered or {}).get("result", ""))
        self.repo.update_device_status(device_id, provision_status="Reboot Request Accepted", last_error=message, last_failure_stage="reboot_verification")
        self.repo.add_operation_event(operation_id, "Reboot Verification Incomplete", {"offline_observed": offline_at is not None, "online_observed": online_at is not None})
        return {"operation_id": operation_id, "status": "CompletedWithWarnings", "sip_status": 200, "message": message}

    @staticmethod
    def _is_reachable(ip_address):
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", str(ip_address)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=2, check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def delete_device(self, device_id):
        """Delete database state and its MAC file as one recoverable action."""
        device = self.repo.get_device(device_id)
        if not device:
            raise ValueError("Device not found.")
        engine = self._engine_for(device)
        generator = self._generator_for(device)
        filenames = engine.expected_filenames(device["normalized_mac"])
        moved = []
        archive_root = generator.root.parent / (generator.root.name + "-archive")
        for filename in filenames:
            path = generator.root / filename
            if not path.exists():
                continue
            if path.is_symlink():
                raise ValueError("Refusing to delete a symlinked provisioning file.")
            archive_root.mkdir(mode=0o750, parents=True, exist_ok=True)
            archive = archive_root / f"{filename}.deleted.{int(time.time())}.{len(moved)}"
            os.replace(path, archive)
            moved.append((path, archive))
        try:
            normalized = self.repo.delete_device(device_id)
            return normalized
        except Exception:
            for path, archive in reversed(moved):
                if archive.exists() and not path.exists():
                    os.replace(archive, path)
            raise


def parse_options_response(ip, payload):
    text = payload.decode("utf-8", "replace")
    lines = text.splitlines()
    status = _parse_sip_status(payload)
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    ua = headers.get("user-agent", headers.get("server", ""))
    parsed = identify_device_user_agent(ua)
    parsed.update({"ip_address": ip, "response_code": status, "headers": {key: value for key, value in headers.items() if key.lower() not in ("authorization", "proxy-authorization")}})
    return parsed


def sip_options(ip, timeout=1.0, source_ip=None, target_port=5060):
    source_ip = source_ip or local_ip_for(ip)
    branch = "z9hG4bK-" + os.urandom(8).hex()
    tag = os.urandom(8).hex()
    call_id = os.urandom(12).hex() + "@" + source_ip
    target_port = int(target_port or 5060)
    packet = (f"OPTIONS sip:{ip}:{target_port} SIP/2.0\r\nVia: SIP/2.0/UDP {source_ip}:0;branch={branch};rport\r\nTo: <sip:{ip}:{target_port}>\r\nFrom: <sip:{source_ip}>;tag={tag}\r\nCall-ID: {call_id}\r\nCSeq: 1 OPTIONS\r\nMax-Forwards: 70\r\nUser-Agent: RCM7021 DEX Discovery\r\nContent-Length: 0\r\n\r\n").encode("ascii")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.bind((source_ip, 0))
        sock.sendto(packet, (ip, target_port))
        payload, address = sock.recvfrom(65535)
        parsed = parse_options_response(ip, payload)
        parsed["source_port"] = address[1]
        return parsed
    except (OSError, socket.timeout):
        return None
    finally:
        sock.close()
