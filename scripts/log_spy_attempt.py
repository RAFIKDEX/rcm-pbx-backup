#!/usr/bin/env python3
import sys

sys.path.insert(0, "/root/RCM_7021")

import db


def clean_ext(value):
    value = str(value or "").strip()
    return value if value.isdigit() else ""


def main():
    caller = clean_ext(sys.argv[1] if len(sys.argv) > 1 else "")
    target = clean_ext(sys.argv[2] if len(sys.argv) > 2 else "")
    mode = str(sys.argv[3] if len(sys.argv) > 3 else "").strip()
    result = str(sys.argv[4] if len(sys.argv) > 4 else "").strip()
    reason = str(sys.argv[5] if len(sys.argv) > 5 else "").strip()

    if mode not in {"Spy", "Whisper", "Barge"}:
        mode = "Spy"
    if result not in {"allowed", "denied"}:
        result = "denied"

    db.log_spy_attempt(caller, target, mode, result, reason, "asterisk")


if __name__ == "__main__":
    main()
