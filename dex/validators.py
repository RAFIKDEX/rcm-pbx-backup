import ipaddress
import re
from pathlib import PurePosixPath

MAC_RE = re.compile(r"^[0-9a-fA-F]{12}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")


def normalize_mac(value):
    raw = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    if not MAC_RE.fullmatch(raw):
        raise ValueError("MAC address must contain exactly 12 hexadecimal characters.")
    normalized = raw.lower()
    if normalized == "ffffffffffff" or int(normalized[:2], 16) & 1:
        raise ValueError("Multicast and broadcast MAC addresses are not valid phone identities.")
    return normalized


def display_mac(value):
    normalized = normalize_mac(value)
    return ":".join(normalized[index:index + 2].upper() for index in range(0, 12, 2))


def validate_ip(value, allow_blank=False):
    value = str(value or "").strip()
    if not value and allow_blank:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("Enter a valid IPv4 or IPv6 address.") from exc
    if address.version != 4:
        raise ValueError("DEX currently accepts IPv4 phone addresses only.")
    return str(address)


def validate_host(value, allow_blank=False, label="Host"):
    """Validate an IPv4 address or DNS hostname used by a phone setting."""
    value = str(value or "").strip()
    if not value and allow_blank:
        return ""
    try:
        return validate_ip(value)
    except ValueError:
        if len(value) > 253 or not HOSTNAME_RE.fullmatch(value):
            raise ValueError(f"{label} must be a valid IPv4 address or hostname.")
        return value.rstrip(".")


def validate_config_text(value, label, max_length=512, allow_blank=True):
    value = str(value or "").strip()
    if not value and not allow_blank:
        raise ValueError(f"{label} is required.")
    if len(value) > max_length or "\r" in value or "\n" in value or "\x00" in value:
        raise ValueError(f"{label} contains invalid or oversized text.")
    return value


def validate_ldap_filter(value, label):
    value = validate_config_text(value, label, max_length=1024, allow_blank=False)
    if not value.startswith("(") or not value.endswith(")"):
        raise ValueError(f"{label} must be a complete LDAP filter.")
    depth = 0
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"{label} has unbalanced parentheses.")
    if escaped or depth != 0:
        raise ValueError(f"{label} has unbalanced parentheses.")
    return value


def safe_filename(value):
    name = str(value or "").strip()
    if not SAFE_FILENAME_RE.fullmatch(name) or ".." in name or "/" in name or "\\" in name:
        raise ValueError("Filename contains unsafe characters.")
    if PurePosixPath(name).name != name:
        raise ValueError("Filename must not contain a path.")
    return name


def validate_common_filename(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return safe_filename(value)


def validate_provisioning_path(value):
    path = str(value or "").strip().strip("/")
    if not path or len(path) > 80 or not re.fullmatch(r"[A-Za-z0-9_-]+", path):
        raise ValueError("Provisioning path must be one safe URL segment.")
    return path


def validate_count(value, minimum, label, allow_unknown=False):
    if value in (None, "") and allow_unknown:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if parsed < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return parsed


def validate_scan_cidr(cidr, max_hosts=256):
    try:
        network = ipaddress.ip_network(str(cidr).strip(), strict=False)
    except ValueError as exc:
        raise ValueError("Enter a valid IPv4 network.") from exc
    if network.version != 4:
        raise ValueError("DEX discovery accepts IPv4 networks only.")
    hosts = list(network.hosts())
    if len(hosts) > max_hosts:
        raise ValueError(f"Scan is limited to {max_hosts} hosts.")
    return network
