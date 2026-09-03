#!/usr/bin/env python3
"""Run the DEX Grandstream Plug-and-Play responder."""

import logging
import os

from dex.pnp import GrandstreamPnpResponder


logging.basicConfig(
    level=os.environ.get("DEX_PNP_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

db_path = os.environ.get("DEX_DB_PATH", "/root/RCM_7021/rcm_7021.db")
interface = os.environ.get("DEX_PNP_INTERFACE", "ens18")
pbx_ip = os.environ.get("DEX_PNP_IP", "192.168.99.223")
source_port = int(os.environ.get("DEX_PNP_SOURCE_PORT", "6060"))

GrandstreamPnpResponder(db_path, interface=interface, pbx_ip=pbx_ip, source_port=source_port).run()
