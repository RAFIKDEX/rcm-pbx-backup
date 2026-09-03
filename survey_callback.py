#!/usr/bin/env python3
import sys
import os
import uuid
import time
import shutil

def main():
    if len(sys.argv) < 6:
        print("Usage: survey_callback.py SURVEY_ID CUSTOMER_NUM MEMBERINTERFACE QUEUE_NUM SURVEY_CALLBACK_EXTEN")
        sys.exit(1)

    survey_id = sys.argv[1]
    customer_num = sys.argv[2]
    member = sys.argv[3]
    queue_num = sys.argv[4]
    exten = sys.argv[5]

    if not customer_num or len(customer_num) < 3:
        # Avoid callback if no valid caller ID
        sys.exit(0)

    # We use a short delay before generating the call file to ensure the channel is fully hung up
    time.sleep(2)

    call_file_content = f"""Channel: Local/{customer_num}@from-internal
Callerid: "{exten}" <{exten}>
MaxRetries: 1
RetryTime: 30
WaitTime: 45
Context: rcm_survey
Extension: s
Priority: 1
Set: SURVEY_ID={survey_id}
Set: QUEUE_NUM={queue_num}
Set: MEMBERINTERFACE={member}
Set: CUSTOMER_NUM={customer_num}
"""

    temp_path = f"/tmp/survey_{uuid.uuid4().hex}.call"
    with open(temp_path, "w") as f:
        f.write(call_file_content)

    os.chmod(temp_path, 0o666)
    try:
        shutil.move(temp_path, "/var/spool/asterisk/outgoing/")
    except Exception as e:
        print(f"Failed to move call file: {e}")

if __name__ == "__main__":
    main()
