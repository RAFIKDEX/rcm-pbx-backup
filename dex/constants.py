from pathlib import Path

DEX_SCHEMA_VERSION = 10
DEX_DRIVER_NAME = "Fanvil/FiberMe Shared Engine"
GRANDSTREAM_DRIVER_NAME = "Grandstream XML Engine"
SUPPORTED_VENDORS = ("FiberMe", "Fanvil", "Grandstream")
ENGINE_KEY = "fanvil_fiberme"
PROVISION_ROOT = Path("/var/lib/rcm/provisioning/DEXPhone")
PROVISION_URL_PATH = "/DEXPhone/"
PROVISION_PORT = 8090
PROVISION_ACCESS_LOG = "/var/lib/rcm/dex/provisioning_access.log"
PROVISION_HTTP_PORT = 8091
PROVISION_HTTP_ACCESS_LOG = "/var/lib/rcm/dex/provisioning_http_access.log"
DEFAULT_NOTIFY_USER_AGENT = "RCM7021"
DEFAULT_NOTIFY_EVENT = "ua-profile"
DEFAULT_NOTIFY_CONTENT_TYPE = "application/url"
GRANDSTREAM_PNP_SOURCE_PORT = 6060
MODEL_FAP2730P = "FAP2730P"
MODEL_X6U = "X6U"
MODEL_GRP2602P = "GRP2602P"
MODEL_GXV3350 = "GXV3350"
DEVICE_STATUSES = (
    "Unknown Model", "Model Defined", "Ready for Configuration",
    "Config Generated", "Config Published", "NOTIFY Sent",
    "NOTIFY Accepted", "Config Requested", "Config Downloaded",
    "Applying", "Registered", "Verified", "Reboot Request Sent",
    "Reboot Request Accepted", "Device Offline", "Device Online",
    "SIP Registered", "Reboot Verified", "Failed",
    "Awaiting SIP Registration",
)
OPERATION_STATUSES = ("Pending", "Running", "Completed", "CompletedWithWarnings", "Failed", "Unsupported")
SEMANTIC_KEY_TYPES = ("BLF", "Speed Dial", "Line", "DTMF", "None")
