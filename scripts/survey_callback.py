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
        with open("/tmp/survey_callback.log", "a") as log:
            log.write(f"[{time.ctime()}] Ignored callback for short customer_num: {customer_num}\n")
        # Avoid callback if no valid caller ID
        sys.exit(0)

    with open("/tmp/survey_callback.log", "a") as log:
        log.write(f"[{time.ctime()}] Initiating callback for survey_id={survey_id}, customer_num={customer_num}, member={member}, queue_num={queue_num}, exten={exten}\n")

    # We use a short delay before generating the call file to ensure the channel is fully hung up
    time.sleep(2)

    context_str = f"from-internal-{exten}" if exten else "from-internal"
    callerid_str = f'"{exten}" <{exten}>' if exten else f'"Survey Callback" <{queue_num}>'

    call_file_content = f"""Channel: Local/{customer_num}@{context_str}
Callerid: {callerid_str}
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
Set: IS_SURVEY_CALLBACK=1
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
