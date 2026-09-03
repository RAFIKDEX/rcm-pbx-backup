import sys
sys.path.append('/root/RCM_7021')
from storage_providers import get_provider_instance
import os

local_path = '/var/spool/asterisk/monitor/rcm-178746795559-queue-6500-5555-20260823-095235.wav'
ext_path = 'Recordings/2026/08/23/rcm-178746795559-queue-6500-5555-20260823-095235.wav'

provider = get_provider_instance(1)
if provider.connect():
    print("Connected.")
    upload_ok, uploaded_path, err = provider.upload_file(local_path, ext_path)
    print(f"Upload OK: {upload_ok}, Path: {uploaded_path}, Error: {err}")
else:
    print(f"Connect failed: {provider.last_error}")
