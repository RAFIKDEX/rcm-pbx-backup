"""Grandstream Plug-and-Play (Zero Config) responder.

GRP phones announce themselves with a SIP SUBSCRIBE to 224.0.1.75:5060
before they have a SIP registration.  The responder acknowledges that
subscription and, when the phone already has a DEX assignment, sends the
Grandstream ua-profile NOTIFY to the Contact port carried by the SUBSCRIBE.
"""

import logging
import re
import socket
import struct
import threading
import time
from urllib.parse import unquote

from .repositories import DexRepository
from .services import ProvisioningService
from .secrets import DexSecretProvider
from .constants import GRANDSTREAM_PNP_SOURCE_PORT

LOG = logging.getLogger("dex.pnp")
PNP_MULTICAST = "224.0.1.75"
SIP_PORT = 5060
DEFAULT_SOURCE_PORT = GRANDSTREAM_PNP_SOURCE_PORT


def _headers(message):
    lines = message.split("\r\n")
    result = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        result.setdefault(name.strip().lower(), value.strip())
    return lines[0] if lines else "", result


def _contact(value):
    match = re.search(r"sip:(?:[^@;<>]+@)?(\d{1,3}(?:\.\d{1,3}){3}):(\d+)", value or "", re.I)
    if not match:
        return None, None
    port = int(match.group(2))
    return match.group(1), port if 1 <= port <= 65535 else None


def parse_pnp_subscribe(payload, source_ip):
    """Parse one Grandstream PnP SUBSCRIBE without retaining credentials."""
    try:
        message = payload.decode("utf-8", "replace")
    except AttributeError:
        return None
    request, headers = _headers(message)
    if not request.upper().startswith("SUBSCRIBE "):
        return None
    destination = request.split()[1] if len(request.split()) > 1 else ""
    event = headers.get("event", "")
    user_agent = headers.get("user-agent", "")
    if (PNP_MULTICAST not in destination or "ua-profile" not in event.lower()
            or headers.get("x-grandstream-pbx", "").lower() != "true"
            or not user_agent.lower().startswith("grandstream ")):
        return None
    mac_match = re.search(r"MAC(?:%3A|:)([0-9a-f]{12})", unquote(destination), re.I)
    model_match = re.match(r"Grandstream\s+(\S+)\s+([^\s]+)", user_agent, re.I)
    contact_ip, contact_port = _contact(headers.get("contact", ""))
    if not mac_match or not model_match or not contact_port:
        return None
    if contact_ip and contact_ip != source_ip:
        return None
    event_model = re.search(r'model="([^"]+)"', event, re.I)
    event_version = re.search(r'version="([^"]+)"', event, re.I)
    return {
        "source_ip": source_ip,
        "mac": mac_match.group(1).lower(),
        "model": event_model.group(1) if event_model else model_match.group(1),
        "firmware": event_version.group(1) if event_version else model_match.group(2),
        "user_agent": user_agent,
        "contact_ip": contact_ip or source_ip,
        "contact_port": contact_port,
        "via": headers.get("via", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "call_id": headers.get("call-id", ""),
        "cseq": headers.get("cseq", ""),
        "event": event,
    }


def build_subscribe_response(pnp, pbx_ip, source_port=DEFAULT_SOURCE_PORT):
    """Build the 202 response observed from Grandstream UCM Zero Config."""
    to = pnp["to"]
    if ";tag=" not in to.lower():
        to += ";tag=" + str(int(time.time() * 1000000))[-10:]
    lines = [
        "SIP/2.0 202 Accepted subscription",
        "Via: " + pnp["via"],
        "From: " + pnp["from"],
        "To: " + to,
        "Call-ID: " + pnp["call_id"],
        "CSeq: " + pnp["cseq"],
        f"Contact: <sip:{pbx_ip}:{int(source_port)}>",
        "Event: " + pnp["event"],
        # GRP26xx uses the UCM PnP responder identity while negotiating the
        # ua-profile subscription.  The provisioning NOTIFY itself continues
        # to identify DEX as RCM7021.
        "User-Agent: Grandstream UCM630X",
        "Expires: 0",
        "Content-Length: 0",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii", "replace")


def _ipv4_udp_payload(frame):
    """Return (source_ip, destination_ip, destination_port, payload)."""
    if len(frame) < 14:
        return None
    ether_type = struct.unpack("!H", frame[12:14])[0]
    offset = 14
    if ether_type in (0x8100, 0x88A8):
        if len(frame) < 18:
            return None
        ether_type = struct.unpack("!H", frame[16:18])[0]
        offset = 18
    if ether_type != 0x0800 or len(frame) < offset + 20:
        return None
    first = frame[offset]
    ihl = (first & 0x0F) * 4
    if (first >> 4) != 4 or len(frame) < offset + ihl + 8 or frame[offset + 9] != 17:
        return None
    source_ip = socket.inet_ntoa(frame[offset + 12:offset + 16])
    destination_ip = socket.inet_ntoa(frame[offset + 16:offset + 20])
    udp = offset + ihl
    destination_port = struct.unpack("!H", frame[udp + 2:udp + 4])[0]
    return source_ip, destination_ip, destination_port, frame[udp + 8:]


class GrandstreamPnpResponder:
    def __init__(self, db_path, interface="ens18", pbx_ip="192.168.99.223", source_port=DEFAULT_SOURCE_PORT):
        self.db_path = db_path
        self.interface = interface
        self.pbx_ip = pbx_ip
        self.source_port = int(source_port)
        self.repo = DexRepository(db_path)
        self.service = ProvisioningService(self.repo, db_path, secret_provider=DexSecretProvider())
        self.seen = {}
        self.provisioned = {}
        self.in_progress = set()

    def _send(self, payload, target):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.pbx_ip, self.source_port))
            sock.sendto(payload, target)
        finally:
            sock.close()

    def _upsert(self, pnp):
        model = self.repo.get_model_by_name("Grandstream", pnp["model"])
        if not model:
            model = self.repo.ensure_discovered_model("Grandstream", pnp["model"], pnp["user_agent"])
        return self.repo.upsert_device({
            "normalized_mac": pnp["mac"],
            "ip_address": pnp["source_ip"],
            "vendor": "Grandstream",
            "detected_model": pnp["model"],
            "model_id": model["id"] if model else None,
            "firmware": pnp["firmware"],
            "raw_user_agent": pnp["user_agent"],
            "mac_source": "Grandstream PnP",
        }, source="Grandstream PnP")

    def handle(self, pnp):
        key = (pnp["mac"], pnp["call_id"])
        now = time.monotonic()
        self.seen = {item: stamp for item, stamp in self.seen.items() if now - stamp < 30}
        self.provisioned = {mac: stamp for mac, stamp in self.provisioned.items() if now - stamp < 60}
        if key in self.seen:
            # SIP retransmissions must receive the same 202 response even
            # when the provisioning work was already handled.
            self._send(build_subscribe_response(pnp, self.pbx_ip, self.source_port), (pnp["source_ip"], pnp["contact_port"]))
            return
        self.seen[key] = now
        self._send(build_subscribe_response(pnp, self.pbx_ip, self.source_port), (pnp["source_ip"], pnp["contact_port"]))
        device_id = self._upsert(pnp)
        self.repo.save_pnp_contact(device_id, pnp["contact_ip"], pnp["contact_port"])
        if pnp["mac"] in self.provisioned or pnp["mac"] in self.in_progress:
            LOG.info("Grandstream PnP already handled mac=%s; skipping duplicate provisioning", pnp["mac"])
            return
        device = self.repo.get_device(device_id)
        ready = bool(device and device.get("model_enabled") and device.get("provisionable") and device.get("sip_account_count") is not None and device.get("blf_count") is not None)
        assigned = any(item.get("enabled") and item.get("extension") for item in (device or {}).get("accounts", []))
        vendor = str((device or {}).get("vendor_code") or (device or {}).get("vendor") or "").upper()
        if vendor == "GRANDSTREAM" and (not assigned or ready):
            # PnP packet handling must stay responsive.  Grandstream may take
            # up to 30 seconds to request the XML, so do the actual publish /
            # NOTIFY exchange in a worker and keep receiving new SUBSCRIBEs.
            baseline = not assigned
            self.in_progress.add(pnp["mac"])
            worker = threading.Thread(
                target=self._provision,
                args=(device_id, pnp, baseline),
                name=f"grandstream-pnp-{pnp['mac']}",
                daemon=True,
            )
            worker.start()
        else:
            LOG.info("Grandstream PnP discovered mac=%s ip=%s model=%s awaiting verified DEX model/assignment", pnp["mac"], pnp["source_ip"], pnp["model"])

    def _provision(self, device_id, pnp, baseline):
        try:
            requested_by = "grandstream-pnp-bootstrap" if baseline else "grandstream-pnp"
            result = self.service.notify(
                device_id,
                requested_by,
                contact_port=pnp["contact_port"],
                source_port_override=self.source_port,
                baseline=baseline,
            )
            LOG.info(
                "Grandstream PnP %s mac=%s ip=%s result=%s",
                "bootstrap" if baseline else "provisioned",
                pnp["mac"], pnp["source_ip"], result.get("status"),
            )
            if result.get("status") in {"Verified", "Bootstrap Downloaded", "Config Downloaded", "Completed", "CompletedWithWarnings"}:
                self.provisioned[pnp["mac"]] = time.monotonic()
        except Exception:
            LOG.exception("Grandstream PnP provisioning failed for %s", pnp.get("mac"))
        finally:
            self.in_progress.discard(pnp["mac"])

    def run(self):
        raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
        raw.bind((self.interface, 0))
        LOG.info("Grandstream PnP listener active on %s for %s:%s", self.interface, PNP_MULTICAST, SIP_PORT)
        try:
            while True:
                frame = raw.recv(65535)
                parsed = _ipv4_udp_payload(frame)
                if not parsed:
                    continue
                source_ip, destination_ip, destination_port, payload = parsed
                if destination_ip != PNP_MULTICAST or destination_port != SIP_PORT:
                    continue
                pnp = parse_pnp_subscribe(payload, source_ip)
                if pnp:
                    try:
                        self.handle(pnp)
                    except Exception:
                        LOG.exception("Grandstream PnP handling failed for %s", pnp.get("mac"))
        finally:
            raw.close()
