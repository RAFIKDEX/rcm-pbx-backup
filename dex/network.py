import fcntl
import http.client
import ipaddress
import re
import socket
import struct
import subprocess

from .validators import normalize_mac


def _interface_ipv4(name, request):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        value = fcntl.ioctl(sock.fileno(), request, struct.pack("256s", name.encode()[:15]))[20:24]
        return socket.inet_ntoa(value)
    except OSError:
        return ""
    finally:
        sock.close()


def local_interfaces():
    result = []
    try:
        names = socket.if_nameindex()
    except OSError:
        # A restricted test/container namespace may deny interface metadata;
        # the page remains usable and the administrator can enter a validated
        # CIDR directly through the API.
        return result
    for _, name in names:
        address = _interface_ipv4(name, 0x8915)
        netmask = _interface_ipv4(name, 0x891b)
        if not address or not netmask or address.startswith("127."):
            continue
        try:
            network = ipaddress.ip_network(f"{address}/{netmask}", strict=False)
        except ValueError:
            continue
        result.append({"name": name, "ip": address, "cidr": str(network), "broadcast": str(network.broadcast_address)})
    return result


def target_from_last_octet(cidr, value):
    network = ipaddress.ip_network(cidr, strict=False)
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or not 0 <= int(raw) <= 255:
        raise ValueError("Enter the final IPv4 octet from 0 to 255.")
    candidate = ipaddress.ip_address(int(network.network_address) + int(raw))
    if candidate not in network or candidate == network.network_address or candidate == network.broadcast_address:
        raise ValueError("The selected host is outside the chosen interface network.")
    return f"{candidate}/32"


def mac_for_ip(ip_address):
    """Resolve a live LAN neighbour MAC without requiring SIP to expose it."""
    target = str(ip_address or "").strip()
    if not target:
        return None
    try:
        result = subprocess.run(
            ["ip", "neigh", "show", target],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=1, check=False,
        )
        text = result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        text = ""
    if not text:
        try:
            with open("/proc/net/arp", "r", encoding="ascii", errors="replace") as handle:
                text = "\n".join(line for line in handle if line.startswith(target + " "))
        except OSError:
            text = ""
    match = re.search(r"(?i)([0-9a-f]{2}(?::[0-9a-f]{2}){5}|[0-9a-f]{12})", text)
    if not match:
        return None
    try:
        return normalize_mac(match.group(1))
    except ValueError:
        return None


def grandstream_model_from_server(server):
    """Return a Grandstream model token from an HTTP Server header."""
    match = re.search(r"\b((?:GRP|GXP|GXV|GAC|GVC|GDS|GXW|DP|WP)[A-Za-z0-9._-]*)\b", str(server or ""), re.IGNORECASE)
    return match.group(1) if match else None


def grandstream_http_identity(ip_address, timeout=0.7):
    """Read a Grandstream model from an HTTP Server header when SIP is down."""
    target = str(ip_address or "").strip()
    if not target:
        return None
    connection = None
    try:
        connection = http.client.HTTPConnection(target, 80, timeout=timeout)
        connection.request("HEAD", "/")
        response = connection.getresponse()
        server = str(response.getheader("Server") or "").strip()
        model = grandstream_model_from_server(server)
        if not model:
            return None
        return {"model": model, "server": server, "response_code": response.status}
    except (OSError, http.client.HTTPException):
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
