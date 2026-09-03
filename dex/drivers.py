import re
import socket
import uuid
from datetime import datetime, timezone

from .constants import (
    DEX_DRIVER_NAME, GRANDSTREAM_DRIVER_NAME, DEFAULT_NOTIFY_CONTENT_TYPE,
    DEFAULT_NOTIFY_EVENT, DEFAULT_NOTIFY_USER_AGENT,
)
from .validators import normalize_mac, safe_filename


class UnsupportedOperation:
    def __init__(self, operation, reason):
        self.operation = operation
        self.reason = reason
        self.supported = False

    def __bool__(self):
        return False


class FanvilFiberMeProvisioningEngine:
    """Verified shared syntax/trigger implementation for FiberMe and Fanvil."""

    name = DEX_DRIVER_NAME
    supported_vendors = {"FIBERME", "FANVIL"}
    provisioning_scheme = "https"
    notify_content_type = DEFAULT_NOTIFY_CONTENT_TYPE

    def identify_device(self, raw_user_agent):
        raw = str(raw_user_agent or "").strip()
        # Real devices emit all three common MAC spellings in User-Agent:
        # compact, colon-separated, and hyphen-separated.
        mac_pattern = r"(?:[0-9a-fA-F]{12}|[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}|[0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})"
        match = re.match(rf"^(FIBERME|Fanvil)\s+(.+?)\s+([0-9][^\s]*)\s+({mac_pattern})$", raw)
        if not match:
            return {"vendor": "", "model": "", "firmware": "", "normalized_mac": None, "raw_user_agent": raw, "confidence": "Unknown"}
        vendor = "FiberMe" if match.group(1).upper() == "FIBERME" else "Fanvil"
        return {"vendor": vendor, "model": match.group(2).strip(), "firmware": match.group(3), "normalized_mac": normalize_mac(match.group(4)), "raw_user_agent": raw, "confidence": "Confirmed"}

    def expected_filename(self, normalized_mac):
        return safe_filename(f"{normalize_mac(normalized_mac)}.cfg")

    def expected_filenames(self, normalized_mac):
        return (self.expected_filename(normalized_mac),)

    def build_notify(self, pbx_ip, device_ip, body, source_port=0, user_agent=DEFAULT_NOTIFY_USER_AGENT, event=DEFAULT_NOTIFY_EVENT, target_port=5060, content_type=None):
        source = int(source_port or 0)
        if not (0 <= source <= 65535):
            raise ValueError("Invalid SIP source port.")
        branch = "z9hG4bK-" + uuid.uuid4().hex
        tag = uuid.uuid4().hex
        call_id = uuid.uuid4().hex + "@" + pbx_ip
        via = f"SIP/2.0/UDP {pbx_ip}:{source};branch={branch};rport"
        lines = [
            "NOTIFY sip:%s:%s SIP/2.0" % (device_ip, int(target_port or 5060)),
            f"Via: {via}",
            f"To: <sip:{device_ip}:{int(target_port or 5060)}>",
            f"From: <sip:{pbx_ip}:{source}>;tag={tag}",
            f"Call-ID: {call_id}",
            "CSeq: 1 NOTIFY",
            "Max-Forwards: 70",
            f"User-Agent: {user_agent}",
            f"Content-Type: {content_type or self.notify_content_type}",
            f"Event: {event}",
            f"Content-Length: {len(body.encode('utf-8'))}",
            "",
            body,
        ]
        return "\r\n".join(lines).encode("utf-8")

    def request_reboot(self, device, pbx_ip=None, url=None, source_port=0, user_agent=DEFAULT_NOTIFY_USER_AGENT, target_port=5060):
        """Build the verified shared reboot trigger for FiberMe/Fanvil phones.

        The trigger is intentionally separate from the provisioning trigger:
        the body is the provisioning directory, but the SIP event is
        ``check-sync``.  The caller must still observe the phone going away
        and returning before treating the operation as verified.
        """
        vendor = str(device.get("vendor_code") or device.get("vendor") or "").upper()
        if vendor not in self.supported_vendors:
            return UnsupportedOperation("reboot", "Reboot is supported only for FiberMe and Fanvil devices.")
        device_ip = str(device.get("ip_address") or "").strip()
        if not device_ip:
            return UnsupportedOperation("reboot", "No IP address is available for this device.")
        if not pbx_ip or not url:
            return UnsupportedOperation("reboot", "The PBX provisioning URL is not configured.")
        packet = self.build_notify(
            pbx_ip, device_ip, url, source_port, user_agent, event="check-sync", target_port=target_port
        )
        return {
            "supported": True,
            "event": "check-sync",
            "content_type": DEFAULT_NOTIFY_CONTENT_TYPE,
            "url": url,
            "packet": packet,
        }

    def map_key_type(self, semantic_type):
        # Verified mapping from supplied FiberMe/Fanvil syntax: 1 is a
        # monitored BLF/value key, 2 is a line key, 0 is unused.  The mapping
        # is only used when the model explicitly says BLF mapping is verified.
        mapping = {"BLF": 1, "Line": 2, "None": 0}
        if semantic_type not in mapping:
            return UnsupportedOperation("blf", f"Semantic key type {semantic_type} is not verified for this driver.")
        return mapping[semantic_type]

    def render_account_lines(self, account, extension, registrar, sip_port, password, display_name):
        index = int(account)
        prefix = f"SIP{index}"
        return [
            f"{prefix} Phone Number       :{extension}",
            f"{prefix} Display Name       :{display_name}",
            f"{prefix} Register Addr      :{registrar}",
            f"{prefix} Register Port      :{sip_port}",
            f"{prefix} Register User      :{extension}",
            f"{prefix} Register Pswd      :{password}",
            f"{prefix} Enable Reg         :1",
        ]

    def render_blf_lines(self, key):
        mapped = self.map_key_type(key.get("semantic_type", "None"))
        if isinstance(mapped, UnsupportedOperation):
            return mapped
        index = int(key["key_index"])
        value = key.get("value", "")
        if mapped == 1 and key.get("pickup"):
            value = f"{value}@{key.get('account_index') or 1}/b{key['pickup']}"
        elif mapped == 2:
            account_index = key.get("account_index") or 1
            value = f"SIP{account_index}"
        lines = [f"Fkey{index} Type               :{mapped}", f"Fkey{index} Value              :{value}", f"Fkey{index} Title              :{key.get('title', '')}", f"Fkey{index} ICON               :Green"]
        return lines


class GrandstreamProvisioningEngine:
    """Grandstream XML/HTTP provisioning trigger validated on GRP2602P/GXV3350."""

    name = GRANDSTREAM_DRIVER_NAME
    supported_vendors = {"GRANDSTREAM"}
    # Factory GRP26xx firmware defaults Config Upgrade via HTTPS and the
    # GRP2602P 1.0.7.64 phone redirects its web service from HTTP to HTTPS.
    # Use the existing DEX HTTPS provisioning listener for Grandstream.
    provisioning_scheme = "https"
    # The captured, working UCM packet uses application/url.  GRP26xx may
    # acknowledge application/x-gs-ucm-url with SIP 200 but not fetch the URL.
    notify_content_type = "application/url"

    def identify_device(self, raw_user_agent):
        raw = str(raw_user_agent or "").strip()
        mac_pattern = r"(?:[0-9a-fA-F]{12}|[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}|[0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})"
        match = re.match(rf"^Grandstream\s+(.+?)\s+([0-9][^\s]*)(?:\s+({mac_pattern}))?$", raw, re.IGNORECASE)
        if not match:
            return {"vendor": "", "model": "", "firmware": "", "normalized_mac": None, "raw_user_agent": raw, "confidence": "Unknown"}
        normalized = normalize_mac(match.group(3)) if match.group(3) else None
        return {
            "vendor": "Grandstream", "model": match.group(1).strip(),
            "firmware": match.group(2), "normalized_mac": normalized,
            "raw_user_agent": raw, "confidence": "Confirmed" if normalized else "Model Only",
        }

    def expected_filename(self, normalized_mac):
        return safe_filename(f"cfg{normalize_mac(normalized_mac)}.xml")

    def expected_filenames(self, normalized_mac):
        normalized = normalize_mac(normalized_mac)
        return (safe_filename(f"cfg{normalized}"), safe_filename(f"cfg{normalized}.xml"))

    def build_notify(self, pbx_ip, device_ip, body, source_port=0, user_agent=DEFAULT_NOTIFY_USER_AGENT, event=DEFAULT_NOTIFY_EVENT, target_port=5060, content_type=None):
        source = int(source_port or 0)
        if not (0 <= source <= 65535):
            raise ValueError("Invalid SIP source port.")
        # Grandstream's captured UCM transaction uses the RFC branch cookie
        # followed directly by the transaction id (no extra hyphen).
        branch = "z9hG4bK" + uuid.uuid4().hex
        tag = uuid.uuid4().hex
        call_id = uuid.uuid4().hex + "@" + pbx_ip
        port = int(target_port or 5060)
        # Match the working Grandstream/UCM trace captured from the PBX.
        via = f"SIP/2.0/UDP {pbx_ip}:{source};branch={branch}"
        lines = [
            f"NOTIFY sip:{device_ip}:{port} SIP/2.0",
            f"Via: {via}", f"From: <sip:{pbx_ip}:{source}>;tag={tag}",
            f"To: <sip:{device_ip}:{port}>", f"Call-ID: {call_id}",
            "CSeq: 1 NOTIFY", f"Contact: <sip:{pbx_ip}:{source}>",
            f"Content-Type: {content_type or self.notify_content_type}",
            "Max-Forwards: 70",
            f"User-Agent: {user_agent}", f"Event: {event}",
            f"Content-Length: {len(body.encode('utf-8'))}", "", body,
        ]
        return "\r\n".join(lines).encode("utf-8")

    def request_reboot(self, device, pbx_ip=None, url=None, source_port=0, user_agent=DEFAULT_NOTIFY_USER_AGENT, target_port=5060):
        vendor = str(device.get("vendor_code") or device.get("vendor") or "").upper()
        if vendor not in self.supported_vendors:
            return UnsupportedOperation("reboot", "Reboot is supported only for Grandstream devices.")
        device_ip = str(device.get("ip_address") or "").strip()
        if not device_ip:
            return UnsupportedOperation("reboot", "No IP address is available for this device.")
        if not pbx_ip or not url:
            return UnsupportedOperation("reboot", "The PBX provisioning URL is not configured.")
        packet = self.build_notify(
            pbx_ip, device_ip, url, source_port, user_agent,
            event="check-sync", target_port=target_port,
        )
        return {
            "supported": True,
            "event": "check-sync",
            "content_type": self.notify_content_type,
            "url": url,
            "packet": packet,
        }

    def map_key_type(self, semantic_type):
        if semantic_type == "BLF":
            return "BLF"
        return UnsupportedOperation("blf", f"Grandstream semantic key type {semantic_type} is not verified for this model.")

    def render_blf_parts(self, key):
        """Return the verified GRP pks.vpk item grammar for one BLF key."""
        mapped = self.map_key_type(key.get("semantic_type", "None"))
        if isinstance(mapped, UnsupportedOperation):
            return mapped
        index = int(key["key_index"])
        if index < 1:
            raise ValueError("Grandstream BLF key index must be positive.")
        value = str(key.get("value") or "").strip()
        if not value:
            raise ValueError(f"Grandstream BLF key {index} requires a value.")
        account = int(key.get("account_index") or 1)
        description = str(key.get("title") or value).strip()
        return {
            "name": f"pks.vpk.{index}",
            "parts": (
                ("lockMode", "No"),
                ("description", description),
                ("value", value),
                ("keyMode", mapped),
                ("account", f"Account{account}"),
            ),
        }


def identify_device_user_agent(raw_user_agent):
    """Identify all DEX-supported phone families from a SIP User-Agent."""
    for engine in (FanvilFiberMeProvisioningEngine(), GrandstreamProvisioningEngine()):
        parsed = engine.identify_device(raw_user_agent)
        if parsed.get("vendor"):
            return parsed
    return FanvilFiberMeProvisioningEngine().identify_device(raw_user_agent)
